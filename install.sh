#!/usr/bin/env bash
# ccwork installer — installs, uninstalls, or dry-runs the GUI setup.
#
# Usage:
#   ./install.sh              — install
#   ./install.sh --uninstall  — remove all ccwork changes
#   ./install.sh --dry-run    — show what would change, touch nothing

set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BASHRC="${HOME}/.bashrc"
CLAUDE_SETTINGS="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}/settings.json"
STATE_DIR="${HOME}/.local/share/ccwork"
BACKUP_DIR="${STATE_DIR}/backups"
LOG="${STATE_DIR}/install.log"
DESKTOP_FILE="${HOME}/.local/share/applications/ccwork.desktop"
CCWORK_LAUNCHER="${SCRIPT_DIR}/bin/ccwork"
HOOK_SINK="${SCRIPT_DIR}/bin/ccwork-hook-sink"
# Marker written into hook commands so uninstall can find + strip them.
HOOK_MARKER="ccwork-hook-sink"

DRY_RUN=false
UNINSTALL=false
for arg in "$@"; do
    case "$arg" in
        --dry-run)   DRY_RUN=true ;;
        --uninstall) UNINSTALL=true ;;
        *) echo "Unknown argument: $arg"; echo "Usage: $0 [--dry-run|--uninstall]"; exit 1 ;;
    esac
done

# STATE_DIR must exist before any logging (needed by both install and uninstall)
$DRY_RUN || mkdir -p "$STATE_DIR"

# ── Output helpers ───────────────────────────────────────────────────────────

green='\033[0;32m'; yellow='\033[1;33m'; blue='\033[0;34m'; red='\033[0;31m'; bold='\033[1m'; nc='\033[0m'

log() {
    local msg="$1"
    echo -e "$msg"
    $DRY_RUN || printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$(echo -e "$msg" | sed 's/\x1b\[[0-9;]*m//g')" >> "$LOG"
}

ok()      { log "${green}✓${nc} $1"; }
skip()    { log "${yellow}–${nc} $1"; }
info()    { log "${blue}  →${nc} $1"; }
dryrun()  { log "${blue}[dry run]${nc} $1"; }
fail()    { log "${red}✗${nc} $1"; exit 1; }
section() { echo -e "\n${bold}$1${nc}"; }

backup() {
    local file="$1"
    [ -f "$file" ] || return 0
    local dest="${BACKUP_DIR}/$(basename "$file").$(date '+%Y%m%d_%H%M%S').bak"
    if $DRY_RUN; then
        dryrun "Would back up $file → $dest"
    else
        mkdir -p "$BACKUP_DIR"
        cp "$file" "$dest"
        info "Backed up $file → $dest"
    fi
}

# ── Uninstall ────────────────────────────────────────────────────────────────

if $UNINSTALL; then
    section "Uninstalling ccwork"

    # bashrc — remove the marked block
    if grep -q "# BEGIN ccwork" "$BASHRC" 2>/dev/null; then
        if $DRY_RUN; then
            dryrun "Would remove ccwork block from $BASHRC"
        else
            backup "$BASHRC"
            sed -i '/# BEGIN ccwork/,/# END ccwork/d' "$BASHRC"
            ok "Removed ccwork block from $BASHRC"
        fi
    else
        skip "No ccwork block found in $BASHRC"
    fi

    # claude settings — remove Stop and Notification hooks we added
    if [ -f "$CLAUDE_SETTINGS" ]; then
        if $DRY_RUN; then
            dryrun "Would remove ccwork hooks from $CLAUDE_SETTINGS"
        else
            backup "$CLAUDE_SETTINGS"
            python3 - "$CLAUDE_SETTINGS" "$HOOK_MARKER" << 'PYEOF'
import json, sys
path, marker = sys.argv[1], sys.argv[2]
try:
    settings = json.load(open(path))
except json.JSONDecodeError as e:
    print(f"error: {path} contains invalid JSON: {e}", file=sys.stderr)
    sys.exit(1)
hooks = settings.get("hooks", {})
for event in list(hooks.keys()):
    hooks[event] = [
        h for h in hooks[event]
        if not any(marker in str(c) for c in h.get("hooks", []))
    ]
    if not hooks[event]:
        del hooks[event]
if not hooks:
    settings.pop("hooks", None)
with open(path, "w") as f:
    json.dump(settings, f, indent=2)
PYEOF
            ok "Removed ccwork hooks from $CLAUDE_SETTINGS"
        fi
    else
        skip "$CLAUDE_SETTINGS not found"
    fi

    # Legacy: an older ccwork used tmux automatic-rename line in tmux.conf.
    # Strip it if present so upgrades from the tmux era clean up fully.
    _TMUX_CONFIG="${XDG_CONFIG_HOME:-${HOME}/.config}/tmux/tmux.conf"
    if grep -q '# ccwork' "$_TMUX_CONFIG" 2>/dev/null; then
        if $DRY_RUN; then
            dryrun "Would remove legacy tmux line from $_TMUX_CONFIG"
        else
            backup "$_TMUX_CONFIG"
            sed -i '/# ccwork/d' "$_TMUX_CONFIG"
            ok "Removed legacy tmux line from $_TMUX_CONFIG"
        fi
    fi

    # Desktop file
    if [ -f "$DESKTOP_FILE" ]; then
        if $DRY_RUN; then
            dryrun "Would remove $DESKTOP_FILE"
        else
            rm -f "$DESKTOP_FILE"
            ok "Removed $DESKTOP_FILE"
        fi
    fi

    echo ""
    $DRY_RUN && echo "Dry run complete — nothing changed." || echo "Done. Run: source ~/.bashrc"
    exit 0
fi

# ── Install ──────────────────────────────────────────────────────────────────

$DRY_RUN && echo -e "\n${blue}Dry run — no files will be modified.${nc}"
log "$(date '+%Y-%m-%d %H:%M:%S')  ccwork install started (dry_run=$DRY_RUN)"

# ── Prerequisites ─────────────────────────────────────────────────────────────

section "Checking prerequisites"
# Hard deps for installation itself.
command -v python3 &>/dev/null || fail "python3 not found"
command -v git     &>/dev/null || fail "git not found"
# Runtime deps: needed to actually launch the GUI. We warn and continue so
# the user can apt-install them later without re-running us.
_warn=""
command -v xterm &>/dev/null || _warn="$_warn xterm"
command -v socat &>/dev/null || command -v nc &>/dev/null || _warn="$_warn socat_or_nc"
command -v notify-send &>/dev/null || _warn="$_warn notify-send"
if [ -n "$_warn" ]; then
    skip "Runtime deps missing:$_warn — install before launching ccwork (e.g. sudo apt install xterm socat libnotify-bin)"
else
    ok "python3, git, xterm, socat/nc, notify-send present"
fi

# ── 1. Create bin/ccwork launcher ────────────────────────────────────────────

section "1/4  ccwork launcher — $CCWORK_LAUNCHER"
info "Launches the Qt GUI via the repo's .venv if present, else system python"

LAUNCHER_BODY=$(cat << EOF
#!/usr/bin/env bash
# ccwork — launch the Qt GUI. Uses the repo's .venv/bin/python if present so
# PySide6 stays isolated; otherwise falls back to \`python3\`.
set -eu
_root="$SCRIPT_DIR"
if [ -x "\$_root/.venv/bin/python" ]; then
    _py="\$_root/.venv/bin/python"
else
    _py=python3
fi
exec "\$_py" -m src.main "\$@"
EOF
)
# Prepend the cd so python -m src.main finds the package root.
LAUNCHER_BODY=$(printf '%s\n' "$LAUNCHER_BODY" | sed '/^exec "\$_py"/i cd "$_root"')

if $DRY_RUN; then
    dryrun "Would write $CCWORK_LAUNCHER"
else
    printf '%s\n' "$LAUNCHER_BODY" > "$CCWORK_LAUNCHER"
    chmod +x "$CCWORK_LAUNCHER"
    ok "Wrote $CCWORK_LAUNCHER"
fi

# ── 2. Shell config ──────────────────────────────────────────────────────────

section "2/4  Shell config — $BASHRC"
info "Prepends $SCRIPT_DIR/bin to PATH so ccwork + the claude wrapper are found first"

HOOK_BLOCK=$(sed "s|__CCWORK_BIN__|$SCRIPT_DIR/bin|" << 'EOF'

# BEGIN ccwork
export PATH="__CCWORK_BIN__:$PATH"
# END ccwork
EOF
)

if grep -q "# BEGIN ccwork" "$BASHRC" 2>/dev/null; then
    # A stale block (tmux / zellij era) contains aliases + hook fns.
    # The new block is just an export PATH. Anything else → stale.
    _block=$(sed -n '/# BEGIN ccwork/,/# END ccwork/p' "$BASHRC")
    if printf '%s' "$_block" | grep -Eq 'tmux|zellij|_ccwork_|alias ccwork|PROMPT_COMMAND'; then
        if $DRY_RUN; then
            dryrun "Would replace stale ccwork block in $BASHRC"
        else
            backup "$BASHRC"
            sed -i '/# BEGIN ccwork/,/# END ccwork/d' "$BASHRC"
            printf '%s\n' "$HOOK_BLOCK" >> "$BASHRC"
            ok "Replaced stale ccwork block in $BASHRC"
        fi
    elif ! printf '%s' "$_block" | grep -Fq "$SCRIPT_DIR/bin"; then
        if $DRY_RUN; then
            dryrun "Would replace ccwork block (wrong path) in $BASHRC"
        else
            backup "$BASHRC"
            sed -i '/# BEGIN ccwork/,/# END ccwork/d' "$BASHRC"
            printf '%s\n' "$HOOK_BLOCK" >> "$BASHRC"
            ok "Replaced ccwork block (path mismatch) in $BASHRC"
        fi
    else
        skip "ccwork block already up to date"
    fi
else
    if $DRY_RUN; then
        dryrun "Would append to $BASHRC:"
        echo "$HOOK_BLOCK" | sed 's/^/    /'
    else
        backup "$BASHRC"
        printf '%s\n' "$HOOK_BLOCK" >> "$BASHRC"
        ok "Added ccwork block to $BASHRC"
    fi
fi

# ── 3. Claude Code hooks ──────────────────────────────────────────────────────

section "3/4  Claude Code hooks — $CLAUDE_SETTINGS"
info "Adds Stop and Notification hooks that pipe the payload to ccwork-hook-sink"
info "Appends to existing hook lists — does not overwrite user hooks"

if $DRY_RUN; then
    dryrun "Would merge Stop and Notification hooks into $CLAUDE_SETTINGS"
else
    hooks_result=$(python3 - "$CLAUDE_SETTINGS" "$HOOK_SINK" "$HOOK_MARKER" << 'PYEOF'
import json, sys, os

path, sink, marker = sys.argv[1], sys.argv[2], sys.argv[3]
# Any previously-installed ccwork hooks get stripped so we don't run
# duplicates after an upgrade. We match by (a) the current marker (our
# sink path) OR (b) legacy markers from the tmux/zellij era.
LEGACY_MARKERS = ("ccwork-spinner", marker)

if os.path.exists(path):
    try:
        settings = json.load(open(path))
    except json.JSONDecodeError as e:
        print(f"error: {path} contains invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)
else:
    settings = {}
hooks = settings.setdefault("hooks", {})

# Strip any prior ccwork hooks (legacy + previous-version) so we cleanly
# install the current definition. Leave unrelated hooks alone.
removed_any = False
for event in list(hooks.keys()):
    filtered = []
    for h in hooks[event]:
        hs = h.get("hooks", [])
        if any(any(m in str(c) for m in LEGACY_MARKERS) for c in hs):
            removed_any = True
            continue
        filtered.append(h)
    if filtered:
        hooks[event] = filtered
    else:
        del hooks[event]

def cmd(event: str) -> str:
    return f"CCWORK_EVENT={event} {sink}"

new_hooks = {
    "Stop":         [{"matcher": "*", "hooks": [{"type": "command", "command": cmd("Stop")}]}],
    "Notification": [{"matcher": "*", "hooks": [{"type": "command", "command": cmd("Notification")}]}],
}

for event, hook_list in new_hooks.items():
    hooks.setdefault(event, []).extend(hook_list)

os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
with open(path, "w") as f:
    json.dump(settings, f, indent=2)

print("replaced" if removed_any else "added")
PYEOF
)
    case "$hooks_result" in
        replaced) ok "Replaced stale hooks and installed Stop/Notification" ;;
        added)    ok "Installed Stop and Notification hooks" ;;
        *)        ok "Updated $CLAUDE_SETTINGS ($hooks_result)" ;;
    esac
fi

# ── 4. Desktop file ───────────────────────────────────────────────────────────

section "4/4  Desktop entry — $DESKTOP_FILE"
info "Adds a launcher entry so ccwork appears in your app menu"

DESKTOP_BODY=$(cat << EOF
[Desktop Entry]
Type=Application
Name=ccwork
Comment=Claude Code GUI
Exec=$CCWORK_LAUNCHER
Icon=utilities-terminal
Terminal=false
Categories=Development;
EOF
)

if $DRY_RUN; then
    dryrun "Would write $DESKTOP_FILE"
else
    mkdir -p "$(dirname "$DESKTOP_FILE")"
    printf '%s\n' "$DESKTOP_BODY" > "$DESKTOP_FILE"
    ok "Wrote $DESKTOP_FILE"
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
if $DRY_RUN; then
    echo "Dry run complete — nothing was changed."
    echo "Re-run without --dry-run to apply."
else
    log "Install complete"
    echo -e "Log: ${STATE_DIR}/install.log"
    echo -e "Backups: ${BACKUP_DIR}/"
    echo ""
    echo "Next:"
    echo "  source ~/.bashrc          # pick up PATH change"
    echo "  pip install -r requirements.txt  # install PySide6 (use a venv)"
    echo "  ccwork                    # launch the GUI"
    echo ""
    echo "Undo: ./install.sh --uninstall"
fi
