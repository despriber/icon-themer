"""icon-themer — desktop GUI.

Live-scans desktop shortcuts and lets you (per app, or batch via multi-select):
  - change the icon to a configured theme (generate -> preview -> replace)
  - upload your own image as the icon
  - hide the name (per app) and the shortcut arrow (global)
  - one-click restore to original

Relaunches itself elevated once at startup so Public-Desktop renames and the
HKLM arrow-overlay registry write work without repeated UAC prompts.
"""
import ctypes
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))


# --- elevation ------------------------------------------------------------

def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_as_admin() -> None:
    params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, str(HERE), 1
    )


if not _is_admin():
    _relaunch_as_admin()
    sys.exit(0)


from PySide6.QtCore import QPoint, QRect, QSize, Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog,
    QLabel, QLayout, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSpinBox, QVBoxLayout, QWidget,
)

import config
import operations
import desktop
import settings as settings_mod
import state as state_mod
import archive
import vision


# --- flow layout (wraps cards to the available width) ---------------------

class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=8, spacing=10):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do(QRect(0, 0, width, 0), test=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, test=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do(self, rect, test):
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = eff.x(), eff.y(), 0
        sp = self.spacing()
        for it in self._items:
            w = it.sizeHint().width()
            h = it.sizeHint().height()
            if x + w > eff.right() + 1 and line_h > 0:
                x = eff.x()
                y = y + line_h + sp
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), it.sizeHint()))
            x = x + w + sp
            line_h = max(line_h, h)
        return y + line_h - rect.y() + m.bottom()


# --- workers --------------------------------------------------------------

class TaskWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception:
            self.failed.emit(traceback.format_exc())


class GenerateWorker(QThread):
    progress = Signal(str, str)     # key, stage
    item_done = Signal(dict)        # {app, preview, ico}
    finished_all = Signal(list)

    def __init__(self, apps, theme, identities, pixelate=None):
        super().__init__()
        self.apps = apps
        self.theme = theme
        self.identities = identities
        self.pixelate = pixelate

    def run(self):
        results = []
        for app in self.apps:
            key = app["key"]

            def cb(stage, frac=None, _k=key):
                self.progress.emit(_k, stage)

            try:
                identity = self.identities.get(app["display_name"])
                preview, ico = operations.generate_styled(
                    app, self.theme, cb, identity=identity, pixelate=self.pixelate
                )
                r = {"app": app, "preview": preview, "ico": ico}
                results.append(r)
                self.item_done.emit(r)
            except Exception as exc:
                self.progress.emit(key, f"失败: {exc}")
        self.finished_all.emit(results)


# --- widgets --------------------------------------------------------------

def _badge(text, color):
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"background:{color}; color:white; border-radius:6px; "
        "padding:1px 6px; font-size:10px;"
    )
    lbl.setAlignment(Qt.AlignCenter)
    return lbl


def thumb_pixmap(path, side, pixel, widget=None):
    """Load `path` and scale to `side` logical px for crisp display.

    Two things keep it sharp:
      - pixel art uses nearest-neighbor (FastTransformation) so the grid stays hard;
      - we render at the screen's devicePixelRatio and tag the pixmap with it, so on
        a HiDPI / >100%-scaled display Windows doesn't bilinear-upscale a small pixmap
        into a blur. Without this every thumbnail looks uniformly soft.
    """
    pm = QPixmap(path) if path else QPixmap()
    if pm.isNull():
        return None
    scr = (widget.screen() if widget is not None else None) or QApplication.primaryScreen()
    dpr = scr.devicePixelRatio() if scr is not None else 1.0
    target = max(1, round(side * dpr))
    mode = Qt.FastTransformation if pixel else Qt.SmoothTransformation
    scaled = pm.scaled(target, target, Qt.KeepAspectRatio, mode)
    scaled.setDevicePixelRatio(dpr)
    return scaled


class AppCard(QFrame):
    CARD_W = 150
    CARD_H = 162

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setFixedSize(self.CARD_W, self.CARD_H)
        self.setObjectName("card")
        self.setStyleSheet(
            "#card { border:1px solid #d0d0d0; border-radius:10px; background:#fafafa; }"
            "#card[checked=\"true\"] { border:2px solid #4a7dff; background:#eef3ff; }"
        )

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 8)
        v.setSpacing(4)

        top = QHBoxLayout()
        self.checkbox = QCheckBox()
        self.checkbox.toggled.connect(self._on_toggle)
        top.addWidget(self.checkbox, 0, Qt.AlignLeft)
        top.addStretch(1)
        v.addLayout(top)

        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignCenter)
        self.icon.setFixedHeight(72)
        scaled = thumb_pixmap(app.get("thumb"), 64, app.get("pixel"), self)
        if scaled is not None:
            self.icon.setPixmap(scaled)
        else:
            self.icon.setText("?")
        v.addWidget(self.icon)

        name = QLabel(app["display_name"])
        name.setAlignment(Qt.AlignCenter)
        name.setWordWrap(True)
        name.setFixedHeight(34)
        name.setStyleSheet("font-size:11px; color:#222; background:transparent;")
        v.addWidget(name)

        badges = QHBoxLayout()
        badges.setSpacing(4)
        badges.addStretch(1)
        if app.get("type") == "folder":
            badges.addWidget(_badge("文件夹", "#d59a2b"))
        if app.get("themed"):
            badges.addWidget(_badge(app.get("theme") or "主题", "#7a5cff"))
        if app.get("name_hidden"):
            badges.addWidget(_badge("名称隐藏", "#888"))
        badges.addStretch(1)
        v.addLayout(badges)

    def _on_toggle(self, checked):
        self.setProperty("checked", "true" if checked else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, ev):
        # click anywhere on the card toggles selection
        self.checkbox.setChecked(not self.checkbox.isChecked())
        super().mousePressEvent(ev)

    def is_checked(self):
        return self.checkbox.isChecked()


class GenerationDialog(QDialog):
    def __init__(self, total, parent=None):
        super().__init__(parent)
        self.setWindowTitle("生成中…")
        self.setModal(True)
        self.setFixedWidth(420)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        self.total = total
        self.count = 0

        v = QVBoxLayout(self)
        self.overall = QLabel(f"0 / {total}")
        self.overall.setStyleSheet("font-weight:bold;")
        v.addWidget(self.overall)
        self.app_lbl = QLabel("")
        v.addWidget(self.app_lbl)
        self.stage_lbl = QLabel("")
        self.stage_lbl.setStyleSheet("color:#555;")
        v.addWidget(self.stage_lbl)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)  # indeterminate
        v.addWidget(self.bar)

    def on_progress(self, key, stage):
        self.stage_lbl.setText(stage)

    def on_item(self, result):
        self.count += 1
        self.overall.setText(f"{self.count} / {self.total}")
        self.app_lbl.setText("最近完成: " + result["app"]["display_name"])


class PreviewDialog(QDialog):
    """Before -> after gallery; user picks which to apply."""

    def __init__(self, results, parent=None):
        super().__init__(parent)
        self.setWindowTitle("预览 — 选择要替换的图标")
        self.setModal(True)
        self.results = results
        self.checks = []

        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        grid = QVBoxLayout(inner)

        for r in results:
            row = QFrame()
            row.setStyleSheet("QFrame { border-bottom:1px solid #eee; }")
            h = QHBoxLayout(row)
            cb = QCheckBox()
            cb.setChecked(True)
            self.checks.append(cb)
            h.addWidget(cb)

            name = QLabel(r["app"]["display_name"])
            name.setFixedWidth(160)
            name.setWordWrap(True)
            h.addWidget(name)

            before = QLabel()
            bscaled = thumb_pixmap(
                r["app"].get("thumb"), 72, r["app"].get("pixel"), self
            )
            if bscaled is not None:
                before.setPixmap(bscaled)
            h.addWidget(before)

            h.addWidget(QLabel("→"))

            after = QLabel()
            ascaled = thumb_pixmap(
                r["preview"], 72, str(r["preview"]).endswith("_preview.png"), self
            )
            if ascaled is not None:
                after.setPixmap(ascaled)
            h.addWidget(after)
            h.addStretch(1)
            grid.addWidget(row)

        grid.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("替换所勾选")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        outer.addLayout(btns)

        self.resize(640, min(520, 140 + 96 * len(results)))

    def chosen(self):
        return [r for r, cb in zip(self.results, self.checks) if cb.isChecked()]


# --- settings dialog ------------------------------------------------------

class SettingsDialog(QDialog):
    """Edit image-generation + vision model config (URL / key / model)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置 — 模型与接口")
        self.setModal(True)
        self.resize(560, 0)
        s = settings_mod.load_settings()
        outer = QVBoxLayout(self)

        # image generation
        img_box = QGroupBox("图片生成 / 编辑")
        img_form = QFormLayout(img_box)
        self.img_url = QLineEdit(s["image"].get("base_url", ""))
        self.img_key = QLineEdit(s["image"].get("api_key", ""))
        self.img_key.setEchoMode(QLineEdit.Password)
        self.img_model = QLineEdit(s["image"].get("model", ""))
        self.img_model.setPlaceholderText("默认 gpt-image-2")
        self.edit_chk = QCheckBox("启用图片编辑接口(优先 img2img,不可用时回退文生图)")
        self.edit_chk.setChecked(bool(s["image"].get("edit_enabled", True)))
        self.bg_chk = QCheckBox("自动抠除背景(把生成图的纯色背景变透明;关闭则保留背景)")
        self.bg_chk.setChecked(bool(s["image"].get("bg_removal", True)))
        img_form.addRow("Base URL:", self.img_url)
        img_form.addRow("API Key:", self.img_key)
        img_form.addRow("模型:", self.img_model)
        img_form.addRow("", self.edit_chk)
        img_form.addRow("", self.bg_chk)
        outer.addWidget(img_box)

        # vision (theme-from-background)
        vis_box = QGroupBox("视觉模型(用于「从背景生成主题」,需图文输入)")
        vis_form = QFormLayout(vis_box)
        self.vis_url = QLineEdit(s["vision"].get("base_url", ""))
        self.vis_key = QLineEdit(s["vision"].get("api_key", ""))
        self.vis_key.setEchoMode(QLineEdit.Password)
        self.vis_model = QLineEdit(s["vision"].get("model", ""))
        self.vis_model.setPlaceholderText("gpt-5.5")
        vis_form.addRow("Base URL:", self.vis_url)
        vis_form.addRow("API Key:", self.vis_key)
        vis_form.addRow("模型:", self.vis_model)
        outer.addWidget(vis_box)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

    def _on_save(self):
        self.save()
        self.accept()

    def save(self):
        settings_mod.save_settings({
            "image": {
                "base_url": self.img_url.text().strip(),
                "api_key": self.img_key.text().strip(),
                "model": self.img_model.text().strip(),
                "edit_enabled": self.edit_chk.isChecked(),
                "bg_removal": self.bg_chk.isChecked(),
            },
            "vision": {
                "base_url": self.vis_url.text().strip(),
                "api_key": self.vis_key.text().strip(),
                "model": self.vis_model.text().strip(),
            },
        })


# --- history dialog (per-app archived generations) ------------------------

class HistoryDialog(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.applied_ico = None
        self.setWindowTitle(f"历史图标 — {app['display_name']}")
        self.setModal(True)
        self.resize(640, 480)
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("该应用历次生成的图标(新→旧)。点「应用」替换到桌面。"))

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        outer.addWidget(self.scroll, 1)

        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        outer.addLayout(row)

        self._reload()

    def _reload(self):
        entries = archive.list_entries(self.app["key"])
        host = QWidget()
        grid = QGridLayout(host)
        grid.setSpacing(10)
        if not entries:
            grid.addWidget(QLabel("暂无历史。先在主界面「生成所选」生成图标。"), 0, 0)
        cols = 4
        for i, e in enumerate(entries):
            card = QFrame()
            card.setStyleSheet("QFrame { border:1px solid #d0d0d0; border-radius:8px; }")
            v = QVBoxLayout(card)
            thumb = QLabel()
            thumb.setAlignment(Qt.AlignCenter)
            ppath = e.get("preview") or e.get("png") or ""
            scaled = thumb_pixmap(ppath, 96, str(ppath).endswith("_preview.png"), self)
            if scaled is not None:
                thumb.setPixmap(scaled)
            else:
                thumb.setText("?")
            v.addWidget(thumb)
            ts = e.get("ts", "")
            nice = ts.replace("_", " ") if ts else ""
            meta = QLabel(f"{e.get('theme','')} · {e.get('engine','')}\n{nice}")
            meta.setAlignment(Qt.AlignCenter)
            meta.setStyleSheet("font-size:10px; color:#333;")
            v.addWidget(meta)
            brow = QHBoxLayout()
            apply_b = QPushButton("应用")
            apply_b.clicked.connect(lambda _=False, ent=e: self._apply(ent))
            del_b = QPushButton("删除")
            del_b.clicked.connect(lambda _=False, ent=e: self._delete(ent))
            brow.addWidget(apply_b)
            brow.addWidget(del_b)
            v.addLayout(brow)
            grid.addWidget(card, i // cols, i % cols)
        self.scroll.setWidget(host)

    def _apply(self, entry):
        try:
            operations.apply_styled(self.app, entry["ico"], entry.get("theme"))
            self.applied_ico = entry["ico"]
        except Exception:
            QMessageBox.critical(self, "出错", traceback.format_exc())
            return
        QMessageBox.information(self, "已应用", "已替换为该历史图标。")
        self.accept()

    def _delete(self, entry):
        archive.delete_entry(self.app["key"], entry["ts"])
        self._reload()


# --- theme editor + manager ----------------------------------------------

class ThemeEditorDialog(QDialog):
    """Create or edit one theme spec (form over the theme JSON)."""

    def __init__(self, spec=None, name_locked=False, parent=None):
        super().__init__(parent)
        spec = spec or {}
        self.setWindowTitle("主题编辑")
        self.setModal(True)
        self.resize(640, 560)
        outer = QVBoxLayout(self)
        form = QFormLayout()

        self.name = QLineEdit(spec.get("name", ""))
        self.name.setPlaceholderText("英文标识(文件名),如 synthwave")
        if name_locked:
            self.name.setReadOnly(True)
        self.display = QLineEdit(spec.get("display_name", ""))
        self.size = QLineEdit(spec.get("size", "1024x1024"))
        form.addRow("name:", self.name)
        form.addRow("显示名:", self.display)
        form.addRow("尺寸:", self.size)
        outer.addLayout(form)

        pa = spec.get("pixel_art") or {}
        pbox = QGroupBox("像素化后处理")
        pform = QFormLayout(pbox)
        self.px_enabled = QCheckBox("启用像素网格")
        self.px_enabled.setChecked(bool(pa.get("enabled", False)))
        self.px_size = QSpinBox()
        self.px_size.setRange(8, 256)
        self.px_size.setValue(int(pa.get("source_size", 32) or 32))
        self.px_colors = QSpinBox()
        self.px_colors.setRange(0, 256)
        self.px_colors.setValue(int(pa.get("colors", 32) or 32))
        pform.addRow("", self.px_enabled)
        pform.addRow("网格(source_size):", self.px_size)
        pform.addRow("颜色数(0=不限):", self.px_colors)
        outer.addWidget(pbox)

        outer.addWidget(QLabel("base_prompt(画风描述,英文效果最好):"))
        self.prompt = QPlainTextEdit(spec.get("base_prompt", ""))
        outer.addWidget(self.prompt, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)
        self.saved_name = None

    def _on_save(self):
        if not self.name.text().strip():
            QMessageBox.information(self, "提示", "请填写 name(英文标识)。")
            return
        if not self.prompt.toPlainText().strip():
            QMessageBox.information(self, "提示", "base_prompt 不能为空。")
            return
        spec = {
            "name": self.name.text().strip(),
            "display_name": self.display.text().strip() or self.name.text().strip(),
            "size": self.size.text().strip() or "1024x1024",
            "base_prompt": self.prompt.toPlainText().strip(),
            "pixel_art": {
                "enabled": self.px_enabled.isChecked(),
                "source_size": self.px_size.value(),
                "colors": self.px_colors.value(),
            },
        }
        try:
            self.saved_name = config.save_theme(spec)
        except Exception:
            QMessageBox.critical(self, "出错", traceback.format_exc())
            return
        self.accept()


class ThemeManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("主题管理")
        self.setModal(True)
        self.resize(420, 420)
        self.changed = False
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel("主题库:"))
        self.list = QListWidget()
        outer.addWidget(self.list, 1)

        row = QHBoxLayout()
        for label, slot in [
            ("新建", self.on_new),
            ("编辑", self.on_edit),
            ("删除", self.on_delete),
            ("从背景生成", self.on_from_bg),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        outer.addLayout(row)

        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        crow = QHBoxLayout()
        crow.addStretch(1)
        crow.addWidget(close)
        outer.addLayout(crow)
        self._reload()

    def _reload(self):
        self.list.clear()
        for t in config.list_themes():
            it = QListWidgetItem(f"{t['display_name']}  ({t['name']})")
            it.setData(Qt.UserRole, t["name"])
            self.list.addItem(it)

    def _selected_name(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def on_new(self):
        dlg = ThemeEditorDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.changed = True
            self._reload()

    def on_edit(self):
        name = self._selected_name()
        if not name:
            QMessageBox.information(self, "提示", "请先选择一个主题。")
            return
        spec = config.load_theme(name)
        dlg = ThemeEditorDialog(spec=spec, name_locked=True, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.changed = True
            self._reload()

    def on_delete(self):
        name = self._selected_name()
        if not name:
            QMessageBox.information(self, "提示", "请先选择一个主题。")
            return
        if QMessageBox.question(
            self, "删除主题", f"确定删除主题「{name}」?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        config.delete_theme(name)
        self.changed = True
        self._reload()

    def on_from_bg(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择桌面背景图", "", "图片 (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if not path:
            return
        self.setEnabled(False)
        self._bg_worker = TaskWorker(
            lambda: vision.describe_theme_from_background(path)
        )
        self._bg_worker.done.connect(self._on_bg_draft)
        self._bg_worker.failed.connect(self._on_bg_failed)
        self._bg_worker.start()

    def _on_bg_draft(self, draft):
        self.setEnabled(True)
        dlg = ThemeEditorDialog(spec=draft, name_locked=False, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.changed = True
            self._reload()

    def _on_bg_failed(self, tb):
        self.setEnabled(True)
        QMessageBox.critical(self, "从背景生成失败", tb)


# --- main window ----------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("icon-themer — 桌面图标主题工具")
        self.resize(980, 720)
        self.apps = []
        self.cards = []
        self._worker = None
        self._gen_worker = None
        self.identities = {
            a["display_name"]: a.get("identity") for a in config.load_apps()
        }

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # top bar
        top = QHBoxLayout()
        top.addWidget(QLabel("主题:"))
        self.theme_combo = QComboBox()
        top.addWidget(self.theme_combo)
        self.theme_mgr_btn = QPushButton("主题…")
        self.theme_mgr_btn.clicked.connect(self.on_themes)
        top.addWidget(self.theme_mgr_btn)
        self.pixel_cb = QCheckBox("像素化")
        self.pixel_cb.setToolTip(
            "勾选:把模型输出降采样成真正的像素网格(限色 + 硬边)。\n"
            "取消:保留模型原始高清输出(画风仍在,但更柔和、非硬像素)。\n"
            "切换主题时默认跟随该主题的设定,可手动覆盖。"
        )
        top.addWidget(self.pixel_cb)
        self.theme_combo.currentIndexChanged.connect(self._sync_pixel_default)
        top.addStretch(1)
        self.settings_btn = QPushButton("设置")
        self.settings_btn.clicked.connect(self.on_settings)
        top.addWidget(self.settings_btn)
        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        top.addWidget(self.refresh_btn)
        self.arrow_btn = QPushButton("隐藏所有箭头")
        self.arrow_btn.clicked.connect(self.on_toggle_arrows)
        top.addWidget(self.arrow_btn)
        self.restore_all_btn = QPushButton("全部恢复")
        self.restore_all_btn.clicked.connect(self.on_restore_all)
        top.addWidget(self.restore_all_btn)
        root.addLayout(top)

        # cards scroll area
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.grid_host = QWidget()
        self.flow = FlowLayout(self.grid_host)
        self.scroll.setWidget(self.grid_host)
        root.addWidget(self.scroll, 1)

        # selection + batch action bar
        bar = QHBoxLayout()
        self.all_cb = QCheckBox("全选")
        self.all_cb.toggled.connect(self.on_toggle_all)
        bar.addWidget(self.all_cb)
        bar.addStretch(1)
        for label, slot in [
            ("生成所选", self.on_generate),
            ("上传图标…", self.on_upload),
            ("查看历史", self.on_history),
            ("隐藏名称", self.on_hide_names),
            ("显示名称", self.on_show_names),
            ("恢复所选", self.on_restore_selected),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            bar.addWidget(b)
            setattr(self, f"_btn_{label}", b)
        root.addLayout(bar)

        self.statusBar().showMessage("启动中…")
        self.reload_themes()
        self._sync_pixel_default()
        self._sync_arrow_button()
        self.refresh()

    # -- helpers
    def theme_name(self):
        return self.theme_combo.currentData()

    def _sync_pixel_default(self):
        """Default the 像素化 checkbox to the selected theme's pixel_art.enabled."""
        name = self.theme_name()
        enabled = False
        if name:
            try:
                enabled = bool((config.load_theme(name).get("pixel_art") or {}).get("enabled"))
            except (ValueError, OSError, KeyError):
                enabled = False
        self.pixel_cb.setChecked(enabled)

    def reload_themes(self):
        """Repopulate the theme dropdown, keeping the current selection if possible."""
        current = self.theme_combo.currentData()
        self.theme_combo.blockSignals(True)
        self.theme_combo.clear()
        for t in config.list_themes():
            self.theme_combo.addItem(t["display_name"], t["name"])
        if current is not None:
            i = self.theme_combo.findData(current)
            if i >= 0:
                self.theme_combo.setCurrentIndex(i)
        self.theme_combo.blockSignals(False)

    def checked_apps(self):
        return [c.app for c in self.cards if c.is_checked()]

    def _set_busy(self, busy, msg=None):
        self.centralWidget().setEnabled(not busy)
        if msg:
            self.statusBar().showMessage(msg)

    def _sync_arrow_button(self):
        hidden = state_mod.arrows_hidden(state_mod.load_state())
        self.arrow_btn.setText("显示所有箭头" if hidden else "隐藏所有箭头")

    # -- scan / refresh
    def refresh(self):
        self._set_busy(True, "扫描桌面快捷方式…")
        self._worker = TaskWorker(desktop.scan_apps)
        self._worker.done.connect(self._on_scanned)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_scanned(self, apps):
        self.apps = apps
        # clear grid
        while self.flow.count():
            item = self.flow.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.cards = []
        for app in apps:
            card = AppCard(app)
            self.cards.append(card)
            self.flow.addWidget(card)
        self.all_cb.setChecked(False)
        self._set_busy(False)
        self.statusBar().showMessage(f"共 {len(apps)} 个应用")

    def _on_failed(self, tb):
        self._set_busy(False)
        QMessageBox.critical(self, "出错", tb)

    def on_toggle_all(self, checked):
        for c in self.cards:
            c.checkbox.setChecked(checked)

    # -- generation
    def on_generate(self):
        apps = self.checked_apps()
        if not apps:
            QMessageBox.information(self, "提示", "请先勾选至少一个应用。")
            return
        self.gen_dialog = GenerationDialog(len(apps), self)
        self._gen_worker = GenerateWorker(
            apps, self.theme_name(), self.identities, self.pixel_cb.isChecked()
        )
        self._gen_worker.progress.connect(self.gen_dialog.on_progress)
        self._gen_worker.item_done.connect(self.gen_dialog.on_item)
        self._gen_worker.finished_all.connect(self._on_generated)
        self._gen_worker.start()
        self.gen_dialog.show()

    def _on_generated(self, results):
        self.gen_dialog.close()
        if not results:
            QMessageBox.warning(self, "生成失败", "没有成功生成的图标。")
            return
        dlg = PreviewDialog(results, self)
        if dlg.exec() == QDialog.Accepted:
            chosen = dlg.chosen()
            if chosen:
                theme = self.theme_name()

                def do():
                    for r in chosen:
                        operations.apply_styled(r["app"], r["ico"], theme)
                self._run_task(do, f"已替换 {len(chosen)} 个图标")

    # -- upload
    def on_upload(self):
        apps = self.checked_apps()
        if len(apps) != 1:
            QMessageBox.information(self, "提示", "上传自定义图标请只勾选 1 个应用。")
            return
        app = apps[0]
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", "图片 (*.png *.ico *.jpg *.jpeg *.bmp *.webp)"
        )
        if not path:
            return
        ans = QMessageBox.question(
            self, "处理方式", "按当前主题像素化处理吗?\n(否 = 原样使用)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        pixelate = ans == QMessageBox.Yes
        try:
            preview, ico = operations.build_uploaded(
                app, path, pixelate, self.theme_name()
            )
        except Exception:
            QMessageBox.critical(self, "出错", traceback.format_exc())
            return
        dlg = PreviewDialog([{"app": app, "preview": preview, "ico": ico}], self)
        if dlg.exec() == QDialog.Accepted and dlg.chosen():
            theme = self.theme_name() if pixelate else None

            def do():
                operations.apply_styled(app, ico, theme)
            self._run_task(do, "已替换上传的图标")

    # -- settings / themes / history
    def on_settings(self):
        SettingsDialog(self).exec()

    def on_themes(self):
        dlg = ThemeManagerDialog(self)
        dlg.exec()
        if dlg.changed:
            self.reload_themes()

    def on_history(self):
        apps = self.checked_apps()
        if len(apps) != 1:
            QMessageBox.information(self, "提示", "查看历史请只勾选 1 个应用。")
            return
        dlg = HistoryDialog(apps[0], self)
        dlg.exec()
        if dlg.applied_ico:
            self.statusBar().showMessage("已应用历史图标")
            self.refresh()

    # -- hide / show / restore
    def on_hide_names(self):
        apps = self.checked_apps()
        if not apps:
            QMessageBox.information(self, "提示", "请先勾选应用。")
            return
        shortcuts = [a for a in apps if a.get("type") != "folder"]
        if not shortcuts:
            QMessageBox.information(self, "提示", "隐藏名称仅支持快捷方式,文件夹会被跳过。")
            return

        def do():
            for app in shortcuts:
                operations.hide_name(app)
        skipped = len(apps) - len(shortcuts)
        msg = "已隐藏名称" + (f"(跳过 {skipped} 个文件夹)" if skipped else "")
        self._run_task(do, msg)

    def on_show_names(self):
        apps = self.checked_apps()
        if not apps:
            QMessageBox.information(self, "提示", "请先勾选应用。")
            return
        shortcuts = [a for a in apps if a.get("type") != "folder"]

        def do():
            for app in shortcuts:
                operations.restore_name(app)
        self._run_task(do, "已显示名称")

    def on_restore_selected(self):
        apps = self.checked_apps()
        if not apps:
            QMessageBox.information(self, "提示", "请先勾选应用。")
            return

        def do():
            for app in apps:
                operations.restore_app(app)
        self._run_task(do, "已恢复所选应用")

    # -- global arrows
    def on_toggle_arrows(self):
        hidden = state_mod.arrows_hidden(state_mod.load_state())
        target = not hidden

        def do():
            operations.set_arrows(target)
        self._run_task(
            do,
            "已隐藏所有箭头 (资源管理器已重启)" if target
            else "已显示所有箭头 (资源管理器已重启)",
            after=self._sync_arrow_button,
        )

    def on_restore_all(self):
        ans = QMessageBox.question(
            self, "全部恢复",
            "将所有应用的名称、图标恢复为原始,并显示所有箭头。继续?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        apps = list(self.apps)

        def do():
            for app in apps:
                operations.restore_app(app)
            operations.set_arrows(False)
        self._run_task(do, "已全部恢复", after=self._sync_arrow_button)

    # -- task runner
    def _run_task(self, fn, success_msg, after=None):
        self._set_busy(True, "处理中…")
        self._worker = TaskWorker(fn)

        def on_done(_):
            if after:
                after()
            self.statusBar().showMessage(success_msg)
            self.refresh()  # re-scan to reflect changes

        self._worker.done.connect(on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
