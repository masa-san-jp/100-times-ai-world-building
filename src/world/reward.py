"""Composite reward over the verifiers in :mod:`src.world.verify`.

``reward = sum(weight * score) / sum(weight)`` over the verifiers that ran,
so it lies in [0, 1].  Weights and thresholds live in
``config/world/reward.yaml``.  The structured result carries per-verifier
scores, pass/fail per threshold and deduction reasons for critique and
rewrite.

Typical use (#32)::

    rv = RewardVerifier(contrasts=ContrastProvider(runner, package_dir))
    result = rv.verify(graph, candidate, brief=brief, axes=axes)
    result.reward, result.passed, result.failed, result.deductions
    # scores are also stored in candidate["entity"]["scores"]
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import yaml

from .verify import (
    ContrastProvider, Deduction, LLMJudge, Similarity, VerifierResult,
    language_of, load_language_rules, verify_consistency, verify_genericity,
    verify_novelty, verify_objectivity, verify_provenance, verify_specificity,
)

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
DEFAULT_REWARD_PATH = CONFIG_DIR / "world" / "reward.yaml"

VERIFIERS = (
    "genericity", "provenance", "specificity", "consistency", "objectivity",
    "novelty",
)


def _merge(base: Dict[str, Any], over: Mapping[str, Any]) -> Dict[str, Any]:
    for k, v in over.items():
        if isinstance(v, Mapping) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = copy.deepcopy(v)
    return base


def load_reward_config(
    path: Any = None, overrides: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Load ``reward.yaml`` and deep-merge ``overrides`` (e.g. new weights)."""
    cfg = yaml.safe_load(
        Path(path or DEFAULT_REWARD_PATH).read_text(encoding="utf-8")) or {}
    return _merge(cfg, overrides or {})


@dataclass
class VerificationResult:
    scores: Dict[str, float]
    reward: float
    passed: bool
    failed: List[str]                  # verifiers below their threshold
    deductions: List[Deduction] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)

    def deductions_for(self, verifier: str) -> List[Deduction]:
        return [d for d in self.deductions if d.verifier == verifier]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scores": {k: round(v, 4) for k, v in self.scores.items()},
            "reward": round(self.reward, 4), "passed": self.passed,
            "failed": list(self.failed), "skipped": list(self.skipped),
            "deductions": [d.to_dict() for d in self.deductions],
        }


class RewardVerifier:
    """Score candidates and combine the scores into a reward."""

    def __init__(
        self, config: Optional[Mapping[str, Any]] = None,
        rules: Optional[Mapping[str, Any]] = None,
        contrasts: Optional[ContrastProvider] = None,
        similarity: Optional[Similarity] = None,
        judge: Optional[LLMJudge] = None,
    ) -> None:
        self.config = dict(config) if config is not None else load_reward_config()
        self.rules = dict(rules) if rules is not None else load_language_rules()
        self.contrasts = contrasts
        self.similarity = similarity
        self.judge = judge

    def verify(
        self, graph: Mapping[str, Any], candidate: Mapping[str, Any], *,
        brief: Optional[Mapping[str, Any]] = None,
        axes: Optional[Sequence[Mapping[str, Any]]] = None,
        store: bool = True,
    ) -> VerificationResult:
        cfg, lang = self.config, language_of(graph)
        results: Dict[str, VerifierResult] = {}

        if self.contrasts is not None:
            gcfg = cfg.get("genericity", {})
            contrast = self.contrasts.get(
                candidate["operator"], graph, candidate.get("target"))
            results["genericity"] = verify_genericity(
                candidate, contrast, self.similarity, gcfg)
        else:
            results["genericity"] = VerifierResult(
                "genericity", 1.0, [], skipped=True)
        results["provenance"] = verify_provenance(
            candidate, graph, brief, cfg.get("provenance"))
        results["specificity"] = verify_specificity(
            candidate, lang, self.rules, cfg.get("specificity"))
        results["consistency"] = verify_consistency(
            candidate, graph, axes, brief, cfg.get("consistency"))
        results["objectivity"] = verify_objectivity(
            candidate, lang, self.rules, cfg.get("objectivity"))
        results["novelty"] = verify_novelty(
            candidate, graph, self.similarity, cfg.get("novelty"))

        if self.judge is not None:
            for name in cfg.get("llm_judges") or []:
                extra = self.judge.judge(name, candidate, graph) \
                    if name in results else None
                if extra:
                    r = results[name]
                    r.deductions += extra
                    r.score = max(0.0, r.score - sum(d.penalty for d in extra))

        weights = cfg.get("weights", {})
        thresholds = cfg.get("thresholds", {})
        ran = [n for n in VERIFIERS if not results[n].skipped]
        total_w = sum(float(weights.get(n, 0)) for n in ran)
        reward = (sum(float(weights.get(n, 0)) * results[n].score for n in ran)
                  / total_w) if total_w > 0 else 0.0
        failed = [n for n in ran
                  if results[n].score < float(thresholds.get(n, 0.0))]
        passed = not failed and reward >= float(thresholds.get("total", 0.0))
        scores = {n: results[n].score for n in ran}
        result = VerificationResult(
            scores=scores, reward=reward, passed=passed, failed=failed,
            deductions=[d for n in VERIFIERS for d in results[n].deductions],
            skipped=[n for n in VERIFIERS if results[n].skipped])
        if store:
            candidate["entity"]["scores"] = {
                **candidate["entity"].get("scores", {}),
                **{k: round(v, 4) for k, v in scores.items()},
                "reward": round(reward, 4)}
        return result


__all__ = [
    "RewardVerifier", "VERIFIERS", "VerificationResult", "load_reward_config",
]
