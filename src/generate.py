"""Generate a restyled icon PNG using OpenAI GPT Image.

Two engines:
  - generate_edit(): img2img. Sends the app's *current* icon to images.edit so
    any app restyles faithfully. No `background` param (it 502s on the relay).
  - generate_text(): pure text-to-image via images.generate (fallback).
"""
import base64

from openai import OpenAI

from config import OUTPUT_DIR
import settings as settings_mod


def _client_and_model():
    cfg = settings_mod.image_config()
    if not cfg["api_key"]:
        raise RuntimeError(
            "未找到 API key。请在「设置」里填写,或设置环境变量 OPENAI_API_KEY / "
            "确保 ~/.codex/auth.json 存在。"
        )
    print(f"[generate] base_url={cfg['base_url']} model={cfg['model']}")
    return OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"]), cfg["model"]


def _save(b64: str, out_stem: str, theme: dict):
    if not b64:
        raise RuntimeError("image response did not include b64_json data")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_png = OUTPUT_DIR / f"{out_stem}_{theme['name']}.png"
    out_png.write_bytes(base64.b64decode(b64))
    print(f"[generate] saved {out_png}")
    return out_png


def build_prompt(theme, app):
    return (
        f"{theme['base_prompt']}\n\n"
        f"Create an app icon representing: {app['identity']}.\n"
        "Do not include letters, words, browser windows, screenshots, or UI chrome. "
        "Preserve the app logo's distinctive geometry and identifying colors as much "
        "as possible while applying the requested art style."
    )


def style_prompt(theme: dict, display_name: str, identity: str | None = None) -> str:
    """Prompt for an arbitrary desktop app (no hand-written identity needed)."""
    if identity:
        subject = f"Create an app icon representing: {identity}."
    else:
        subject = (
            f"Restyle this application icon for \"{display_name}\" into the art "
            "style described above. Keep its core silhouette, distinctive shapes "
            "and identifying colors clearly recognizable."
        )
    return (
        f"{theme['base_prompt']}\n\n{subject}\n"
        "Do not add letters, words, screenshots, or UI chrome."
    )


def generate_edit(image_path, theme: dict, prompt: str, out_stem: str):
    """img2img: restyle an existing icon image via images.edit."""
    client, model = _client_and_model()
    print(f"[generate] stem={out_stem} mode=edit (img2img)")
    with open(image_path, "rb") as fh:
        resp = client.images.edit(
            model=model,
            image=fh,
            prompt=prompt,
            size=theme.get("size", "1024x1024"),
        )
    return _save(resp.data[0].b64_json, out_stem, theme)


def generate_text(theme: dict, prompt: str, out_stem: str):
    """Pure text-to-image via images.generate."""
    client, model = _client_and_model()
    print(f"[generate] stem={out_stem} mode=generate (text)")
    resp = client.images.generate(
        model=model,
        prompt=prompt,
        size=theme.get("size", "1024x1024"),
    )
    return _save(resp.data[0].b64_json, out_stem, theme)


def generate(app, theme):
    """Legacy CLI path: text-to-image from a hand-written app identity."""
    return generate_text(theme, build_prompt(theme, app), app["key"])


if __name__ == "__main__":
    import argparse
    from config import get_app, load_theme

    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--theme", default="oneshot")
    args = ap.parse_args()
    generate(get_app(args.app), load_theme(args.theme))
