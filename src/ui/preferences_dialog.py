"""Tabbed preferences editor for ccwork.

Save writes `~/.config/ccwork/settings.toml`. Font / bg / fg apply live
to running terminals via OSC (see `xterm_osc.py`); scrollback, scrollbar,
and extra args need a respawn (right-click a repo → Reload terminal).
"""

from __future__ import annotations

import copy
import shlex
from dataclasses import dataclass

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.settings import Settings, UISettings, XtermSettings, save_settings


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

        help_lbl = QLabel(
            "Tip: drag the splitter to resize the sidebar — the width persists.",
            w,
        )
        help_lbl.setWordWrap(True)
        help_lbl.setStyleSheet("color: #888;")
        form.addRow("", help_lbl)

        return w

    # ── Advanced tab ──

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
        # sidebar_width is set live by splitter drag — preserve whatever the
        # user last dragged it to.
        self._settings.ui = UISettings(
            sidebar_side=self._sidebar_side.currentText(),
            sidebar_width=int(self._settings.ui.sidebar_width),
            restore_last_repo=bool(self._restore_last.isChecked()),
            desktop_notifications=bool(self._desktop_notifs.isChecked()),
            status_badge_style=str(self._badge_style.currentData() or "dot"),
            auto_arrange_repos=bool(self._auto_arrange.isChecked()),
            group_active_repos=bool(self._group_active.isChecked()),
            warn_on_ctrl_z=bool(self._warn_ctrl_z.isChecked()),
        )

        try:
            save_settings(self._settings)
        except OSError as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return

        self.applied.emit(self._settings)
        self.accept()
