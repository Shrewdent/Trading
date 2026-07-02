"""App config: theme, last-used settings, Alpaca keys. Stored in git-ignored config.json."""

import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULTS = {
    "alpaca": {"api_key": "", "secret_key": ""},
    "theme": "dark",
    "last_used": {
        "ticker": "SPY",
        "strategy": "ma_crossover",
        "start_date": "2020-01-01",
        "end_date": "2025-01-01",
    },
}


def load() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return json.loads(json.dumps(DEFAULTS))
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(DEFAULTS))
    merged = json.loads(json.dumps(DEFAULTS))
    merged.update({k: v for k, v in cfg.items() if k != "alpaca" and k != "last_used"})
    merged["alpaca"].update(cfg.get("alpaca", {}))
    merged["last_used"].update(cfg.get("last_used", {}))
    return merged


def save(cfg: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def has_alpaca_keys() -> bool:
    cfg = load()
    keys = cfg.get("alpaca", {})
    api_key = keys.get("api_key", "").strip()
    secret_key = keys.get("secret_key", "").strip()
    placeholder = {"YOUR_ALPACA_PAPER_API_KEY", "YOUR_ALPACA_PAPER_SECRET_KEY", ""}
    return api_key not in placeholder and secret_key not in placeholder
