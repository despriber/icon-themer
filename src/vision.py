"""Generate a theme draft from a desktop-background image, via a vision model.

Uses a separately-configured chat model (settings.vision -> falls back to the
image relay's base_url/api_key, but the model name must be set explicitly).
The model is asked to look at the wallpaper and emit a JSON theme spec in the
same spirit as themes/oneshot.json, which the user then edits before saving.
"""
import base64
import json
import mimetypes

from openai import OpenAI

import settings as settings_mod

SYSTEM_PROMPT = """\
You are an art director for a desktop-icon restyling tool. The user gives you \
their desktop wallpaper. Derive a single coherent ART STYLE from it and output a \
reusable icon-style spec, so every app icon redrawn in this style will feel like \
it belongs on that wallpaper.

Return ONLY a JSON object (no prose, no code fences) with exactly these keys:
- "display_name": short human label for the style, e.g. "Synthwave Neon" (may use the wallpaper's mood).
- "base_prompt": a single rich English paragraph describing the art style for an \
image model. Cover: medium/technique, the color palette (give concrete hex codes \
drawn from the wallpaper), lighting, shading approach, mood, composition (single \
centered icon subject, bold readable silhouette, generous margin, plain solid \
background that exists only to be cleanly removed — no app badge/frame/ground \
shadow), and an explicit list of things to avoid (text, letters, UI windows, \
screenshots, photorealism unless intended). It must instruct: keep the subject's \
identifying shapes and signature colors recognizable while applying the style.
- "pixel_art": object {"enabled": bool, "source_size": int, "colors": int}. \
Set enabled true ONLY for pixel/retro/8-bit/16-bit styles (then source_size ~32, \
colors ~32); otherwise enabled false, source_size 32, colors 32.

Output the JSON object and nothing else."""


def _data_url(image_path: str) -> str:
    mime = mimetypes.guess_type(image_path)[0] or "image/png"
    b64 = base64.b64encode(open(image_path, "rb").read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _extract_json(text: str) -> dict:
    """Tolerate code fences / extra prose around the JSON object."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if t.count("```") >= 2 else t.strip("`")
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    try:
        return json.loads(t)
    except ValueError:
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(t[start:end + 1])
        raise


def describe_theme_from_background(image_path: str) -> dict:
    """Call the vision model and return a theme draft dict (name left blank)."""
    cfg = settings_mod.vision_config()
    if not cfg["model"]:
        raise RuntimeError("未配置视觉模型。请在「设置 → 视觉模型」中填写模型名。")
    if not cfg["api_key"]:
        raise RuntimeError("未找到 API key,请在「设置」中填写。")

    client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    print(f"[vision] base_url={cfg['base_url']} model={cfg['model']}")
    resp = client.chat.completions.create(
        model=cfg["model"],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": "Here is my desktop wallpaper. Produce the theme spec JSON."},
                {"type": "image_url", "image_url": {"url": _data_url(image_path)}},
            ]},
        ],
    )
    content = resp.choices[0].message.content or ""
    draft = _extract_json(content)

    pa = draft.get("pixel_art") or {}
    return {
        "name": "",
        "display_name": draft.get("display_name", "新主题"),
        "size": "1024x1024",
        "base_prompt": draft.get("base_prompt", ""),
        "pixel_art": {
            "enabled": bool(pa.get("enabled", False)),
            "source_size": int(pa.get("source_size", 32) or 32),
            "colors": int(pa.get("colors", 32) or 32),
        },
    }
