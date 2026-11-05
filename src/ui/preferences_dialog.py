"""Tabbed preferences editor for ccwork.

Save writes `~/.config/ccwork/settings.toml`. Font / bg / fg apply live
to running terminals via OSC (see `xterm_osc.py`); scrollback, scrollbar,
and extra args need a respawn (right-click a repo → Reload terminal). The
Rows tab previews each edit in the sidebar through `rows_previewed`.
"""

from __future__ import annotations

import copy
import shlex
from dataclasses import dataclass, replace

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core.settings import (
    ROW_LINE_IDS,
    RowLineSettings,
    RowSettings,
    Settings,
    UISettings,
    XtermSettings,
    save_settings,
)

ROW_LINE_NAMES = {"title": "Title", "repo": "Repo · branch", "status": "Status"}
ROW_LAYOUT_NAMES = {"equal": "Equal thirds", "sized": "Sized to each line", "packed": "Packed with a gap"}
ROW_COLOR_NAMES = {"text": "Text", "sub": "Sub", "muted": "Muted", "accent": "Row accent"}
ROW_HIGHLIGHT_NAMES = {"accent": "Row accent, light", "marker": "Yellow marker"}
CUSTOM = "Custom"


# ── Color-scheme presets ────────────────────────────────────────────────────
# Curated: three dark and three light well-known schemes. Users can always
# override via the color pickers — doing so flips the combo to "Custom".


@dataclass(frozen=True)
class ColorScheme:
    name: str
    bg: str
    fg: str
    kind: str  # "dark" | "light" | "custom"


DARK_SCHEMES: list[ColorScheme] = [
    ColorScheme("Solarized Dark", "#002b36", "#93a1a1", "dark"),
    ColorScheme("Dracula",        "#282a36", "#f8f8f2", "dark"),
    ColorScheme("Gruvbox Dark",   "#282828", "#ebdbb2", "dark"),
]

LIGHT_SCHEMES: list[ColorScheme] = [
    ColorScheme("Solarized Light", "#fdf6e3", "#586e75", "light"),
    ColorScheme("GitHub Light",    "#ffffff", "#24292f", "light"),
    ColorScheme("Tomorrow",        "#ffffff", "#4d4d4c", "light"),
]

CUSTOM_SCHEME = ColorScheme("Custom", "", "", "custom")

COLOR_SCHEMES: list[ColorScheme] = [*DARK_SCHEMES, *LIGHT_SCHEMES, CUSTOM_SCHEME]


# ── Color button widget ─────────────────────────────────────────────────────


class _ColorButton(QPushButton):
    """Square button whose face shows the current color and opens a picker."""

    color_changed = Signal(str)  # new color hex

    def __init__(self, initial: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(110)
        self._color = QColor(initial)
        self._refresh()
        self.clicked.connect(self._pick)

    def value(self) -> str:
        return self._color.name(QColor.HexRgb)

    def set_value(self, s: str) -> None:
        c = QColor(s)
        if c.isValid() and c != self._color:
            self._color = c
            self._refresh()
            self.color_changed.emit(self.value())

    def _refresh(self) -> None:
        name = self._color.name(QColor.HexRgb)
        self.setText(name)
        fg = "#000" if self._color.lightness() > 128 else "#fff"
        self.setStyleSheet(f"background: {name}; color: {fg}; border: 1px solid #888;")

    def _pick(self) -> None:
        c = QColorDialog.getColor(self._color, self, "Pick color")
        if c.isValid():
            self._color = c
            self._refresh()
            self.color_changed.emit(self.value())


# ── Preview pane ────────────────────────────────────────────────────────────


class _PreviewLabel(QLabel):
    """Tiny mock terminal showing the current font + bg/fg pair."""

    SAMPLE = "$ claude --help\n[ccwork] Ready. Type to start a session.\n■"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setText(self.SAMPLE)
        self.setMinimumHeight(70)
        self.setContentsMargins(10, 8, 10, 8)

    def apply(self, font_family: str, font_size: int, bg: str, fg: str) -> None:
        f = QFont(font_family)
        f.setPointSize(int(font_size))
        f.setStyleHint(QFont.Monospace)
        self.setFont(f)
        self.setStyleSheet(
            f"background: {bg}; color: {fg}; padding: 8px; "
            f"border: 1px solid #888;"
        )


# ── Dialog ──────────────────────────────────────────────────────────────────


class PreferencesDialog(QDialog):
    """Modal tabbed preferences editor.

    Emits `applied(Settings)` once on accept, AFTER saving to disk.
    """

    applied = Signal(Settings)
    rows_previewed = Signal(object)  # RowSettings, after each Rows tab edit

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ccwork preferences")
        self.setModal(True)
        self._settings = copy.deepcopy(settings)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_text_tab(), "Text")
        tabs.addTab(self._build_colors_tab(), "Colors")
        tabs.addTab(self._build_scrolling_tab(), "Scrolling")
        tabs.addTab(self._build_ui_tab(), "UI")
        tabs.addTab(self._build_rows_tab(), "Rows")
        tabs.addTab(self._build_advanced_tab(), "Advanced")

        hint = QLabel(
            "Most edits apply live to running terminals. Scrollback, scrollbar, "
            "and extra args need a respawn — right-click a repo → Reload terminal.",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; padding: 6px 2px;")

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save
            | QDialogButtonBox.Cancel
            | QDialogButtonBox.RestoreDefaults,
            parent=self,
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._on_restore_defaults)

        root = QVBoxLayout(self)
        root.addWidget(tabs, 1)
        root.addWidget(self._preview)
        root.addWidget(hint)
        root.addWidget(buttons)
        self.resize(560, 540)

        self._refresh_preview()

    # ── Text tab ──

    def _build_text_tab(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)

        self._font = QFontComboBox(w)
        self._font.setFontFilters(QFontComboBox.MonospacedFonts)
        self._font.setCurrentText(self._settings.xterm.font_family)
        self._font.currentFontChanged.connect(lambda *_: self._refresh_preview())
        self._font.setToolTip("Terminal font. The list is filtered to monospaced families.")
        form.addRow("Font family", self._font)

        self._font_size = QSpinBox(w)
        self._font_size.setRange(6, 48)
        self._font_size.setValue(self._settings.xterm.font_size)
        self._font_size.setSuffix(" pt")
        self._font_size.valueChanged.connect(lambda *_: self._refresh_preview())
        self._font_size.setToolTip("Terminal font size in points.")
        form.addRow("Font size", self._font_size)

        return w

    # ── Colors tab ──

    def _build_colors_tab(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)

        self._scheme = QComboBox(w)
        self._populate_scheme_combo()
        # Select scheme matching current bg/fg, else "Custom".
        self._scheme.setCurrentText(self._match_scheme_name(self._settings.xterm.bg, self._settings.xterm.fg))
        self._scheme.currentIndexChanged.connect(self._on_scheme_picked)
        self._scheme.setToolTip("Pick a known palette. Overwrites both swatches below.")
        form.addRow("Preset", self._scheme)

        self._bg = _ColorButton(self._settings.xterm.bg, w)
        self._fg = _ColorButton(self._settings.xterm.fg, w)
        self._bg.color_changed.connect(self._on_color_changed_manually)
        self._fg.color_changed.connect(self._on_color_changed_manually)
        self._bg.setToolTip("Terminal background. Picking a custom color switches the preset to Custom.")
        self._fg.setToolTip("Terminal foreground (text). Picking a custom color switches the preset to Custom.")

        swatch_row = QWidget(w)
        lay = QHBoxLayout(swatch_row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("Background"))
        lay.addWidget(self._bg)
        lay.addSpacing(20)
        lay.addWidget(QLabel("Foreground"))
        lay.addWidget(self._fg)
        lay.addStretch(1)
        form.addRow("", swatch_row)

        help_lbl = QLabel(
            "Picking a preset overwrites both colors. Click a swatch to "
            "override manually — the preset will switch to Custom.",
            w,
        )
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet("color: #888;")
        form.addRow("", help_lbl)

        return w

    # ── Scrolling tab ──

    def _build_scrolling_tab(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)

        self._scrollback = QSpinBox(w)
        self._scrollback.setRange(0, 1_000_000)
        self._scrollback.setSingleStep(1000)
        self._scrollback.setValue(self._settings.xterm.scrollback)
        self._scrollback.setSuffix(" lines")
        self._scrollback.setToolTip("Lines of terminal history retained. 0 disables scrollback.")
        form.addRow("Scrollback buffer", self._scrollback)

        self._scrollbar = QComboBox(w)
        self._scrollbar.addItems(["right", "left", "none"])
        self._scrollbar.setCurrentText(self._settings.xterm.scrollbar)
        self._scrollbar.setToolTip("Where to draw xterm's scrollbar, if at all.")
        form.addRow("Scrollbar", self._scrollbar)

        self._jump = QCheckBox("Jump scroll (redraw one screen at a time when output is heavy)", w)
        self._jump.setChecked(self._settings.xterm.jump_scroll)
        self._jump.setToolTip(
            "During heavy output, redraw a screen at a time instead of every line. "
            "Lets the terminal keep up at the cost of skipping intermediate frames."
        )
        form.addRow("", self._jump)

        help_lbl = QLabel(
            "Tip: Shift+PgUp / Shift+PgDn page through scrollback in xterm.",
            w,
        )
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet("color: #888;")
        form.addRow("", help_lbl)

        return w

    # ── UI tab ──

    def _build_ui_tab(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)
        ui = self._settings.ui

        self._sidebar_side = QComboBox(w)
        self._sidebar_side.addItems(["left", "right"])
        self._sidebar_side.setCurrentText(ui.sidebar_side)
        self._sidebar_side.setToolTip("Which side of the window the repo list lives on.")
        form.addRow("Sidebar position", self._sidebar_side)

        self._badge_style = QComboBox(w)
        self._badge_style.addItem("Colored dot", "dot")
        self._badge_style.addItem("Glyph (! ✓ ·)", "glyph")
        idx = self._badge_style.findData(ui.status_badge_style)
        self._badge_style.setCurrentIndex(idx if idx >= 0 else 0)
        self._badge_style.setToolTip(
            "Shape of the right-edge alert on each repo row: a colored dot or a single character."
        )
        form.addRow("Status badge", self._badge_style)

        self._restore_last = QCheckBox("Reopen the last-used repo on launch", w)
        self._restore_last.setChecked(ui.restore_last_repo)
        self._restore_last.setToolTip(
            "On startup, re-select whichever repo row was active when ccwork last closed."
        )
        form.addRow("", self._restore_last)

        self._desktop_notifs = QCheckBox("Show desktop notifications (Stop / Notification)", w)
        self._desktop_notifs.setChecked(ui.desktop_notifications)
        self._desktop_notifs.setToolTip(
            "Off suppresses notify-send pop-ups; in-window cues (bell dot, sidebar status) "
            "stay on. The 🔊 / 🔇 top-bar button mirrors this setting."
        )
        form.addRow("", self._desktop_notifs)

        self._auto_arrange = QCheckBox("Auto-arrange repos by recent Claude activity", w)
        self._auto_arrange.setChecked(ui.auto_arrange_repos)
        self._auto_arrange.setToolTip(
            "Reorders rows by Claude-driven events (Stop / Notification / UserPromptSubmit) "
            "~2 s after the last event. User-driven row switches don't count."
        )
        form.addRow("", self._auto_arrange)

        self._group_active = QCheckBox(
            "Group active sessions at the top of the sidebar", w,
        )
        self._group_active.setChecked(ui.group_active_repos)
        self._group_active.setToolTip(
            "Repos running a live Claude session float to the top of the "
            "list. A terminal left at a bash prompt sinks to the bottom."
        )
        form.addRow("", self._group_active)

        self._warn_ctrl_z = QCheckBox("Warn before sending Ctrl+Z to the terminal", w)
        self._warn_ctrl_z.setChecked(ui.warn_on_ctrl_z)
        self._warn_ctrl_z.setToolTip(
            "Ctrl+Z in a shell sends SIGTSTP and suspends the running process "
            "(usually Claude), dropping to a bash prompt. When on, a "
            "confirmation dialog appears first."
        )
        form.addRow("", self._warn_ctrl_z)

        self._show_status_text = QCheckBox("Show status text in sidebar rows", w)
        self._show_status_text.setChecked(ui.show_status_text)
        self._show_status_text.setToolTip(
            "Line 3 of each row says what Claude is doing: the badge's word "
            "(\"Needs permission\", \"Rate limited\", …), \"Working · 2m\", or "
            "\"Claude open\". Off leaves the line blank."
        )
        form.addRow("", self._show_status_text)

        expire_row = QWidget(w)
        expire_box = QHBoxLayout(expire_row)
        expire_box.setContentsMargins(0, 0, 0, 0)
        self._expire_idle = QCheckBox("Remove idle repos from the sidebar after", expire_row)
        self._expire_idle.setChecked(ui.expire_idle_repos)
        self._expire_idle.setToolTip(
            "A repo with no Claude activity and no click for this many days "
            "moves to the Recent list, where one click brings it back. "
            "Repos with an open terminal never expire."
        )
        self._expire_days = QSpinBox(expire_row)
        self._expire_days.setRange(1, 3650)
        self._expire_days.setSuffix(" days")
        self._expire_days.setValue(ui.expire_idle_days)
        self._expire_days.setEnabled(ui.expire_idle_repos)
        self._expire_idle.toggled.connect(self._expire_days.setEnabled)
        expire_box.addWidget(self._expire_idle)
        expire_box.addWidget(self._expire_days)
        expire_box.addStretch(1)
        form.addRow("", expire_row)

        folder_row = QWidget(w)
        folder_box = QHBoxLayout(folder_row)
        folder_box.setContentsMargins(0, 0, 0, 0)
        self._worktree_folder = QLineEdit(ui.worktree_folder, folder_row)
        self._worktree_folder.setPlaceholderText("Beside the main checkout")
        self._worktree_folder.setToolTip(
            "Make worktree puts each new worktree in this folder, as "
            "<folder>/<repo>-<branch>. Empty puts it beside the main checkout."
        )
        browse = QPushButton("Browse…", folder_row)
        browse.clicked.connect(self._pick_worktree_folder)
        folder_box.addWidget(self._worktree_folder, 1)
        folder_box.addWidget(browse)
        form.addRow("Worktree folder", folder_row)

        help_lbl = QLabel(
            "Tip: drag the splitter to resize the sidebar — the width persists.",
            w,
        )
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet("color: #888;")
        form.addRow("", help_lbl)

        return w

    # ── Advanced tab ──

    # ── Rows tab ──

    def _build_rows_tab(self) -> QWidget:
        w = QWidget(self)
        root = QVBoxLayout(w)
        row_form = QFormLayout()
        root.addLayout(row_form)

        def spin(lo: int, hi: int, suffix: str) -> QSpinBox:
            box = QSpinBox(w)
            box.setRange(lo, hi)
            box.setSuffix(suffix)
            return box

        def dspin(lo: float, hi: float, step: float, suffix: str) -> QDoubleSpinBox:
            box = QDoubleSpinBox(w)
            box.setRange(lo, hi)
            box.setSingleStep(step)
            box.setDecimals(1)
            box.setSuffix(suffix)
            return box

        def combo(names: dict[str, str], custom: bool) -> QComboBox:
            box = QComboBox(w)
            for key, name in names.items():
                box.addItem(name, key)
            if custom:
                box.addItem(CUSTOM, CUSTOM)
            return box

        self._row_height = spin(16, 200, " px")
        self._row_inset = spin(0, 30, " px")
        self._row_layout = combo(ROW_LAYOUT_NAMES, custom=False)
        self._row_gap = spin(0, 30, " px")
        self._row_collapse = QCheckBox("A hidden line gives its space to the others", w)
        row_form.addRow("Row height", self._row_height)
        row_form.addRow("Top and bottom inset", self._row_inset)
        row_form.addRow("Line layout", self._row_layout)
        row_form.addRow("Gap between lines", self._row_gap)
        row_form.addRow("", self._row_collapse)

        # The lines in paint order, with buttons to move the selected one.
        self._line_list = QListWidget(w)
        up, down = QToolButton(w), QToolButton(w)
        up.setText("▲")
        down.setText("▼")
        up.setToolTip("Move the line up")
        down.setToolTip("Move the line down")
        up.clicked.connect(lambda: self._move_line(-1))
        down.clicked.connect(lambda: self._move_line(1))
        moves = QVBoxLayout()
        moves.addWidget(up)
        moves.addWidget(down)
        moves.addStretch(1)
        order_row = QHBoxLayout()
        order_row.addWidget(self._line_list, 1)
        order_row.addLayout(moves)
        row_form.addRow("Line order", order_row)

        line_form = QFormLayout()
        root.addLayout(line_form)
        self._ln_visible = QCheckBox("Shown", w)
        self._ln_size = dspin(4, 40, 0.5, " px")
        self._ln_family = QComboBox(w)
        self._ln_family.addItem("App font", "")
        for family in QFontDatabase.families():
            self._ln_family.addItem(family, family)
        self._ln_follow = QCheckBox("Bold with a terminal, italic without", w)
        self._ln_styles: dict[str, QToolButton] = {}
        styles = QHBoxLayout()
        for key, label, tip in (
            ("bold", "B", "Bold"), ("italic", "I", "Italic"), ("underline", "U", "Underline"),
            ("strike", "S", "Strikeout"), ("caps", "ABC", "All capitals"), ("small_caps", "Small caps", "Small capitals"),
        ):
            btn = QToolButton(w)
            btn.setText(label)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.toggled.connect(self._on_line_edited)
            styles.addWidget(btn)
            self._ln_styles[key] = btn
        styles.addStretch(1)
        self._ln_color = combo(ROW_COLOR_NAMES, custom=True)
        self._ln_color_btn = _ColorButton("#24292f", w)
        color_row = QHBoxLayout()
        color_row.addWidget(self._ln_color)
        color_row.addWidget(self._ln_color_btn)
        color_row.addStretch(1)
        self._ln_highlight = QCheckBox("Highlight", w)
        self._ln_hl_color = combo(ROW_HIGHLIGHT_NAMES, custom=True)
        self._ln_hl_btn = _ColorButton("#fff1a8", w)
        hl_row = QHBoxLayout()
        hl_row.addWidget(self._ln_highlight)
        hl_row.addWidget(self._ln_hl_color)
        hl_row.addWidget(self._ln_hl_btn)
        hl_row.addStretch(1)
        self._ln_opacity = spin(0, 100, " %")
        self._ln_tracking = dspin(-1, 4, 0.1, " px")
        self._ln_title = QLabel(w)
        line_form.addRow(self._ln_title)
        line_form.addRow("", self._ln_visible)
        line_form.addRow("Size", self._ln_size)
        line_form.addRow("Font", self._ln_family)
        line_form.addRow("Style", styles)
        line_form.addRow("", self._ln_follow)
        line_form.addRow("Color", color_row)
        line_form.addRow("", hl_row)
        line_form.addRow("Opacity", self._ln_opacity)
        line_form.addRow("Letter spacing", self._ln_tracking)

        self._load_rows()
        self._line_list.setFixedHeight(
            self._line_list.sizeHintForRow(0) * len(ROW_LINE_IDS) + 2 * self._line_list.frameWidth())
        for box in (self._row_height, self._row_inset, self._row_gap):
            box.valueChanged.connect(self._on_row_edited)
        self._row_layout.currentIndexChanged.connect(self._on_row_edited)
        self._row_collapse.toggled.connect(self._on_row_edited)
        self._line_list.currentRowChanged.connect(lambda _: self._load_line())
        for box in (self._ln_size, self._ln_tracking, self._ln_opacity):
            box.valueChanged.connect(self._on_line_edited)
        for box in (self._ln_family, self._ln_color, self._ln_hl_color):
            box.currentIndexChanged.connect(self._on_line_edited)
        for check in (self._ln_visible, self._ln_follow, self._ln_highlight):
            check.toggled.connect(self._on_line_edited)
        for btn in (self._ln_color_btn, self._ln_hl_btn):
            btn.color_changed.connect(self._on_line_edited)
        return w

    def _line_id(self) -> str:
        return self._line_list.currentItem().data(Qt.UserRole)

    def _load_rows(self) -> None:
        """Show `self._settings.ui.rows` in the Rows tab without previewing."""
        rows = self._settings.ui.rows
        widgets = (self._row_height, self._row_inset, self._row_layout, self._row_gap,
                   self._row_collapse, self._line_list)
        for widget in widgets:
            widget.blockSignals(True)
        self._row_height.setValue(rows.height)
        self._row_inset.setValue(rows.inset)
        self._row_layout.setCurrentIndex(self._row_layout.findData(rows.layout))
        self._row_gap.setValue(rows.gap)
        self._row_gap.setEnabled(rows.layout == "packed")
        self._row_collapse.setChecked(rows.collapse_hidden)
        self._line_list.clear()
        for line_id in rows.order:
            self._line_list.addItem(ROW_LINE_NAMES[line_id])
            self._line_list.item(self._line_list.count() - 1).setData(Qt.UserRole, line_id)
        self._line_list.setCurrentRow(0)
        for widget in widgets:
            widget.blockSignals(False)
        self._load_line()

    def _load_line(self) -> None:
        """Show the selected line's settings in the line editor."""
        line_id = self._line_id()
        line: RowLineSettings = getattr(self._settings.ui.rows, line_id)
        widgets = (self._ln_visible, self._ln_size, self._ln_family, self._ln_follow,
                   self._ln_color, self._ln_color_btn, self._ln_highlight, self._ln_hl_color,
                   self._ln_hl_btn, self._ln_opacity, self._ln_tracking, *self._ln_styles.values())
        for widget in widgets:
            widget.blockSignals(True)
        self._ln_title.setText(f"<b>{ROW_LINE_NAMES[line_id]}</b>")
        self._ln_visible.setChecked(line.visible)
        self._ln_size.setValue(line.size)
        family = self._ln_family.findData(line.family)
        if family < 0:  # a family this machine lacks still shows by name
            self._ln_family.addItem(line.family, line.family)
            family = self._ln_family.count() - 1
        self._ln_family.setCurrentIndex(family)
        self._ln_follow.setVisible(line_id == "title")
        self._ln_follow.setChecked(line.follow_terminal)
        for key, btn in self._ln_styles.items():
            btn.setChecked(getattr(line, key))
        self._set_color_pick(self._ln_color, self._ln_color_btn, line.color)
        self._ln_highlight.setChecked(line.highlight)
        self._set_color_pick(self._ln_hl_color, self._ln_hl_btn, line.highlight_color)
        self._ln_opacity.setValue(line.opacity)
        self._ln_tracking.setValue(line.tracking)
        for widget in widgets:
            widget.blockSignals(False)
        self._sync_line_enabled()

    @staticmethod
    def _set_color_pick(box: QComboBox, btn: _ColorButton, value: str) -> None:
        idx = box.findData(value)
        box.setCurrentIndex(idx if idx >= 0 else box.findData(CUSTOM))
        if idx < 0:
            btn.set_value(value)

    @staticmethod
    def _color_pick(box: QComboBox, btn: _ColorButton) -> str:
        key = box.currentData()
        return btn.value() if key == CUSTOM else key

    def _sync_line_enabled(self) -> None:
        follow = self._ln_follow.isVisible() and self._ln_follow.isChecked()
        self._ln_styles["bold"].setEnabled(not follow)
        self._ln_styles["italic"].setEnabled(not follow)
        self._ln_color_btn.setVisible(self._ln_color.currentData() == CUSTOM)
        self._ln_hl_color.setEnabled(self._ln_highlight.isChecked())
        self._ln_hl_btn.setVisible(self._ln_highlight.isChecked() and self._ln_hl_color.currentData() == CUSTOM)

    def _on_row_edited(self, *_: object) -> None:
        rows = self._settings.ui.rows
        rows.height = self._row_height.value()
        rows.inset = self._row_inset.value()
        rows.layout = self._row_layout.currentData()
        rows.gap = self._row_gap.value()
        rows.collapse_hidden = self._row_collapse.isChecked()
        self._row_gap.setEnabled(rows.layout == "packed")
        self.rows_previewed.emit(copy.deepcopy(rows))

    def _on_line_edited(self, *_: object) -> None:
        line: RowLineSettings = getattr(self._settings.ui.rows, self._line_id())
        line.visible = self._ln_visible.isChecked()
        line.size = self._ln_size.value()
        line.family = self._ln_family.currentData()
        line.follow_terminal = self._ln_follow.isChecked()
        for key, btn in self._ln_styles.items():
            setattr(line, key, btn.isChecked())
        line.color = self._color_pick(self._ln_color, self._ln_color_btn)
        line.highlight = self._ln_highlight.isChecked()
        line.highlight_color = self._color_pick(self._ln_hl_color, self._ln_hl_btn)
        line.opacity = self._ln_opacity.value()
        line.tracking = self._ln_tracking.value()
        self._sync_line_enabled()
        self.rows_previewed.emit(copy.deepcopy(self._settings.ui.rows))

    def _move_line(self, step: int) -> None:
        order = self._settings.ui.rows.order
        i = self._line_list.currentRow()
        j = i + step
        if not 0 <= j < len(order):
            return
        order[i], order[j] = order[j], order[i]
        item = self._line_list.takeItem(i)
        self._line_list.insertItem(j, item)
        self._line_list.setCurrentRow(j)
        self.rows_previewed.emit(copy.deepcopy(self._settings.ui.rows))

    def _build_advanced_tab(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)

        self._extras = QLineEdit(w)
        self._extras.setText(" ".join(shlex.quote(a) for a in self._settings.xterm.extra_args))
        self._extras.setPlaceholderText("-bdc -xrm 'XTerm*cursorBlink: true'")
        self._extras.setToolTip(
            "Raw flags appended to every xterm spawn. Parsed with shell "
            "quoting rules. See <code>man xterm</code> for the full list."
        )
        form.addRow("Extra xterm args", self._extras)

        return w

    # ── Preview pane (shared across tabs) ──

    @property
    def _preview(self) -> _PreviewLabel:
        # Lazily create so all tabs are built first.
        if not hasattr(self, "_preview_lbl"):
            self._preview_lbl = _PreviewLabel(self)
        return self._preview_lbl

    def _refresh_preview(self) -> None:
        self._preview.apply(
            font_family=self._font.currentFont().family(),
            font_size=int(self._font_size.value()),
            bg=self._bg.value(),
            fg=self._fg.value(),
        )

    # ── color scheme plumbing ──

    def _populate_scheme_combo(self) -> None:
        """Fill the combo as: Dark group / separator / Light group / separator / Custom."""
        for sch in DARK_SCHEMES:
            self._scheme.addItem(sch.name)
        self._scheme.insertSeparator(self._scheme.count())
        for sch in LIGHT_SCHEMES:
            self._scheme.addItem(sch.name)
        self._scheme.insertSeparator(self._scheme.count())
        self._scheme.addItem(CUSTOM_SCHEME.name)

    def _match_scheme_name(self, bg: str, fg: str) -> str:
        bg_n = QColor(bg).name(QColor.HexRgb).lower()
        fg_n = QColor(fg).name(QColor.HexRgb).lower()
        for sch in COLOR_SCHEMES:
            if not sch.bg:
                continue
            if QColor(sch.bg).name(QColor.HexRgb).lower() == bg_n and \
               QColor(sch.fg).name(QColor.HexRgb).lower() == fg_n:
                return sch.name
        return "Custom"

    def _on_scheme_picked(self, _idx: int) -> None:
        name = self._scheme.currentText()
        sch = next((s for s in COLOR_SCHEMES if s.name == name), None)
        if sch is None or sch.kind == "custom":
            return
        # Block manual-change signals so picking a preset doesn't flip itself
        # back to "Custom".
        self._bg.blockSignals(True)
        self._fg.blockSignals(True)
        self._bg.set_value(sch.bg)
        self._fg.set_value(sch.fg)
        self._bg.blockSignals(False)
        self._fg.blockSignals(False)
        self._refresh_preview()

    def _on_color_changed_manually(self, *_: object) -> None:
        # Any manual pick drops us to "Custom".
        self._scheme.blockSignals(True)
        self._scheme.setCurrentText("Custom")
        self._scheme.blockSignals(False)
        self._refresh_preview()

    # ── button handlers ──

    def _pick_worktree_folder(self) -> None:
        picked = QFileDialog.getExistingDirectory(self, "Worktree folder",
                                                  self._worktree_folder.text())
        if picked:
            self._worktree_folder.setText(picked)

    def _on_restore_defaults(self) -> None:
        d = XtermSettings()
        du = UISettings()
        self._sidebar_side.setCurrentText(du.sidebar_side)
        bidx = self._badge_style.findData(du.status_badge_style)
        self._badge_style.setCurrentIndex(bidx if bidx >= 0 else 0)
        self._restore_last.setChecked(du.restore_last_repo)
        self._desktop_notifs.setChecked(du.desktop_notifications)
        self._auto_arrange.setChecked(du.auto_arrange_repos)
        self._group_active.setChecked(du.group_active_repos)
        self._warn_ctrl_z.setChecked(du.warn_on_ctrl_z)
        self._show_status_text.setChecked(du.show_status_text)
        self._expire_idle.setChecked(du.expire_idle_repos)
        self._expire_days.setValue(du.expire_idle_days)
        self._worktree_folder.setText(du.worktree_folder)
        self._font.setCurrentText(d.font_family)
        self._font_size.setValue(d.font_size)
        self._scrollback.setValue(d.scrollback)
        self._scrollbar.setCurrentText(d.scrollbar)
        self._jump.setChecked(d.jump_scroll)
        self._bg.blockSignals(True)
        self._fg.blockSignals(True)
        self._bg.set_value(d.bg)
        self._fg.set_value(d.fg)
        self._bg.blockSignals(False)
        self._fg.blockSignals(False)
        self._scheme.setCurrentText(self._match_scheme_name(d.bg, d.fg))
        self._extras.setText("")
        self._settings.ui.rows = RowSettings()
        self._load_rows()
        self.rows_previewed.emit(copy.deepcopy(self._settings.ui.rows))
        self._refresh_preview()

    def _on_save(self) -> None:
        try:
            extras = shlex.split(self._extras.text())
        except ValueError as e:
            QMessageBox.warning(self, "Extra args", f"Couldn't parse: {e}")
            return

        new_x = XtermSettings(
            font_family=self._font.currentFont().family(),
            font_size=int(self._font_size.value()),
            scrollback=int(self._scrollback.value()),
            scrollbar=self._scrollbar.currentText(),
            jump_scroll=bool(self._jump.isChecked()),
            bg=self._bg.value(),
            fg=self._fg.value(),
            extra_args=extras,
        )
        self._settings.xterm = new_x
        # Replace only the fields this dialog edits. Everything else —
        # sidebar_width (set live by splitter drag) and the TOML-only
        # [ui.layout] / [ui.animation] knobs — keeps its current value.
        self._settings.ui = replace(
            self._settings.ui,
            sidebar_side=self._sidebar_side.currentText(),
            restore_last_repo=bool(self._restore_last.isChecked()),
            desktop_notifications=bool(self._desktop_notifs.isChecked()),
            status_badge_style=str(self._badge_style.currentData() or "dot"),
            auto_arrange_repos=bool(self._auto_arrange.isChecked()),
            group_active_repos=bool(self._group_active.isChecked()),
            warn_on_ctrl_z=bool(self._warn_ctrl_z.isChecked()),
            show_status_text=bool(self._show_status_text.isChecked()),
            expire_idle_repos=bool(self._expire_idle.isChecked()),
            expire_idle_days=int(self._expire_days.value()),
            worktree_folder=self._worktree_folder.text().strip(),
        )

        try:
            save_settings(self._settings)
        except OSError as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return

        self.applied.emit(self._settings)
        self.accept()
