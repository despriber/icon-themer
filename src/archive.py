"""Per-app archive of generated icons, so past generations stay viewable.

Layout:
  output/archive/<stem>/<ts>_<theme>.png   (the styled source PNG)
  output/archive/<stem>/<ts>_<theme>.ico   (the built icon, applied to desktop)
  output/archive/<stem>/<ts>_<theme>_preview.png  (pixel themes only)
  output/archive/index.json   { app_key: [ {ts, theme, engine, png, ico, preview, prompt} ] }

`ts` is a sortable "YYYYMMDD_HHMMSS" stamp (collision-suffixed if needed).
"""
import json
from datetime import datetime
from pathlib import Path

from config import OUTPUT_DIR

ARCHIVE_DIR = OUTPUT_DIR / "archive"
INDEX_FILE = ARCHIVE_DIR / "index.json"


def _load_index() -> dict:
    if INDEX_FILE.exists():
        try:
            return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def _save_index(idx: dict) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(
        json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def new_slot(stem: str, theme_name: str) -> dict:
    """Reserve a fresh, collision-free archive slot. Returns paths to write into.

    Returns {ts, dir, png, ico} — caller writes the PNG to `png` and points the
    .ico builder at `ico` (its *_preview.png lands beside it), then calls
    add_entry() with the resulting files.
    """
    d = ARCHIVE_DIR / stem
    d.mkdir(parents=True, exist_ok=True)
    base_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ts = base_ts
    n = 1
    while (d / f"{ts}_{theme_name}.ico").exists():
        n += 1
        ts = f"{base_ts}_{n}"
    stub = d / f"{ts}_{theme_name}"
    return {
        "ts": ts,
        "dir": str(d),
        "png": str(stub.with_name(stub.name + ".png")),
        "ico": str(stub.with_name(stub.name + ".ico")),
    }


def add_entry(app_key: str, ts: str, theme: str, engine: str,
              png: str, ico: str, preview: str | None, prompt: str = "") -> dict:
    idx = _load_index()
    entry = {
        "ts": ts, "theme": theme, "engine": engine,
        "png": png, "ico": ico,
        "preview": preview or png, "prompt": prompt,
    }
    idx.setdefault(app_key, []).append(entry)
    _save_index(idx)
    return entry


def list_entries(app_key: str) -> list[dict]:
    """Existing-on-disk entries for an app, newest first."""
    idx = _load_index()
    entries = [e for e in idx.get(app_key, []) if Path(e.get("ico", "")).exists()]
    return sorted(entries, key=lambda e: e.get("ts", ""), reverse=True)


def delete_entry(app_key: str, ts: str) -> None:
    idx = _load_index()
    kept = []
    for e in idx.get(app_key, []):
        if e.get("ts") == ts:
            for k in ("png", "ico", "preview"):
                p = e.get(k)
                if p:
                    try:
                        Path(p).unlink()
                    except OSError:
                        pass
        else:
            kept.append(e)
    idx[app_key] = kept
    _save_index(idx)
