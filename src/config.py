"""Shared paths and helpers for icon-themer."""
import json
import os
try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # Python 3.10 and earlier
    import tomli as tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- Credentials: reuse the Codex CLI config (key + relay base_url) ---
CODEX_DIR = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
IMAGE_MODEL = "gpt-image-2"


def codex_credentials():
    """Return (api_key, base_url) from env vars or the Codex CLI config.

    Env overrides win: OPENAI_API_KEY / OPENAI_BASE_URL.
    The OpenAI SDK appends '/images/edits' etc., so base_url ends with '/v1'.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL")

    if not api_key:
        auth = CODEX_DIR / "auth.json"
        if auth.exists():
            api_key = json.loads(auth.read_text(encoding="utf-8")).get("OPENAI_API_KEY")

    if not base_url:
        cfg = CODEX_DIR / "config.toml"
        if cfg.exists():
            data = tomllib.loads(cfg.read_text(encoding="utf-8"))
            provider_name = data.get("model_provider", "")
            providers = data.get("model_providers") or {}
            provider = providers.get(provider_name, {})
            base_url = provider.get("base_url")

    if base_url:
        base_url = base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url += "/v1"

    return api_key, base_url
INPUT_DIR = ROOT / "input"
OUTPUT_DIR = ROOT / "output"
THEMES_DIR = ROOT / "themes"
APPS_FILE = ROOT / "apps.json"
ASSETS_DIR = ROOT / "assets"
POWERSHELL_SCRIPTS_DIR = ROOT / "scripts" / "windows"
CACHE_DIR = OUTPUT_DIR / "cache"        # extracted current-icon thumbnails
STATE_FILE = ROOT / "state.json"        # per-app theming / hide state
NAME_BACKUP_FILE = ROOT / "name_backup.json"  # legacy, imported once into state

# Multi-resolution sizes baked into every generated .ico
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def load_apps():
    # apps.json is an optional, developer-specific list of identity hints.
    # The GUI scans the live desktop, so a missing file is fine -> no hints.
    if not APPS_FILE.exists():
        return []
    return json.loads(APPS_FILE.read_text(encoding="utf-8")).get("apps", [])


def get_app(key):
    for app in load_apps():
        if app["key"] == key:
            return app
    raise KeyError(f"app '{key}' not found in {APPS_FILE}")


def load_theme(name):
    path = THEMES_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def theme_path(name: str) -> Path:
    return THEMES_DIR / f"{name}.json"


def _slugify(name: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9_-]+", "-", (name or "").strip().lower()).strip("-_")
    return slug or "theme"


def save_theme(spec: dict) -> str:
    """Write a theme JSON. `spec` needs at least name + base_prompt. Returns the
    resolved slug name (filename stem)."""
    name = _slugify(spec.get("name") or spec.get("display_name") or "theme")
    out = {
        "name": name,
        "display_name": spec.get("display_name") or name,
        "size": spec.get("size") or "1024x1024",
        "pixel_art": spec.get("pixel_art") or {
            "enabled": False, "source_size": 32, "colors": 32,
        },
        "base_prompt": spec.get("base_prompt", ""),
    }
    if spec.get("palette"):
        out["palette"] = spec["palette"]
    THEMES_DIR.mkdir(parents=True, exist_ok=True)
    theme_path(name).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return name


def delete_theme(name: str) -> None:
    p = theme_path(name)
    if p.exists():
        p.unlink()


def list_themes():
    """Return [{name, display_name}] for every themes/*.json."""
    themes = []
    for path in sorted(THEMES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        themes.append({
            "name": data.get("name", path.stem),
            "display_name": data.get("display_name", data.get("name", path.stem)),
        })
    return themes
