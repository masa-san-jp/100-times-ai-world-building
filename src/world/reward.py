"""Load parameters for the retained deterministic checks; no adoption scoring."""
import copy
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
DEFAULT_REWARD_PATH = CONFIG_DIR / "world" / "reward.yaml"

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
    """Load ``reward.yaml`` and deep-merge ``overrides`` for deterministic verifier parameters."""
    cfg = yaml.safe_load(
        Path(path or DEFAULT_REWARD_PATH).read_text(encoding="utf-8")) or {}
    return _merge(cfg, overrides or {})
