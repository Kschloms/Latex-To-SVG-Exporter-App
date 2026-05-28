"""
latex_snippets.py — LaTeX snippet composer for Affinity Designer figures
Compile LaTeX expressions to SVG/PNG, preview inline, copy to clipboard.

Requirements:
    pip install PyQt6
    System: latex (texlive), dvisvgm, ghostscript (for PNG rasterisation)

Usage:
    python latex_snippets.py
"""

import sys
import os
import json
import shutil
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTextEdit, QLabel, QPushButton, QComboBox, QSpinBox,
    QDoubleSpinBox, QTabWidget, QListWidget, QListWidgetItem, QScrollArea,
    QFrame, QGroupBox, QCheckBox, QLineEdit, QMessageBox, QSizePolicy,
    QStatusBar, QToolBar, QSlider, QInputDialog, QDialog, QDialogButtonBox,
    QFormLayout, QMenu, QFileDialog,
)
from PyQt6.QtCore import (
    Qt, QProcess, QTimer, QSettings, QSize, QThread, pyqtSignal, QObject,
)
from PyQt6.QtGui import (
    QFont, QPixmap, QImage, QKeySequence, QShortcut, QColor, QPalette,
    QAction, QIcon, QSyntaxHighlighter, QTextCharFormat, QCursor,
)
from PyQt6.QtSvgWidgets import QSvgWidget
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtCore import QByteArray

# ── Paths ────────────────────────────────────────────────────────────────────
APP_DIR = Path.home() / ".latex_snippets"
APP_DIR.mkdir(exist_ok=True)
SNIPPETS_FILE = APP_DIR / "snippets.json"
SETTINGS_FILE = APP_DIR / "settings.json"

# ── Default settings ─────────────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "font_size_pt": 11,
    "compiler": "latex",          # latex | pdflatex | lualatex
    "png_dpi": 300,
    "math_mode": "display",       # inline | display
    "svg_border_pt": 2,
    "auto_save": True,
    "packages": {
        "amsmath": True,
        "amssymb": True,
        "physics": True,
        "braket": False,
        "xcolor": False,
    },
    "custom_preamble": "",
}

# ── Quick-insert snippets ─────────────────────────────────────────────────────
QUICK_INSERTS = [
    (r"\ket{}",         r"\ket{}"),
    (r"\bra{}",         r"\bra{}"),
    (r"\braket{}",      r"\braket{}"),
    (r"\otimes",        r"\otimes"),
    (r"\Omega_{\beta}", r"\Omega_{\beta}"),
    (r"\hat{H}",        r"\hat{H}"),
    (r"\frac{}{}",      r"\frac{}{}"),
    (r"\dagger",        r"\dagger"),
    (r"\sigma_z",       r"\sigma_z"),
    (r"\mathrm{}",      r"\mathrm{}"),
]


# ─────────────────────────────────────────────────────────────────────────────
#  Syntax highlighter for LaTeX input
# ─────────────────────────────────────────────────────────────────────────────
class LaTeXHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self._rules = []

        cmd = QTextCharFormat()
        cmd.setForeground(QColor("#4A90D9"))
        cmd.setFontWeight(700)
        import re
        self._rules.append((re.compile(r'\\[a-zA-Z]+'), cmd))

        brace = QTextCharFormat()
        brace.setForeground(QColor("#E06C75"))
        self._rules.append((re.compile(r'[{}]'), brace))

        comment = QTextCharFormat()
        comment.setForeground(QColor("#7C8591"))
        comment.setFontItalic(True)
        self._rules.append((re.compile(r'%.*'), comment))

    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ─────────────────────────────────────────────────────────────────────────────
#  Compiler worker (runs in a QThread)
# ─────────────────────────────────────────────────────────────────────────────
class CompileWorker(QObject):
    finished = pyqtSignal(str, str)   # svg_path_or_empty, error_msg

    def __init__(self, latex_src: str, settings: dict):
        super().__init__()
        self.latex_src = latex_src
        self.settings = settings

    def run(self):
        s = self.settings
        tmpdir = tempfile.mkdtemp(prefix="latexsnip_")
        try:
            tex_path = Path(tmpdir) / "snippet.tex"
            tex_path.write_text(self.latex_src, encoding="utf-8")

            compiler = s.get("compiler", "latex")
            result = subprocess.run(
                [compiler, "-interaction=nonstopmode", "-halt-on-error", "snippet.tex"],
                cwd=tmpdir, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                log = result.stdout + result.stderr
                # extract the useful TeX error line
                err = next((l for l in log.splitlines() if l.startswith("!")), log[-400:])
                self.finished.emit("", err)
                return

            # DVI → SVG
            dvi_path = Path(tmpdir) / "snippet.dvi"
            if compiler == "pdflatex":
                # pdf2svg path
                pdf_path = Path(tmpdir) / "snippet.pdf"
                svg_path = Path(tmpdir) / "snippet.svg"
                r2 = subprocess.run(
                    ["pdf2svg", str(pdf_path), str(svg_path)],
                    cwd=tmpdir, capture_output=True, text=True, timeout=15,
                )
            else:
                svg_path = Path(tmpdir) / "snippet.svg"
                # --bbox=N pads by N big-points around tight content.
                # 1pt = 1.333bp; standalone border already handles most padding,
                # so just pass a small integer here.
                border_bp = max(1, round(s.get("svg_border_pt", 2) * 1.333))
                r2 = subprocess.run(
                    ["dvisvgm", "--no-fonts", "--exact",
                     f"--bbox={border_bp}",
                     "-o", str(svg_path), str(dvi_path)],
                    cwd=tmpdir, capture_output=True, text=True, timeout=15,
                )

            if r2.returncode != 0 or not svg_path.exists():
                self.finished.emit("", r2.stderr or "dvisvgm failed")
                return

            self.finished.emit(str(svg_path), "")
        except FileNotFoundError as e:
            self.finished.emit("", f"Tool not found: {e.filename}\nIs TeX Live installed?")
        except subprocess.TimeoutExpired:
            self.finished.emit("", "Compile timed out (>30 s)")
        except Exception as e:
            self.finished.emit("", str(e))
        # NOTE: tmpdir intentionally not deleted — reused for PNG export.
        # Caller should delete after copy.


# ─────────────────────────────────────────────────────────────────────────────
#  Helper: build the full .tex source
# ─────────────────────────────────────────────────────────────────────────────
def build_tex(expr: str, settings: dict) -> str:
    pkgs = settings.get("packages", {})
    pkg_lines = "\n".join(
        f"\\usepackage{{{name}}}" for name, enabled in pkgs.items() if enabled
    )
    custom = settings.get("custom_preamble", "").strip()
    preamble_extra = (f"\n{custom}" if custom else "")

    border = settings.get("svg_border_pt", 2)
    font_size = settings.get("font_size_pt", 11)

    # Map font size to LaTeX class option
    size_map = {8:"8pt",9:"9pt",10:"10pt",11:"11pt",12:"12pt",14:"14pt",17:"17pt",20:"20pt",25:"25pt"}
    closest = min(size_map.keys(), key=lambda k: abs(k - font_size))
    size_opt = size_map[closest]

    if settings.get("math_mode", "display") == "display":
        math_wrap = f"\\[\n{expr}\n\\]"
    else:
        math_wrap = f"${expr}$"

    return f"""%% Auto-generated by latex_snippets
\\documentclass[preview,border={border}pt,{size_opt}]{{standalone}}
{pkg_lines}{preamble_extra}
\\begin{{document}}
{math_wrap}
\\end{{document}}
"""


# ─────────────────────────────────────────────────────────────────────────────
#  Snippets store
# ─────────────────────────────────────────────────────────────────────────────
class SnippetStore:
    def __init__(self):
        self._items: list[dict] = []
        self.load()

    def load(self):
        if SNIPPETS_FILE.exists():
            try:
                self._items = json.loads(SNIPPETS_FILE.read_text())
            except Exception:
                self._items = []

    def save(self):
        SNIPPETS_FILE.write_text(json.dumps(self._items, indent=2))

    def add(self, code: str, label: str = ""):
        # avoid exact duplicates
        if any(s["code"] == code for s in self._items):
            return
        self._items.insert(0, {
            "code": code,
            "label": label or code[:40],
            "added": datetime.now().isoformat(timespec="seconds"),
        })
        self.save()

    def remove(self, index: int):
        self._items.pop(index)
        self.save()

    def rename(self, index: int, label: str):
        self._items[index]["label"] = label
        self.save()

    def all(self) -> list[dict]:
        return self._items


# ─────────────────────────────────────────────────────────────────────────────
#  Settings dialog
# ─────────────────────────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(420)
        self._s = dict(settings)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Compiler
        self.compiler_box = QComboBox()
        self.compiler_box.addItems(["latex", "pdflatex", "lualatex"])
        self.compiler_box.setCurrentText(self._s.get("compiler", "latex"))
        form.addRow("Compiler", self.compiler_box)

        # Font size
        self.font_size = QSpinBox()
        self.font_size.setRange(6, 25)
        self.font_size.setValue(self._s.get("font_size_pt", 11))
        self.font_size.setSuffix(" pt")
        form.addRow("Font size", self.font_size)

        # Math mode
        self.math_mode = QComboBox()
        self.math_mode.addItems(["display", "inline"])
        self.math_mode.setCurrentText(self._s.get("math_mode", "display"))
        form.addRow("Math mode", self.math_mode)

        # PNG DPI
        self.dpi = QSpinBox()
        self.dpi.setRange(72, 600)
        self.dpi.setValue(self._s.get("png_dpi", 300))
        self.dpi.setSuffix(" dpi")
        form.addRow("PNG DPI", self.dpi)

        # SVG border
        self.border = QSpinBox()
        self.border.setRange(0, 20)
        self.border.setValue(self._s.get("svg_border_pt", 2))
        self.border.setSuffix(" pt")
        form.addRow("SVG border", self.border)

        # Auto-save
        self.auto_save = QCheckBox("Save to history on compile")
        self.auto_save.setChecked(self._s.get("auto_save", True))
        form.addRow("Auto-save", self.auto_save)

        layout.addLayout(form)

        # Packages
        pkg_box = QGroupBox("Packages")
        pkg_layout = QVBoxLayout(pkg_box)
        self._pkg_checks = {}
        pkgs = self._s.get("packages", DEFAULT_SETTINGS["packages"])
        for name, enabled in pkgs.items():
            cb = QCheckBox(f"\\usepackage{{{name}}}")
            cb.setChecked(enabled)
            cb.setFont(QFont("monospace", 10))
            self._pkg_checks[name] = cb
            pkg_layout.addWidget(cb)
        layout.addWidget(pkg_box)

        # Custom preamble
        preamble_box = QGroupBox("Custom preamble")
        preamble_layout = QVBoxLayout(preamble_box)
        self.custom_preamble = QTextEdit()
        self.custom_preamble.setFont(QFont("monospace", 10))
        self.custom_preamble.setPlainText(self._s.get("custom_preamble", ""))
        self.custom_preamble.setFixedHeight(80)
        self.custom_preamble.setPlaceholderText(r"% e.g. \newcommand{\dd}[1]{\mathrm{d}#1}")
        preamble_layout.addWidget(self.custom_preamble)
        layout.addWidget(preamble_box)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_settings(self) -> dict:
        self._s["compiler"] = self.compiler_box.currentText()
        self._s["font_size_pt"] = self.font_size.value()
        self._s["math_mode"] = self.math_mode.currentText()
        self._s["png_dpi"] = self.dpi.value()
        self._s["svg_border_pt"] = self.border.value()
        self._s["auto_save"] = self.auto_save.isChecked()
        self._s["packages"] = {name: cb.isChecked() for name, cb in self._pkg_checks.items()}
        self._s["custom_preamble"] = self.custom_preamble.toPlainText()
        return self._s


# ─────────────────────────────────────────────────────────────────────────────
#  Main window
# ─────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LaTeX Snippets")
        self.setMinimumSize(860, 580)

        # Load persisted settings
        if SETTINGS_FILE.exists():
            try:
                self._settings = json.loads(SETTINGS_FILE.read_text())
                # merge any missing keys from defaults
                for k, v in DEFAULT_SETTINGS.items():
                    if k not in self._settings:
                        self._settings[k] = v
                    if isinstance(v, dict):
                        for kk, vv in v.items():
                            self._settings[k].setdefault(kk, vv)
            except Exception:
                self._settings = dict(DEFAULT_SETTINGS)
        else:
            self._settings = dict(DEFAULT_SETTINGS)

        self._store = SnippetStore()
        self._current_svg_path: str = ""
        self._compile_thread: QThread | None = None

        self._build_ui()
        self._setup_shortcuts()

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        # Toolbar
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(tb)

        compile_act = QAction("▶  Compile  (Ctrl+Enter)", self)
        compile_act.triggered.connect(self._compile)
        tb.addAction(compile_act)

        tb.addSeparator()

        copy_svg_act = QAction("Copy SVG", self)
        copy_svg_act.triggered.connect(self._copy_svg)
        tb.addAction(copy_svg_act)

        copy_png_act = QAction("Copy PNG", self)
        copy_png_act.triggered.connect(self._copy_png)
        tb.addAction(copy_png_act)

        save_act = QAction("Save snippet", self)
        save_act.triggered.connect(self._save_snippet)
        tb.addAction(save_act)

        tb.addSeparator()

        export_act = QAction("Export file…", self)
        export_act.triggered.connect(self._export_file)
        tb.addAction(export_act)

        settings_act = QAction("⚙ Settings", self)
        settings_act.triggered.connect(self._open_settings)
        tb.addAction(settings_act)

        # Central splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # ── Left panel ─────────────────────────────────────────────────────
        left = QWidget()
        left.setMinimumWidth(320)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(6)

        tabs = QTabWidget()
        left_layout.addWidget(tabs)

        # Input tab
        input_widget = QWidget()
        input_layout = QVBoxLayout(input_widget)
        input_layout.setContentsMargins(4, 4, 4, 4)

        self._editor = QTextEdit()
        self._editor.setFont(QFont("monospace", 12))
        self._editor.setPlaceholderText(r"Enter LaTeX math, e.g.  \ket{0_2} \otimes \ket{n}")
        self._editor.setAcceptRichText(False)
        self._highlighter = LaTeXHighlighter(self._editor.document())
        input_layout.addWidget(self._editor)

        # Quick inserts
        qi_label = QLabel("Quick insert:")
        qi_label.setStyleSheet("color: gray; font-size: 11px;")
        input_layout.addWidget(qi_label)

        qi_grid = QWidget()
        qi_flow = QHBoxLayout(qi_grid)
        qi_flow.setContentsMargins(0, 0, 0, 0)
        qi_flow.setSpacing(4)
        for label, code in QUICK_INSERTS:
            btn = QPushButton(label)
            btn.setFont(QFont("monospace", 9))
            btn.setMaximumHeight(24)
            btn.clicked.connect(lambda _, c=code: self._insert(c))
            qi_flow.addWidget(btn)
        qi_flow.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(qi_grid)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(36)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        input_layout.addWidget(scroll)

        tabs.addTab(input_widget, "Input")

        # History tab
        history_widget = QWidget()
        history_layout = QVBoxLayout(history_widget)
        history_layout.setContentsMargins(4, 4, 4, 4)

        self._history_list = QListWidget()
        self._history_list.setFont(QFont("monospace", 10))
        self._history_list.itemDoubleClicked.connect(self._load_from_history)
        self._history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._history_list.customContextMenuRequested.connect(self._history_context_menu)
        history_layout.addWidget(self._history_list)

        hist_btns = QHBoxLayout()
        load_btn = QPushButton("Load selected")
        load_btn.clicked.connect(lambda: self._load_from_history(self._history_list.currentItem()))
        delete_btn = QPushButton("Delete selected")
        delete_btn.clicked.connect(self._delete_snippet)
        hist_btns.addWidget(load_btn)
        hist_btns.addWidget(delete_btn)
        history_layout.addLayout(hist_btns)

        tabs.addTab(history_widget, "History")
        self._tabs = tabs

        self._refresh_history()

        # ── Right panel ────────────────────────────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 6, 6, 6)
        right_layout.setSpacing(6)

        preview_label = QLabel("Preview")
        preview_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        right_layout.addWidget(preview_label)

        # SVG preview area
        self._preview_scroll = QScrollArea()
        self._preview_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_scroll.setFrameShape(QFrame.Shape.StyledPanel)
        self._preview_scroll.setStyleSheet("background: white;")

        self._preview_label = QLabel("Press Ctrl+Enter to compile")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setStyleSheet("color: gray; font-size: 13px;")
        self._preview_label.setMargin(40)
        self._preview_scroll.setWidget(self._preview_label)
        self._preview_scroll.setWidgetResizable(True)
        right_layout.addWidget(self._preview_scroll, stretch=1)

        # Scale slider
        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("Scale:"))
        self._scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._scale_slider.setRange(25, 400)
        self._scale_slider.setValue(100)
        self._scale_slider.setTickInterval(25)
        self._scale_slider.valueChanged.connect(self._update_preview_scale)
        scale_row.addWidget(self._scale_slider)
        self._scale_val_label = QLabel("100%")
        self._scale_val_label.setMinimumWidth(42)
        scale_row.addWidget(self._scale_val_label)
        right_layout.addLayout(scale_row)

        # Error output
        self._error_box = QTextEdit()
        self._error_box.setReadOnly(True)
        self._error_box.setFont(QFont("monospace", 9))
        self._error_box.setMaximumHeight(90)
        self._error_box.setVisible(False)
        self._error_box.setStyleSheet("background: #fff0f0; color: #c0392b;")
        right_layout.addWidget(self._error_box)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        # Status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._compile)
        QShortcut(QKeySequence("Ctrl+S"),      self, activated=self._save_snippet)
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, activated=self._copy_svg)

    # ── Compile ───────────────────────────────────────────────────────────────
    def _compile(self):
        expr = self._editor.toPlainText().strip()
        if not expr:
            self._status.showMessage("Nothing to compile.", 3000)
            return

        self._status.showMessage("Compiling…")
        self._error_box.setVisible(False)

        tex = build_tex(expr, self._settings)

        self._compile_thread = QThread()
        self._worker = CompileWorker(tex, self._settings)
        self._worker.moveToThread(self._compile_thread)
        self._compile_thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_compile_done)
        self._worker.finished.connect(self._compile_thread.quit)
        self._compile_thread.start()

    def _on_compile_done(self, svg_path: str, error: str):
        if error:
            self._error_box.setPlainText(error)
            self._error_box.setVisible(True)
            self._status.showMessage("Compile error — see log below.", 5000)
            return

        self._current_svg_path = svg_path
        self._render_svg(svg_path)
        self._status.showMessage("Compiled successfully.", 3000)

        if self._settings.get("auto_save", True):
            expr = self._editor.toPlainText().strip()
            self._store.add(expr)
            self._refresh_history()

    def _render_svg(self, svg_path: str):
        scale = self._scale_slider.value() / 100.0
        renderer = QSvgRenderer(svg_path)
        base = renderer.defaultSize()
        w = int(base.width() * scale * 2)
        h = int(base.height() * scale * 2)
        if w < 1 or h < 1:
            self._status.showMessage("SVG has zero size.", 3000)
            return

        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.white)

        from PyQt6.QtGui import QPainter
        painter = QPainter(img)
        renderer.render(painter)
        painter.end()

        pixmap = QPixmap.fromImage(img)
        lbl = QLabel()
        lbl.setPixmap(pixmap)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setMargin(20)
        lbl.setStyleSheet("background: white;")

        self._preview_scroll.setWidget(lbl)
        self._preview_label = lbl

    def _update_preview_scale(self, value: int):
        self._scale_val_label.setText(f"{value}%")
        if self._current_svg_path:
            self._render_svg(self._current_svg_path)

    # ── Copy / Export ─────────────────────────────────────────────────────────
    def _copy_svg(self):
        if not self._current_svg_path:
            self._status.showMessage("Nothing compiled yet.", 3000)
            return
        svg_text = Path(self._current_svg_path).read_text(encoding="utf-8")
        cb = QApplication.clipboard()
        cb.setText(svg_text)
        self._status.showMessage("SVG copied to clipboard.", 3000)

    def _copy_png(self):
        if not self._current_svg_path:
            self._status.showMessage("Nothing compiled yet.", 3000)
            return
        dpi = self._settings.get("png_dpi", 300)
        renderer = QSvgRenderer(self._current_svg_path)
        base = renderer.defaultSize()
        scale = dpi / 96.0
        w = int(base.width() * scale)
        h = int(base.height() * scale)
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.white)
        from PyQt6.QtGui import QPainter
        p = QPainter(img)
        renderer.render(p)
        p.end()
        QApplication.clipboard().setPixmap(QPixmap.fromImage(img))
        self._status.showMessage(f"PNG copied ({w}×{h} px @ {dpi} dpi).", 3000)

    def _export_file(self):
        if not self._current_svg_path:
            self._status.showMessage("Nothing compiled yet.", 3000)
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", str(Path.home()),
            "SVG Files (*.svg);;PNG Files (*.png)"
        )
        if not path:
            return
        if path.endswith(".png"):
            dpi = self._settings.get("png_dpi", 300)
            renderer = QSvgRenderer(self._current_svg_path)
            base = renderer.defaultSize()
            scale = dpi / 96.0
            img = QImage(int(base.width()*scale), int(base.height()*scale), QImage.Format.Format_ARGB32)
            img.fill(Qt.GlobalColor.white)
            from PyQt6.QtGui import QPainter
            p = QPainter(img)
            renderer.render(p)
            p.end()
            img.save(path)
        else:
            shutil.copy(self._current_svg_path, path)
        self._status.showMessage(f"Exported to {path}", 4000)

    # ── Snippet history ───────────────────────────────────────────────────────
    def _save_snippet(self):
        expr = self._editor.toPlainText().strip()
        if not expr:
            return
        label, ok = QInputDialog.getText(self, "Save snippet", "Label (optional):", text=expr[:40])
        if ok:
            self._store.add(expr, label)
            self._refresh_history()
            self._status.showMessage("Saved.", 2000)

    def _refresh_history(self):
        self._history_list.clear()
        for item in self._store.all():
            li = QListWidgetItem(item["label"])
            li.setData(Qt.ItemDataRole.UserRole, item["code"])
            li.setToolTip(item["code"])
            self._history_list.addItem(li)

    def _load_from_history(self, item: QListWidgetItem | None):
        if item is None:
            return
        code = item.data(Qt.ItemDataRole.UserRole)
        self._editor.setPlainText(code)
        self._tabs.setCurrentIndex(0)
        self._compile()

    def _delete_snippet(self):
        row = self._history_list.currentRow()
        if row < 0:
            return
        self._store.remove(row)
        self._refresh_history()

    def _history_context_menu(self, pos):
        item = self._history_list.itemAt(pos)
        if not item:
            return
        row = self._history_list.row(item)
        menu = QMenu(self)
        load_act = menu.addAction("Load")
        rename_act = menu.addAction("Rename")
        delete_act = menu.addAction("Delete")
        act = menu.exec(self._history_list.mapToGlobal(pos))
        if act == load_act:
            self._load_from_history(item)
        elif act == rename_act:
            label, ok = QInputDialog.getText(self, "Rename", "New label:", text=item.text())
            if ok:
                self._store.rename(row, label)
                self._refresh_history()
        elif act == delete_act:
            self._store.remove(row)
            self._refresh_history()

    # ── Settings ──────────────────────────────────────────────────────────────
    def _open_settings(self):
        dlg = SettingsDialog(self._settings, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._settings = dlg.get_settings()
            SETTINGS_FILE.write_text(json.dumps(self._settings, indent=2))
            self._status.showMessage("Settings saved.", 2000)

    def _insert(self, code: str):
        cursor = self._editor.textCursor()
        cursor.insertText(code)
        self._editor.setTextCursor(cursor)
        self._editor.setFocus()

    def closeEvent(self, event):
        SETTINGS_FILE.write_text(json.dumps(self._settings, indent=2))
        super().closeEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LaTeX Snippets")
    app.setStyle("Fusion")

    # Check for required tools
    missing = [t for t in ("latex", "dvisvgm") if not shutil.which(t)]
    if missing:
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Missing tools")
        msg.setText(
            f"The following tools were not found on PATH:\n  {', '.join(missing)}\n\n"
            "Install TeX Live (texlive-full or texlive-base + texlive-science) "
            "and dvisvgm to compile expressions.\n\n"
            "The app will still open but compilation will fail."
        )
        msg.exec()

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()