"""Per-app theming / hide state for icon-themer.

state.json maps a stable app key -> what we changed, so every operation is
reversible *exactly* (we capture the real original IconLocation before the
first change, instead of guessing a default).

Key = "<directory>::<original .lnk filename>".  It is stable across the
non-breaking-space rename used to hide names, because we remember the
hidden_name and reverse-map scanned files back to their original key.
"""
import json

from config import NAME_BACKUP_FILE, STATE_FILE

ARROWS_KEY = "__arrows__"


def make_key(directory: str, original_name: str) -> str:
    return f"{directory}::{original_name}"


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            state = {}
    else:
        state = {}
    _import_legacy_name_backup(state)
    return state


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_entry(state: dict, key: str):
    return state.get(key)


def ensure_entry(state: dict, key: str, directory: str, original_name: str,
                 item_type: str = "shortcut") -> dict:
    entry = state.get(key)
    if entry is None:
        entry = {
            "type": item_type,
            "directory": directory,
            "original_name": original_name,
            "hidden_name": None,
            "original_icon_location": None,
            "good_thumb": None,      # last good thumbnail (survives name-hide)
            "themed": False,
            "ico_path": None,
            "theme": None,
        }
        state[key] = entry
    else:
        entry.setdefault("type", item_type)
        entry.setdefault("good_thumb", None)
    return entry


def find_by_hidden(state: dict, directory: str, name: str):
    """Return (key, entry) for a shortcut currently renamed to `name`."""
    for key, entry in state.items():
        if key == ARROWS_KEY:
            continue
        if entry.get("hidden_name") == name and entry.get("directory") == directory:
            return key, entry
    return None, None


def capture_original_icon(entry: dict, current_location: str) -> None:
    """Record the true IconLocation before the first theming change."""
    if not entry.get("original_icon_location") and not entry.get("themed"):
        entry["original_icon_location"] = current_location or ""


def arrows_hidden(state: dict) -> bool:
    return bool(state.get(ARROWS_KEY, {}).get("hidden"))


def set_arrows_hidden(state: dict, hidden: bool) -> None:
    state[ARROWS_KEY] = {"hidden": bool(hidden)}


def _import_legacy_name_backup(state: dict) -> None:
    """One-time migration of the old flat name_backup.json into state.json."""
    if not NAME_BACKUP_FILE.exists():
        return
    try:
        entries = json.loads(NAME_BACKUP_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return
    changed = False
    for e in entries or []:
        directory = e.get("Directory")
        original = e.get("OriginalName")
        hidden = e.get("HiddenName")
        if not directory or not original:
            continue
        key = make_key(directory, original)
        if key not in state:
            state[key] = {
                "directory": directory,
                "original_name": original,
                "hidden_name": hidden,
                "original_icon_location": None,
                "themed": False,
                "ico_path": None,
                "theme": None,
            }
            changed = True
    if changed:
        # rename so we don't re-import; keep a copy for safety
        try:
            NAME_BACKUP_FILE.rename(NAME_BACKUP_FILE.with_suffix(".json.imported"))
        except OSError:
            pass
        save_state(state)
