"""User settings for the engine and the extension: profile, allowed apps, autopilot.
Stored in data/settings.json (git-ignored). The extension edits these through
the local API; nothing here needs .env changes."""
import json, threading, time
from copy import deepcopy
from .config import ROOT, MODE

SETTINGS_PATH = ROOT / "data" / "settings.json"
ALL_APPS = ("gmail", "calendar", "slack", "airtable")

DEFAULTS = {
    "onboarded": False,
    "profile": {"email": "", "name": ""},
    "allowed_apps": list(ALL_APPS),
    "autopilot": {
        "enabled": False,        # watch Granola and act on new meetings
        "armed": False,          # allow real sends (set by the user, with a warning)
        "poll_minutes": 2,
        "only_my_meetings": True,
        "enabled_at": None,      # only meetings created after this are processed
    },
    "created_at": None,
    "updated_at": None,
}

_lock = threading.Lock()

def _merge(base: dict, patch: dict) -> dict:
    out = deepcopy(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out

def load() -> dict:
    with _lock:
        if not SETTINGS_PATH.exists():
            return deepcopy(DEFAULTS)
        try:
            return _merge(DEFAULTS, json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
        except ValueError:
            return deepcopy(DEFAULTS)

def _clean(patch: dict) -> dict:
    """Keep only known keys, with the right types."""
    out = {}
    if "onboarded" in patch:
        out["onboarded"] = bool(patch["onboarded"])
    if isinstance(patch.get("profile"), dict):
        p = patch["profile"]
        out["profile"] = {k: str(p.get(k, "")).strip()[:200] for k in ("email", "name") if k in p}
    if "allowed_apps" in patch:
        apps = patch["allowed_apps"] if isinstance(patch["allowed_apps"], list) else []
        out["allowed_apps"] = [a for a in ALL_APPS if a in apps]
    if isinstance(patch.get("autopilot"), dict):
        a, ap = patch["autopilot"], {}
        for k in ("enabled", "armed", "only_my_meetings"):
            if k in a:
                ap[k] = bool(a[k])
        if "poll_minutes" in a:
            try:
                ap["poll_minutes"] = min(60, max(1, int(a["poll_minutes"])))
            except (TypeError, ValueError):
                pass
        out["autopilot"] = ap
    return out

def update(patch: dict) -> dict:
    """Merge a partial update and save. Returns the full settings."""
    current = load()
    clean = _clean(patch)
    new = _merge(current, clean)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    # Remember when autopilot was switched on, so only later meetings are processed.
    if new["autopilot"]["enabled"] and not current["autopilot"]["enabled"]:
        new["autopilot"]["enabled_at"] = now
    if not new["autopilot"]["enabled"]:
        new["autopilot"]["enabled_at"] = None
    new["created_at"] = current.get("created_at") or now
    new["updated_at"] = now
    with _lock:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(new, indent=2), encoding="utf-8")
    return new

def is_armed(settings: dict | None = None) -> bool:
    """Real sends are allowed when the user armed autopilot in the extension,
    or when .env says FOLLOWTHROUGH_MODE=real."""
    s = settings or load()
    return bool(s["autopilot"]["armed"]) or MODE == "real"
