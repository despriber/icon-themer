"""Live desktop shortcut scanning, merged with per-app state."""
import json
import subprocess
from pathlib import Path

from config import CACHE_DIR, POWERSHELL_SCRIPTS_DIR
import operations
import state as state_mod


def _strip_lnk(name: str) -> str:
    return name[:-4] if name.lower().endswith(".lnk") else name


def run_scan() -> list[dict]:
    """Invoke scan_shortcuts.ps1 and return the raw shortcut records."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_json = CACHE_DIR / "_scan.json"
    ps1 = POWERSHELL_SCRIPTS_DIR / "scan_shortcuts.ps1"
    cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(ps1),
        "-OutJson", str(out_json),
        "-CacheDir", str(CACHE_DIR),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    if not out_json.exists():
        return []
    data = json.loads(out_json.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [data]
    return data or []


def scan_apps() -> list[dict]:
    """Return desktop items (shortcuts + folders) merged with state."""
    records = run_scan()
    state = state_mod.load_state()
    dirty = False
    apps = []

    for rec in records:
        directory = rec.get("Directory", "")
        name = rec.get("Name", "")
        item_type = rec.get("Type", "shortcut")

        # Only shortcuts can be name-hidden (via the U+00A0 rename). A folder is
        # never matched as hidden.
        key = entry = None
        name_hidden = False
        if item_type == "shortcut":
            key, entry = state_mod.find_by_hidden(state, directory, name)
            name_hidden = entry is not None
        if entry is not None:
            original_name = entry["original_name"]
        else:
            original_name = name
            key = state_mod.make_key(directory, original_name)
            entry = state_mod.get_entry(state, key)

        # Reconcile stale hidden_name: entry says hidden, but the on-disk file
        # carries its normal name -> it isn't actually hidden anymore.
        if entry and not name_hidden and entry.get("hidden_name"):
            entry["hidden_name"] = None
            dirty = True

        themed = bool(entry and entry.get("themed"))

        # Card thumbnail: ALWAYS the app's own original icon (its real logo), never
        # the themed/pixel result — the grid is a stable picker that doesn't follow
        # the theme. ensure_orig_thumb recovers + caches the original (resolving the
        # shortcut's target), so name-hidden/themed apps still show a clean icon.
        if entry is not None:
            thumb = operations.ensure_orig_thumb(entry, rec) or rec.get("Thumb", "")
            if entry.get("orig_thumb"):
                dirty = True
        else:
            thumb = rec.get("Thumb", "")

        # Original icons are real (not pixel art) -> always smooth-scale on the card.
        pixel = False

        apps.append({
            "key": key,
            "path": rec.get("Path", ""),
            "name": name,
            "type": item_type,
            "directory": directory,
            "original_name": original_name,
            "display_name": _strip_lnk(original_name),
            "target": rec.get("TargetPath", ""),
            "icon_location": rec.get("IconLocation", ""),
            "working_dir": rec.get("WorkingDirectory", ""),
            "thumb": thumb,
            "pixel": pixel,
            "name_hidden": name_hidden,
            "themed": themed,
            "theme": (entry or {}).get("theme"),
            "ico_path": (entry or {}).get("ico_path"),
        })

    if dirty:
        state_mod.save_state(state)
    apps.sort(key=lambda a: (a["type"] != "folder", a["display_name"].lower()))
    return apps


if __name__ == "__main__":
    for a in scan_apps():
        flags = []
        if a["themed"]:
            flags.append(f"theme={a['theme']}")
        if a["name_hidden"]:
            flags.append("name-hidden")
        print(f"{a['display_name']:<30} {' '.join(flags)}")
