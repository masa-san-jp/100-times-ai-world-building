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

from .premises import contract_checks_enabled, proposed_extension, world_premises
from .quantities import is_counter, observed_units

from .verify import (
    ContrastProvider, Deduction, LLMJudge, Similarity, VerifierResult,
    language_of, load_language_rules, rules_for, reference_text, verify_consistency, verify_genericity,
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
    premise_extension: Dict[str, Any] = field(default_factory=dict)
    premise_review: Dict[str, Any] = field(default_factory=dict)

    def deductions_for(self, verifier: str) -> List[Deduction]:
        return [d for d in self.deductions if d.verifier == verifier]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scores": {k: round(v, 4) for k, v in self.scores.items()},
            "reward": round(self.reward, 4), "passed": self.passed,
            "failed": list(self.failed), "skipped": list(self.skipped),
            "premise_extension": copy.deepcopy(self.premise_extension),
            "premise_review": copy.deepcopy(self.premise_review),
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
        siblings: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> VerificationResult:
        """Score one candidate.

        ``siblings`` are the other independent candidates generated for the
        same slot; wording they share with the candidate counts as the
        model's default (genericity).
        """
        cfg, lang = self.config, language_of(graph)
        results: Dict[str, VerifierResult] = {}

        reference = reference_text(graph, candidate.get("target"), brief)
        gcfg = cfg.get("genericity", {})
        contrast: Sequence[Mapping[str, Any]] = []
        if self.contrasts is not None:
            contrast = self.contrasts.get(
                candidate["operator"], graph, candidate.get("target"))
        results["genericity"] = verify_genericity(
            candidate, contrast, self.similarity, gcfg,
            siblings=siblings, reference=reference)
        results["provenance"] = verify_provenance(
            candidate, graph, brief, cfg.get("provenance"))
        results["specificity"] = verify_specificity(
            candidate, lang, self.rules, cfg.get("specificity"),
            reference=reference)
        results["consistency"] = verify_consistency(
            candidate, graph, axes, brief, cfg.get("consistency"))
        results["objectivity"] = verify_objectivity(
            candidate, lang, self.rules, cfg.get("objectivity"))
        results["novelty"] = verify_novelty(
            candidate, graph, self.similarity, cfg.get("novelty"))

        weights = cfg.get("weights", {})
        thresholds = cfg.get("thresholds", {})
        ran = [n for n in VERIFIERS if not results[n].skipped]
        total_w = sum(float(weights.get(n, 0)) for n in ran)

        def verdict():
            reward = (sum(float(weights.get(n, 0)) * results[n].score for n in ran)
                      / total_w) if total_w > 0 else 0.0
            failed = [n for n in ran if results[n].score < float(thresholds.get(n, 0.0))]
            return reward, failed, not failed and reward >= float(thresholds.get("total", 0.0))

        entity = candidate["entity"]
        contract = (world_premises(graph) or entity.get("world_premises", {})) if contract_checks_enabled(graph) else {}
        units = observed_units(entity, contract, rules_for(self.rules, lang))
        extension = proposed_extension(entity, world_premises(graph), rules_for(self.rules, lang))
        approved = False
        raw_response = None
        raw_response_text = None
        # Review every surviving quantity and social claim, even if the
        # configured optional criteria omit consistency. No extra call.
        required = bool(contract and (units or any(not is_counter(u, rules_for(self.rules, lang))
                        for u in (entity.get("premise_usage") or {}).get("units", []))
                        or contract.get("society") or extension))
        criteria = []
        review_state = "disabled" if self.judge is None else "deterministic_rejection"
        # Judges only deduct, so a deterministic rejection cannot be rescued.
        # Pending capability proposals are resolved after this check.
        if self.judge is not None and verdict()[2]:
            criteria = [n for n in cfg.get("llm_judges") or [] if n in results]
            if required and "consistency" not in criteria:
                criteria.append("consistency")
            assessments = self.judge.judge_many(criteria, candidate, graph, brief, axes=axes)
            raw_response = copy.deepcopy(self.judge.last_response)
            raw_response_text = self.judge.last_response_text
            consistency = assessments.get("consistency")
            review_state = ("reviewed" if consistency and consistency.review_usable
                            else "missing_or_invalid" if "consistency" in criteria else "not_requested")
            for name, assessment in assessments.items():
                r = results[name]
                r.deductions += assessment.deductions
                r.score = max(0.0, r.score - sum(d.penalty for d in assessment.deductions))
                if name == "consistency":
                    approved = assessment.extension_approved
            if required and review_state == "missing_or_invalid":
                r = results["consistency"]
                amount = float(cfg.get("consistency", {}).get("penalties", {}).get("review_missing", 0.4))
                r.deductions.append(Deduction("consistency", "entity", "review_missing",
                    "quantity or social premises need a usable consistency review; repair the review response", amount))
                r.score = max(0.0, r.score - amount)
        if extension and not approved and (extension.get("capabilities") or self.judge is not None):
            r = results["consistency"]
            amount = float(cfg.get("consistency", {}).get("penalties", {}).get("undefined_technology", 0.4))
            r.deductions.append(Deduction(
                "consistency", "premise_usage", "undefined_technology" if extension.get("capabilities") else "extension_unapproved",
                "new units or capabilities need explicit consistency approval of their derivation within technology.description limits",
                amount, {"proposal": extension}))
            r.score = max(0.0, r.score - amount)
        reward, failed, passed = verdict()
        scores = {n: results[n].score for n in ran}
        result = VerificationResult(
            scores=scores, reward=reward, passed=passed, failed=failed,
            deductions=[d for n in VERIFIERS for d in results[n].deductions],
            skipped=[n for n in VERIFIERS if results[n].skipped],
            premise_extension=extension if approved and passed else {},
            premise_review={"usage": copy.deepcopy(entity.get("premise_usage", {})),
                "inferred": copy.deepcopy(entity.get("premise_usage_inferred", {})),
                "observed_units": units, "proposal": copy.deepcopy(extension),
                "proposal_state": ("no_contract" if not world_premises(graph) else
                    "no_usage" if not entity.get("premise_usage") else
                    "reason_missing" if not (entity.get("provenance") or {}).get("reason") else
                    "proposed" if extension else "no_new_terms"),
                "criteria": list(dict.fromkeys(criteria)), "state": review_state,
                "raw_response": raw_response, "raw_response_text": raw_response_text,
                "extension_status": ("eligible" if approved and passed and extension else
                    "candidate_rejected" if approved and extension else
                    "unapproved" if extension else "no_proposal"),
                "extension_approved": approved,
                "reason_present": bool((entity.get("provenance") or {}).get("reason"))})
        if store:
            candidate["entity"]["scores"] = {
                **candidate["entity"].get("scores", {}),
                **{k: round(v, 4) for k, v in scores.items()},
                "reward": round(reward, 4)}
        return result


__all__ = [
    "RewardVerifier", "VERIFIERS", "VerificationResult", "load_reward_config",
]
