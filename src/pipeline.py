"""End-to-end: one app + one theme -> restyled .ico, then optionally apply it.

Usage (from project root):
    python src/pipeline.py --app chrome --theme oneshot
    python src/pipeline.py --app chrome --theme oneshot --apply
"""
import argparse
import subprocess
from pathlib import Path

from config import IMAGE_MODEL, OUTPUT_DIR, POWERSHELL_SCRIPTS_DIR, get_app, load_theme
from generate import generate
from postprocess import to_ico


def apply_icon(shortcut: str, ico_path: Path):
    ps1 = POWERSHELL_SCRIPTS_DIR / "apply.ps1"
    cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(ps1),
        "-ShortcutPath", shortcut,
        "-IcoPath", str(ico_path.resolve()),
    ]
    print(f"[apply] {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--theme", default="oneshot")
    ap.add_argument("--apply", action="store_true", help="apply the .ico to the shortcut")
    ap.add_argument("--skip-generate", action="store_true",
                    help="reuse existing PNG, only redo postprocess/apply")
    args = ap.parse_args()

    app = get_app(args.app)
    theme = load_theme(args.theme)

    png = OUTPUT_DIR / f"{app['key']}_{theme['name']}.png"
    if not args.skip_generate:
        png = generate(app, theme)
    elif not png.exists():
        raise FileNotFoundError(
            f"generated PNG missing for --skip-generate: {png}. "
            f"Run without --skip-generate first to create it with {IMAGE_MODEL}."
        )

    ico = to_ico(png, theme=theme)

    if args.apply:
        apply_icon(app["shortcut"], ico)
        print("[done] icon applied. If the desktop doesn't refresh, log off/on or restart explorer.")
    else:
        print(f"[done] icon ready: {ico}\n      add --apply to set it on the shortcut.")


if __name__ == "__main__":
    main()
