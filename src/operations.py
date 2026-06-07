"""High-level, GUI-facing operations: generate, apply, upload, hide, restore.

Assumes the process is running elevated (see app.py): renames of Public-Desktop
shortcuts and HKLM registry writes happen in-process; COM IconLocation writes
go through small PowerShell helpers (inherit the admin token, no extra UAC).
"""
import hashlib
import os
import re
import shutil
import subprocess
import time
import winreg
from contextlib import contextmanager
from pathlib import Path

from config import (
    ASSETS_DIR, CACHE_DIR, OUTPUT_DIR, POWERSHELL_SCRIPTS_DIR, load_theme,
)
from generate import generate_edit, generate_text, style_prompt
from postprocess import to_ico
import archive
import settings as settings_mod
import state as state_mod

NBSP = " "
ARROW_REG_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Icons"


# --- helpers --------------------------------------------------------------

def _noop(stage, frac=None):
    pass


def _is_folder(app: dict) -> bool:
    return app.get("type") == "folder"


def _stem(app: dict) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", app["display_name"]).strip("_") or "app"
    h = hashlib.md5(app["key"].encode("utf-8")).hexdigest()[:8]
    return f"{safe}_{h}"


def _run_ps(script: str, *flags, **kwargs) -> subprocess.CompletedProcess:
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", str(POWERSHELL_SCRIPTS_DIR / script)]
    for k, v in kwargs.items():
        cmd += [f"-{k}", str(v)]
    for f in flags:                       # switch params, e.g. "Clear"
        cmd.append(f if f.startswith("-") else f"-{f}")
    return subprocess.run(
        cmd, check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def _current_path(app: dict, state: dict) -> str:
    """Resolve the app's current on-disk path from state (a shortcut may be hidden)."""
    entry = state_mod.get_entry(state, app["key"])
    name = (entry or {}).get("hidden_name") or app["original_name"]
    return os.path.join(app["directory"], name)


@contextmanager
def _temporarily_unhidden(app: dict, state: dict):
    """For a name-hidden shortcut, rename it back to its real name for the duration
    of a COM/shell op, then restore the hidden name.

    COM (WScript.Shell) and SHGetFileInfo cannot resolve a .lnk whose filename is a
    bare U+00A0 sequence, so any IconLocation read/write or icon extraction must run
    against the original-named file.
    """
    entry = state_mod.get_entry(state, app["key"])
    hidden = (entry or {}).get("hidden_name")
    if not hidden or _is_folder(app):
        yield app["path"]
        return
    directory = app["directory"]
    hidden_path = os.path.join(directory, hidden)
    real_path = os.path.join(directory, app["original_name"])
    renamed = False
    if os.path.exists(hidden_path) and not os.path.exists(real_path):
        os.rename(hidden_path, real_path)
        renamed = True
    try:
        yield real_path
    finally:
        if renamed and os.path.exists(real_path):
            os.rename(real_path, hidden_path)


# --- icon generation ------------------------------------------------------

def _entry_stem(entry: dict) -> str:
    """Stable cache stem from a state entry (no live app dict needed)."""
    name = entry.get("original_name") or "app"
    safe = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_") or "app"
    key = state_mod.make_key(entry.get("directory", ""), entry.get("original_name", ""))
    h = hashlib.md5(key.encode("utf-8")).hexdigest()[:8]
    return f"{safe}_{h}"


def ensure_orig_thumb(entry: dict, rec: dict | None = None) -> str | None:
    """Path to a cached thumbnail of the app's ORIGINAL icon (its real logo),
    independent of any theming or name-hiding. Captured once, then reused.

    The card grid shows this so it stays a stable, recognizable app picker that
    never follows the themed/pixel result. extract_icon.ps1 follows a .lnk to its
    target and pulls the target's icon, so it recovers the real logo even after we
    overwrote the shortcut's IconLocation.
    """
    cur = entry.get("orig_thumb")
    if cur and Path(cur).exists():
        return cur

    scan_thumb = (rec or {}).get("Thumb") or ""
    out = CACHE_DIR / f"{_entry_stem(entry)}_orig.png"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    is_folder = entry.get("type") == "folder"
    themed = bool(entry.get("themed"))
    hidden = entry.get("hidden_name")

    # Folders have no target exe, and a clean (un-themed, un-hidden) shortcut already
    # shows its true icon in the live scan -> just cache that, no PowerShell needed.
    if is_folder or (not themed and not hidden):
        if scan_thumb and Path(scan_thumb).exists():
            try:
                shutil.copyfile(scan_thumb, out)
                entry["orig_thumb"] = str(out)
                return str(out)
            except OSError:
                return scan_thumb
        return scan_thumb or None

    # Themed and/or name-hidden shortcut: the scan icon is wrong (replaced) or
    # generic (blank-named .lnk). Recover the original target icon.
    # 1) If a concrete exe/dll original source was captured, read it directly —
    #    no need to disturb the on-disk shortcut.
    loc = entry.get("original_icon_location") or ""
    src_path = loc.rsplit(",", 1)[0].strip().strip('"') if loc else ""
    if src_path.lower().endswith((".exe", ".dll")) and os.path.exists(src_path):
        try:
            _run_ps("extract_icon.ps1", Source=src_path, OutPng=str(out), Size=256)
        except subprocess.CalledProcessError:
            pass
        if out.exists():
            entry["orig_thumb"] = str(out)
            return str(out)

    # 2) Otherwise resolve through the shortcut (extract_icon follows .lnk -> target).
    #    Temporarily un-hide a name-hidden shortcut so the shell can read it.
    directory = entry.get("directory") or ""
    original_name = entry.get("original_name") or ""
    real_path = os.path.join(directory, original_name)
    hidden_path = os.path.join(directory, hidden) if hidden else real_path
    renamed = False
    try:
        if hidden and os.path.exists(hidden_path) and not os.path.exists(real_path):
            os.rename(hidden_path, real_path)
            renamed = True
        if os.path.exists(real_path):
            _run_ps("extract_icon.ps1", Source=real_path, OutPng=str(out), Size=256)
    except (subprocess.CalledProcessError, OSError):
        pass
    finally:
        if renamed and os.path.exists(real_path):
            try:
                os.rename(real_path, hidden_path)
            except OSError:
                pass
    if out.exists():
        entry["orig_thumb"] = str(out)
        return str(out)
    return scan_thumb or None


def extract_current_icon(app: dict):
    """Pull the app's real (target) icon to a PNG for img2img input."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = CACHE_DIR / f"{_stem(app)}_src.png"
    state = state_mod.load_state()
    try:
        with _temporarily_unhidden(app, state) as src_path:
            _run_ps("extract_icon.ps1", Source=src_path, OutPng=str(out), Size=256)
        if out.exists():
            return out
    except subprocess.CalledProcessError:
        pass
    # fall back to the scan thumbnail if extraction failed
    return app.get("thumb") or None


def generate_styled(app: dict, theme_name: str, progress_cb=_noop, identity=None,
                    pixelate: bool | None = None):
    """Generate a restyled icon. Returns (preview_png, ico_path).

    pixelate: None -> follow the theme's pixel_art.enabled flag; True/False ->
    force the pixel-art post-step on/off regardless of the theme (GUI checkbox).
    """
    theme = load_theme(theme_name)
    stem = _stem(app)

    prompt = style_prompt(theme, app["display_name"], identity)
    use_edit = settings_mod.edit_enabled()
    png = None
    engine = "text"
    if use_edit:
        progress_cb("提取图标", None)
        src = extract_current_icon(app)
        if src:
            progress_cb("调用模型生成 (img2img)", None)
            try:
                png = generate_edit(src, theme, prompt, stem)
                engine = "edit"
            except Exception as exc:  # relay/edit hiccup -> fall back to text
                progress_cb(f"img2img 失败,回退文生图 ({exc})", None)
                png = None
    if png is None:
        progress_cb("调用模型生成 (文生图)", None)
        png = generate_text(theme, prompt, stem)
        engine = "text"

    theme_pixel = bool((theme.get("pixel_art") or {}).get("enabled"))
    do_pixel = theme_pixel if pixelate is None else pixelate
    progress_cb("像素化后处理" if do_pixel else "后处理", None)
    # Archive every generation under its own timestamped slot (non-destructive).
    slot = archive.new_slot(stem, theme_name)
    shutil.copyfile(png, slot["png"])
    ico = Path(slot["ico"])
    to_ico(slot["png"], ico, theme=theme, pixelate=pixelate,
           remove_bg=settings_mod.bg_removal_enabled())
    preview = ico.with_name(ico.stem + "_preview.png")
    if not preview.exists():
        preview = Path(slot["png"])  # non-pixel themes: styled PNG is the preview

    archive.add_entry(
        app["key"], slot["ts"], theme_name, engine,
        slot["png"], str(ico), str(preview), prompt,
    )
    progress_cb("完成", 1.0)
    return str(preview), str(ico)


def build_uploaded(app: dict, image_path: str, pixelate: bool, theme_name: str):
    """Turn a user-supplied image into an .ico. Returns (preview_png, ico_path)."""
    theme = load_theme(theme_name) if pixelate else None
    stem = _stem(app)
    ico = OUTPUT_DIR / f"{stem}_upload.ico"
    to_ico(image_path, ico, theme=theme, pixelate=pixelate,
           remove_bg=settings_mod.bg_removal_enabled())
    preview = ico.with_name(ico.stem + "_preview.png")
    if not preview.exists():
        preview = image_path
    return str(preview), str(ico)


# --- apply / hide / restore ----------------------------------------------

def apply_styled(app: dict, ico_path: str, theme_name: str | None):
    """Set the generated .ico on a shortcut or folder; record state for restore."""
    state = state_mod.load_state()
    entry = state_mod.ensure_entry(
        state, app["key"], app["directory"], app["original_name"],
        item_type=app.get("type", "shortcut"),
    )
    state_mod.capture_original_icon(entry, app.get("icon_location", ""))

    if _is_folder(app):
        _run_ps("folder_icon.ps1", FolderPath=app["path"], IcoPath=ico_path)
    else:
        # COM IconLocation can't be written against a U+00A0-named .lnk.
        with _temporarily_unhidden(app, state) as path:
            _run_ps("apply.ps1", ShortcutPath=path, IcoPath=ico_path)

    entry["themed"] = True
    entry["ico_path"] = ico_path
    entry["theme"] = theme_name
    # Remember a crisp thumbnail so the card shows exactly what we generated,
    # instead of re-extracting (and bicubic-muddying) it from the shell.
    ico_p = Path(ico_path)
    preview = ico_p.with_name(ico_p.stem + "_preview.png")
    is_pixel = preview.exists()  # the pixel post-step is the only writer of _preview.png
    entry["good_thumb"] = str(preview) if is_pixel else str(ico_p)
    entry["pixel"] = is_pixel    # drives nearest-neighbor card scaling, survives name-hiding
    state_mod.save_state(state)


def hide_name(app: dict):
    """Blank a shortcut's label via a U+00A0 rename. Shortcuts only — renaming a
    real folder/file is risky, so folders are skipped."""
    if _is_folder(app):
        return
    if app.get("name_hidden"):
        return  # already hidden (decided from the live scan, not stale state)

    state = state_mod.load_state()
    entry = state_mod.ensure_entry(
        state, app["key"], app["directory"], app["original_name"],
        item_type="shortcut",
    )

    # Preserve the current (correct) thumbnail; once renamed, the shell can't
    # resolve the blank-named .lnk and would only yield a generic icon.
    thumb = app.get("thumb")
    if thumb and os.path.exists(thumb):
        good = CACHE_DIR / f"{_stem(app)}_good.png"
        try:
            shutil.copyfile(thumb, good)
            entry["good_thumb"] = str(good)
        except OSError:
            pass

    directory = app["directory"]
    n = 1
    while True:
        candidate = (NBSP * n) + ".lnk"
        if not os.path.exists(os.path.join(directory, candidate)):
            break
        n += 1
    src = _current_path(app, state)
    dst = os.path.join(directory, candidate)
    os.rename(src, dst)
    entry["hidden_name"] = candidate
    state_mod.save_state(state)


def restore_name(app: dict, state: dict | None = None, save: bool = True):
    if _is_folder(app):
        return
    own = state is None
    if own:
        state = state_mod.load_state()
    entry = state_mod.get_entry(state, app["key"])
    if entry and entry.get("hidden_name"):
        src = os.path.join(app["directory"], entry["hidden_name"])
        dst = os.path.join(app["directory"], entry["original_name"])
        if os.path.exists(src):
            os.rename(src, dst)
        entry["hidden_name"] = None
        if save:
            state_mod.save_state(state)


def restore_app(app: dict):
    """Undo everything for one app: name + custom icon -> original."""
    state = state_mod.load_state()
    # 1) name first (shortcuts only), so we operate on the original-named path
    restore_name(app, state=state, save=False)
    entry = state_mod.get_entry(state, app["key"])
    if entry and entry.get("themed"):
        if _is_folder(app):
            _run_ps("folder_icon.ps1", "Clear", FolderPath=app["path"])
        else:
            path = os.path.join(app["directory"], entry["original_name"])
            original_loc = entry.get("original_icon_location") or ",0"
            _run_ps("set_icon.ps1", ShortcutPath=path, IconLocation=original_loc)
        entry["themed"] = False
        entry["ico_path"] = None
        entry["theme"] = None
    state_mod.save_state(state)


# --- global shortcut-arrow toggle ----------------------------------------

def set_arrows(hidden: bool, restart_explorer: bool = True):
    """Hide/show ALL shortcut arrows (Windows overlay #29 is global)."""
    if hidden:
        blank = ASSETS_DIR / "blank.ico"
        if not blank.exists():
            raise FileNotFoundError(f"blank icon missing: {blank}")
        key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, ARROW_REG_PATH)
        winreg.SetValueEx(key, "29", 0, winreg.REG_SZ, f"{blank},0")
        winreg.CloseKey(key)
    else:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, ARROW_REG_PATH, 0, winreg.KEY_SET_VALUE
            )
            winreg.DeleteValue(key, "29")
            winreg.CloseKey(key)
        except FileNotFoundError:
            pass

    state = state_mod.load_state()
    state_mod.set_arrows_hidden(state, hidden)
    state_mod.save_state(state)

    if restart_explorer:
        _restart_explorer()


def _restart_explorer():
    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"],
                   capture_output=True)
    time.sleep(1)
    subprocess.Popen(["explorer.exe"])
