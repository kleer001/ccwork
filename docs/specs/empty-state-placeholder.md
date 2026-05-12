# Empty-state placeholder

Replace the blank pane shown when no terminal is current with a centered
logo + heading + hint list. See `CLAUDE.md` for architectural context;
this document only covers the feature.

## Motivation

Two code paths land the user on `_empty_placeholder`
(`src/ui/main_window.py:113`, `:316`, `:526`):

1. **Cold start** — first launch, no repos in `repos.json`, sidebar empty.
2. **Terminal exited** — `_on_terminal_finished` (`src/ui/main_window.py:506`)
   removes the host, and when `was_current` is True it falls back to the
   placeholder. The user is left with the sidebar still populated but a
   blank right pane and no indication of what to do next.

Today's placeholder is a featureless `QWidget` with `autoFillBackground=True`
(`_make_empty_placeholder`, `src/ui/main_window.py:421`). Both situations
are dead ends — there is no surface telling the user that `Ctrl+O` adds
a repo, or that clicking a sidebar row reopens its terminal.

## Scope

In:

- A single shared empty-state widget replacing the current blank
  `QWidget`.
- Logo, heading, version/tagline, and a static list of 3–5 hints.
- Theming via the existing Qt palette so it inherits the xterm-derived
  colors (see `src/ui/qt_theme.py`).

Out:

- Dynamic per-state content (cold-start vs terminal-exited copy).
- Tutorials, onboarding flows, "what's new" panels.
- Animations of any kind.
- "Recent repos" list, news/changelog feed.

## Design

### Widget layout

A new `EmptyState(QWidget)` in `src/ui/empty_state.py`. Inside, a single
`QVBoxLayout` with stretches above and below so the content stays
vertically centered at any window height:

```
[stretch]
QLabel  — logo pixmap (96 px square, scaled from SVG, transparent bg)
QLabel  — "ccwork"  (heading font, ~22 pt, bold)
QLabel  — "v{__version__} — embedded xterm sessions for Claude Code"
          (subhead, palette text color at ~70 % alpha)
[12 px spacer]
QLabel  — hint list, rich text or one QLabel per row (see Hints)
[stretch]
```

The outer layout has equal horizontal stretches so the column also
sits centered. All `QLabel`s use `setAlignment(Qt.AlignCenter)` and
`setWordWrap(True)`.

### Hints

A static list of 3–5 lines. Each line is a single `QLabel` (easier to
style and wrap than rich-text bullets). Recommended copy:

- "Press **Ctrl+O** to add a repo"   *(always shown — wired in
  `_install_shortcuts`, `src/ui/main_window.py:168`)*
- "Right-click any repo for options"   *(always shown — context
  menu already exists in `repo_sidebar.py`)*
- "Press **Ctrl+,** for preferences"
- "Drag a folder onto this window to add it"
  **Dependency:** drag-drop is not implemented today
  (no `dragEnterEvent` / `dropEvent` in `MainWindow`). Either ship
  this hint *with* a small drop handler, or omit until drag-drop
  lands. Default for the first cut: **omit**.
- "Press F1 for keyboard shortcuts"
  **Dependency:** no cheatsheet dialog exists. Omit until a
  shortcuts dialog ships.

The first cut should therefore show three lines (Ctrl+O / right-click /
Ctrl+,). Adding the other two is a one-line edit once the prerequisite
features land.

Use `<b>` inside the label text for the shortcut glyphs (Qt's rich-text
mode kicks in automatically on `<` characters). Keep keycaps as plain
bold rather than styled `<kbd>` to avoid CSS dependency.

### Colors / theming

Do **not** set explicit colors. The palette is rebuilt from
`XtermSettings.bg`/`.fg` on every settings change (`apply_theme`,
`src/ui/qt_theme.py`), and the placeholder must follow. Two rules:

1. Subhead and hint labels use a *derived* color — read
   `self.palette().color(QPalette.WindowText)` at paint time and
   apply an alpha of ~160/255 via a stylesheet on the specific label
   (`color: rgba(...)`), or just use `WindowText` without alpha and
   accept full contrast. Recommend the simpler full-contrast path
   for the first cut.
2. The logo SVG is rendered to a transparent-background `QPixmap`;
   no palette tinting. The current logo (`logo/v2-icon.svg`,
   loaded in `src/main.py` as the window icon) reads well on both
   light and dark backgrounds — verified by eye, not by code.

### One widget or a stack?

The cold-start and terminal-exited states are similar enough that a
single static widget covers both. A `QStackedWidget` of two variants
would let us swap subheads ("Add a repo to begin" vs. "Pick a repo
from the sidebar"), but the cost — extra state plumbing in
`_on_terminal_finished` and `_on_repo_removed` — isn't worth the
marginal copy improvement. **Recommendation: single static widget.**
Revisit if user feedback shows the terminal-exited case is confusing.

### Logo loading

Read `logo/v2-icon.svg` once at `EmptyState` construction. Use
`QSvgRenderer` (from `PySide6.QtSvg`) to render to a `QPixmap` at
the chosen size, then `QLabel.setPixmap`. Cache the pixmap on the
instance — there is only one `EmptyState` per `MainWindow`, but
caching makes a future `resizeEvent`-driven re-render cheap.

The SVG path is resolved relative to the repo root, the same way
`src/main.py` does it for the window icon. Wrap in a try/except:
if the file is missing or `QtSvg` fails to load, log a warning and
fall back to `QIcon.fromTheme("applications-system")` rendered at
96 px, and on further failure simply hide the image label. The
heading and hints must continue to render.

## Files touched

- **New: `src/ui/empty_state.py`** — `class EmptyState(QWidget)`. Builds
  the layout described above. Constructor takes a `version: str` and an
  optional `logo_path: Path`. No signals or slots — fully static.
- **Edit: `src/ui/main_window.py`** — replace `_make_empty_placeholder`
  (currently `src/ui/main_window.py:421`) with
  `EmptyState(version=__version__, logo_path=...)`. No other call sites
  change; the three references at `:113`, `:316`, `:526` continue to
  work because `EmptyState` is a `QWidget`.

## Edge cases

- **Tiny windows.** With `setWordWrap(True)` and stretches on both
  vertical and horizontal axes, the layout collapses gracefully. If the
  pane gets narrower than the heading's natural width, the heading
  wraps; if shorter than the column's natural height, the top and
  bottom stretches absorb to zero and the content gets clipped — which
  is acceptable because the user controls window size and a too-small
  empty state is no worse than today's blank one.
- **QtSvg missing.** PySide6 ships QtSvg as a separate but always-bundled
  module (`PySide6.QtSvg`, `PySide6.QtSvgWidgets`). Importing it is safe
  on any supported wheel. The fallback path above handles the unlikely
  failure.
- **Very long version strings.** `__version__` is `"0.1.0"` today
  (`src/__init__.py:1`). If it grows (`"0.1.0+dev.abc1234"`), word-wrap
  on the subhead handles it. No truncation.
- **Theme change at runtime.** Preferences applies a new palette via
  `apply_theme` (`src/ui/main_window.py:276`). Qt repaints all widgets
  using palette roles automatically — `EmptyState` needs no explicit
  reaction unless it caches palette-derived colors. Don't cache them.

## Tests

New file `tests/test_empty_state.py`, following the `qapp` fixture
pattern at `tests/test_preferences_dialog.py:24`.

- `test_empty_state_renders_without_logo(qapp)` — construct
  `EmptyState(version="9.9.9", logo_path=Path("/does/not/exist"))`,
  assert the widget builds, the heading label text is `"ccwork"`, and
  the version label contains `"9.9.9"`.
- `test_empty_state_shown_at_startup(qapp, tmp_path, monkeypatch)` —
  build a `MainWindow` against an empty repo store, assert
  `main_window._stack.currentWidget() is main_window._empty_placeholder`
  and `isinstance(main_window._empty_placeholder, EmptyState)`.
- `test_empty_state_hint_count` — assert the widget exposes its hint
  labels (e.g. via an `_hints: list[QLabel]` attribute) so future
  contributors can add a hint without breaking the test, and the
  initial count matches the three shipped lines.

Skip a test for "Ctrl+O hint click triggers add" until the hints are
buttons. The current spec keeps them as plain text — clickable hints
are a follow-up.

## Out of scope

- Animation (fade-in, logo bounce, typewriter heading).
- Dynamic per-state content (separate cold-start vs terminal-exited
  variants).
- "Recent repos" or "recently closed" list.
- News, changelog, or "what's new in v0.x" panel.
- Clickable hint buttons — the first cut is read-only text. Promote to
  buttons in a follow-up if telemetry (or user feedback) shows the
  hints are being ignored.
