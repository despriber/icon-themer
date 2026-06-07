"""User-editable model settings (overrides the Codex CLI defaults).

settings.json (repo root, local only — holds plaintext keys, never committed):

  {
    "image":  {"base_url": "", "api_key": "", "model": "gpt-image-2",
               "edit_enabled": true},
    "vision": {"base_url": "", "api_key": "", "model": ""}
  }

Any blank field falls back: image -> codex_credentials()/IMAGE_MODEL; vision's
base_url/api_key -> the resolved image config (so a single relay can serve both),
but the vision model name has no default and must be set by the user.
"""
import json

from config import IMAGE_MODEL, ROOT, codex_credentials

SETTINGS_FILE = ROOT / "settings.json"

_DEFAULTS = {
    "image": {"base_url": "", "api_key": "", "model": "", "edit_enabled": True,
              "bg_removal": True},
    "vision": {"base_url": "", "api_key": "", "model": ""},
}


def load_settings() -> dict:
    data = {}
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = {}
    # merge onto defaults so missing keys never KeyError
    out = {k: dict(v) for k, v in _DEFAULTS.items()}
    for section in ("image", "vision"):
        for k, v in (data.get(section) or {}).items():
            out[section][k] = v
    return out


def save_settings(data: dict) -> None:
    out = {k: dict(v) for k, v in _DEFAULTS.items()}
    for section in ("image", "vision"):
        for k, v in (data.get(section) or {}).items():
            out[section][k] = v
    SETTINGS_FILE.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _normalize_base_url(base_url: str | None) -> str | None:
    """Ensure the base_url ends with '/v1' (the OpenAI SDK appends '/images/edits'
    etc.). A user pasting 'https://relay.example.com/' would otherwise hit the
    wrong path. Mirrors the normalization in config.codex_credentials()."""
    if not base_url:
        return base_url
    base_url = base_url.strip().rstrip("/")
    if not base_url.endswith("/v1"):
        base_url += "/v1"
    return base_url


def image_config() -> dict:
    """Resolved image-generation config: settings override, Codex as fallback."""
    s = load_settings()["image"]
    cx_key, cx_url = codex_credentials()
    return {
        "base_url": _normalize_base_url((s.get("base_url") or "").strip() or cx_url),
        "api_key": (s.get("api_key") or "").strip() or cx_key,
        "model": (s.get("model") or "").strip() or IMAGE_MODEL,
        "edit_enabled": bool(s.get("edit_enabled", True)),
        "bg_removal": bool(s.get("bg_removal", True)),
    }


def vision_config() -> dict:
    """Resolved vision (theme-from-background) config. base_url/api_key fall back
    to the image config; model must be configured explicitly."""
    s = load_settings()["vision"]
    img = image_config()
    return {
        "base_url": _normalize_base_url((s.get("base_url") or "").strip()) or img["base_url"],
        "api_key": (s.get("api_key") or "").strip() or img["api_key"],
        "model": (s.get("model") or "").strip(),
    }


def edit_enabled() -> bool:
    return image_config()["edit_enabled"]


def bg_removal_enabled() -> bool:
    """Whether the post-processing chroma-key background removal runs. When the
    image model/relay can't emit a transparent background, this is the only way
    to get a non-square icon; disable it to keep the generated background."""
    return image_config()["bg_removal"]
