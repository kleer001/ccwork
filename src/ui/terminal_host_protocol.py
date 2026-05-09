"""Structural protocol for the embedded terminal widget.

The MVP implementation (`src/ui/terminal_host.py`) embeds `xterm` via
XEmbed — Linux + X11 only. Cross-platform support (Wayland, macOS,
Windows) is planned but multi-PR work; see
`docs/roadmap-cross-platform.md` for candidate widgets and tradeoffs.

This protocol names the surface that `TerminalLifecycle` and
`MainWindow` rely on, so future implementations (QTermWidget, termqt,
…) can be slotted behind it without rewriting the lifecycle. The
current concrete `TerminalHost` satisfies it structurally — no `isa`
relationship is asserted today.

Tests can also satisfy it with a stub (`tests/test_zoom.py` already
does informally). Once a second real implementation lands, lifecycle
will accept a factory callable so the choice can be settings-driven.
"""

from __future__ import annotations

from typing import Protocol

from src.core.settings import XtermSettings


class TerminalHostLike(Protocol):
    """The surface MainWindow + TerminalLifecycle consume from a host.

    Signals are referenced as attributes (Qt signals are descriptors,
    not methods) and aren't typed structurally — Protocol can't express
    "has a Signal[int] called `finished`". Rely on duck-typing for the
    Qt connection plumbing; this protocol covers the methods.
    """

    def start(self) -> None:
        """Spawn the terminal process and embed it into this widget."""

    def stop(self) -> None:
        """Terminate the terminal process. Idempotent."""

    def is_running(self) -> bool:
        """Whether the terminal process is alive."""

    def focus_child(self) -> None:
        """Forward keyboard focus into the embedded terminal."""

    def apply_live_settings(self, xt: XtermSettings) -> list[str]:
        """Apply live-changeable settings (colors, font face/size).

        Returns a list of field names that couldn't be live-applied and
        require a respawn (e.g. `["scrollback"]`).
        """

    def paste_text(self, text: str) -> None:
        """Inject `text` into the terminal as if pasted from the clipboard."""
