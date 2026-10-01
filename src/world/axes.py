"""Decide the world's axes (domains and weights) from an input brief.

The domain catalog is a coverage checklist.  The backend proposes weights and
world-specific meanings; this module validates everything it returns so that
no axis is ungrounded, no weight is zero, and every catalog domain is present.
Later stages reference axes by ``id`` and allocate budget by ``weight``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

import yaml

from ..llm import LLMBackend

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
DEFAULT_CATALOG_PATH = CONFIG_DIR / "world" / "domains.yaml"
DEFAULT_PROMPT_PATH = CONFIG_DIR / "prompts" / "world_axes.yaml"

NO_INPUT_REASON = (
    "not touched by the input but needed for the world to function"
)


class CatalogError(ValueError):
    """Raised when the domain catalog is malformed."""


@dataclass(frozen=True)
class WorldAxesResult:
    axes: List[Dict[str, Any]]
    axes_path: Path

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(json.dumps({"axes": self.axes}, ensure_ascii=False))


def load_catalog(path: Union[str, Path, None] = None) -> Dict[str, Any]:
    data = yaml.safe_load(
        Path(path or DEFAULT_CATALOG_PATH).read_text(encoding="utf-8")
    )
    if not isinstance(data, Mapping) or not data.get("domains"):
        raise CatalogError("catalog must define domains")
    ids = set()
    for domain in data["domains"]:
        if not isinstance(domain, Mapping) or not domain.get("id") \
                or not domain.get("name"):
            raise CatalogError("each domain needs id and name")
        if domain["id"] in ids:
            raise CatalogError(f"duplicate domain id: {domain['id']}")
        ids.add(domain["id"])
    return dict(data)


def load_prompt(path: Union[str, Path, None] = None) -> Dict[str, str]:
    data = yaml.safe_load(
        Path(path or DEFAULT_PROMPT_PATH).read_text(encoding="utf-8")
    )
    return dict(data["world_axes"])


class WorldAxesBuilder:
    """Turn an input brief into a validated ``world_axes.json``."""

    def __init__(
        self,
        backend: LLMBackend,
        output_dir: Union[str, Path],
        catalog: Optional[Mapping[str, Any]] = None,
        prompt: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.backend = backend
        self.output_dir = Path(output_dir)
        self.catalog = dict(catalog) if catalog else load_catalog()
        self.prompt = dict(prompt) if prompt else load_prompt()
        self.min_weight = float(self.catalog.get("min_weight", 0.05))
        self.ungrounded_max = float(
            self.catalog.get("ungrounded_max_weight", 0.3)
        )
        self.max_added = int(self.catalog.get("max_added_axes", 6))
        if not 0 < self.min_weight <= 1:
            raise CatalogError("min_weight must be in (0, 1]")

    def build(self, brief: Mapping[str, Any]) -> WorldAxesResult:
        response = self.backend.generate_json(
            self._render_prompt(brief),
            system_prompt=self.prompt.get("system"),
        )
        axes = self._validate(response, brief)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / "world_axes.json"
        path.write_text(
            json.dumps({"axes": axes}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return WorldAxesResult(axes=axes, axes_path=path)

    def _render_prompt(self, brief: Mapping[str, Any]) -> str:
        def lines(items: Any, with_id: bool = True) -> str:
            out = [
                f"{i['id']}: {i['text']}" if with_id else str(i["text"])
                for i in items or []
                if isinstance(i, Mapping) and i.get("text")
            ]
            return "\n".join(out) or "(none)"

        catalog = "\n".join(
            f"{d['id']}: {d['name']}" for d in self.catalog["domains"]
        )
        return self.prompt["user"].format(
            statements=lines(brief.get("statements")),
            open_questions=lines(brief.get("open_questions"), False),
            constraints=lines(brief.get("constraints"), False),
            catalog=catalog,
        )

    def _weight(self, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return self.min_weight
        if value != value:  # NaN
            return self.min_weight
        return round(min(1.0, max(self.min_weight, float(value))), 4)

    @staticmethod
    def _text(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    def _validate(
        self, response: Any, brief: Mapping[str, Any]
    ) -> List[Dict[str, Any]]:
        valid_ids = {
            s["id"] for s in brief.get("statements", []) or []
            if isinstance(s, Mapping) and "id" in s
        }
        proposals = []
        if isinstance(response, Mapping) and isinstance(
            response.get("axes"), list
        ):
            proposals = [p for p in response["axes"] if isinstance(p, Mapping)]

        catalog = {d["id"]: d for d in self.catalog["domains"]}
        by_domain: Dict[str, Dict[str, Any]] = {}
        added: List[Dict[str, Any]] = []
        for p in proposals:
            ids = p.get("statement_ids", [])
            ids = [
                i for i in dict.fromkeys(ids if isinstance(ids, list) else [])
                if isinstance(i, str) and i in valid_ids
            ]
            reason = self._text(p.get("reason"))
            domain = p.get("domain")
            entry = {
                "meaning": self._text(p.get("meaning")),
                "weight": self._weight(p.get("weight")),
                "statement_ids": ids,
                "reason": reason,
                "name": self._text(p.get("name")),
            }
            if isinstance(domain, str) and domain in catalog:
                by_domain.setdefault(domain, entry)  # first proposal wins
            elif len(added) < self.max_added and entry["name"] \
                    and entry["meaning"] and (ids or reason):
                added.append(entry)

        axes: List[Dict[str, Any]] = []
        for domain_id, d in catalog.items():
            entry = by_domain.get(domain_id)
            if entry is None:
                axes.append(self._axis(
                    domain_id, d["name"], d.get("description", ""),
                    self.min_weight, [], NO_INPUT_REASON, "catalog",
                ))
                continue
            axes.append(self._axis(
                domain_id, d["name"],
                entry["meaning"] or d.get("description", ""),
                entry["weight"], entry["statement_ids"], entry["reason"],
                "catalog",
            ))
        used = {a["id"] for a in axes}
        for entry in added:
            slug = re.sub(r"[^a-z0-9]+", "_", entry["name"].lower()).strip("_")
            base = f"x_{slug}" if slug else "x"
            axis_id, n = base, 1
            while axis_id in used:
                n += 1
                axis_id = f"{base}_{n}"
            used.add(axis_id)
            axes.append(self._axis(
                axis_id, entry["name"], entry["meaning"], entry["weight"],
                entry["statement_ids"], entry["reason"], "added",
            ))
        return axes

    def _axis(
        self, axis_id: str, name: str, meaning: str, weight: float,
        statement_ids: List[str], reason: str, origin: str,
    ) -> Dict[str, Any]:
        if not statement_ids:
            weight = min(weight, max(self.ungrounded_max, self.min_weight))
            reason = reason or NO_INPUT_REASON
        return {
            "id": axis_id,
            "name": name,
            "meaning": meaning,
            "weight": weight,
            "grounds": {"statement_ids": statement_ids, "reason": reason},
            "origin": origin,
        }


def load_axes(path: Union[str, Path]) -> List[Dict[str, Any]]:
    """Read ``world_axes.json`` for later stages (reference axes by id)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))["axes"]


__all__ = [
    "CatalogError", "NO_INPUT_REASON", "WorldAxesBuilder", "WorldAxesResult",
    "load_axes", "load_catalog", "load_prompt",
]
