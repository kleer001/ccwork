#!/usr/bin/env bash
# ccwork installer — installs, uninstalls, or dry-runs ccwork setup.
#
# Usage:
#   ./install.sh              — install
#   ./install.sh --uninstall  — remove all ccwork changes
#   ./install.sh --dry-run    — show what would change, touch nothing

set -euo pipefail

# ── Config ───────────────────────────────────────────────────────────────────

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BASHRC="${HOME}/.bashrc"
ZELLIJ_CONFIG="${XDG_CONFIG_HOME:-${HOME}/.config}/zellij/config.kdl"
CLAUDE_SETTINGS="${CLAUDE_CONFIG_DIR:-${HOME}/.claude}/settings.json"
STATE_DIR="${HOME}/.local/share/ccwork"
BACKUP_DIR="${STATE_DIR}/backups"
LOG="${STATE_DIR}/install.log"

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

    # zellij config — remove the line we added
    if grep -q '^post_command_discovery_hook.*// ccwork' "$ZELLIJ_CONFIG" 2>/dev/null; then
        if $DRY_RUN; then
            dryrun "Would remove post_command_discovery_hook from $ZELLIJ_CONFIG"
        else
            backup "$ZELLIJ_CONFIG"
            sed -i '\|^post_command_discovery_hook.*// ccwork|d' "$ZELLIJ_CONFIG"
            ok "Removed post_command_discovery_hook from $ZELLIJ_CONFIG"
        fi
    else
        skip "post_command_discovery_hook not present in $ZELLIJ_CONFIG"
    fi

    # claude settings — remove Stop and Notification hooks we added
    if [ -f "$CLAUDE_SETTINGS" ]; then
        if $DRY_RUN; then
            dryrun "Would remove ccwork hooks from $CLAUDE_SETTINGS"
        else
            backup "$CLAUDE_SETTINGS"
            python3 - "$CLAUDE_SETTINGS" << 'PYEOF'
import json, sys
path = sys.argv[1]
try:
    settings = json.load(open(path))
except json.JSONDecodeError as e:
    print(f"error: {path} contains invalid JSON: {e}", file=sys.stderr)
    sys.exit(1)
hooks = settings.get("hooks", {})
marker = "notify-send"
for event in ["Stop", "Notification"]:
    if event in hooks:
        hooks[event] = [
            h for h in hooks[event]
            if not any(marker in str(c) for c in h.get("hooks", []))
        ]
        if not hooks[event]:
            del hooks[event]
if not hooks:
    settings.pop("hooks", None)
json.dump(settings, open(path, "w"), indent=2)
PYEOF
            ok "Removed ccwork hooks from $CLAUDE_SETTINGS"
        fi
    else
        skip "$CLAUDE_SETTINGS not found"
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
command -v zellij      &>/dev/null || fail "zellij not found — https://zellij.dev"
command -v notify-send &>/dev/null || fail "notify-send not found:  sudo apt install libnotify-bin"
command -v python3     &>/dev/null || fail "python3 not found"
ok "zellij, notify-send, python3 present"

# ── 1. Shell config ──────────────────────────────────────────────────────────

section "1/3  Shell config — $BASHRC"
info "Will add PATH prepend, ccwork alias, tab-rename hook, resume hint"
info "Wrapped in # BEGIN ccwork / # END ccwork markers for clean uninstall"

if grep -q "# BEGIN ccwork" "$BASHRC" 2>/dev/null; then
    skip "ccwork block already present"
else
    # NOTE: sed uses | as delimiter — repo path must not contain |
    HOOK_BLOCK=$(sed "s|__CCWORK_BIN__|$SCRIPT_DIR/bin|" << 'EOF'

# BEGIN ccwork
export PATH="__CCWORK_BIN__:$PATH"

alias ccwork='zellij attach --create ccwork'

_zellij_tab_rename() {
    [ -n "$ZELLIJ" ] && zellij action rename-tab "$(basename "$PWD")"
}

_ccwork_hint() {
    [ -z "$ZELLIJ" ] && return
    [ "$PWD" = "$_ccwork_hint_dir" ] && return
    _ccwork_hint_dir="$PWD"
    local _project_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects/$(echo "$PWD" | sed 's|/|-|g')"
    ls "$_project_dir"/*.jsonl 2>/dev/null | grep -q . && echo "  Type 'claude' to resume previous session"
}

PROMPT_COMMAND="${PROMPT_COMMAND:+$PROMPT_COMMAND; }_zellij_tab_rename; _ccwork_hint"
# END ccwork
EOF
)
    if $DRY_RUN; then
        dryrun "Would append to $BASHRC:"
        echo "$HOOK_BLOCK" | sed 's/^/    /'
    else
        backup "$BASHRC"
        printf '%s\n' "$HOOK_BLOCK" >> "$BASHRC"
        ok "Added ccwork block to $BASHRC"
    fi
fi

# ── 2. Zellij resurrection ────────────────────────────────────────────────────

section "2/3  Zellij session resurrection — $ZELLIJ_CONFIG"
info "Will add: post_command_discovery_hook to drop into shell instead of re-running commands"

if grep -q '^post_command_discovery_hook.*// ccwork' "$ZELLIJ_CONFIG" 2>/dev/null; then
    skip "post_command_discovery_hook already active"
else
    LINE='post_command_discovery_hook "echo $SHELL" // ccwork'
    if $DRY_RUN; then
        dryrun "Would add to $ZELLIJ_CONFIG:  $LINE"
    else
        backup "$ZELLIJ_CONFIG"
        mkdir -p "$(dirname "$ZELLIJ_CONFIG")"
        if grep -q "post_command_discovery_hook" "$ZELLIJ_CONFIG" 2>/dev/null; then
            # uncomment the existing placeholder
            sed -i "s|.*post_command_discovery_hook.*|$LINE|" "$ZELLIJ_CONFIG"
        else
            printf '\n%s\n' "$LINE" >> "$ZELLIJ_CONFIG"
        fi
        ok "Configured post_command_discovery_hook"
    fi
fi

# ── 3. Claude Code hooks ──────────────────────────────────────────────────────

section "3/3  Claude Code hooks — $CLAUDE_SETTINGS"
info "Will add Stop and Notification hooks to send desktop notifications from within Zellij"
info "Existing hooks are preserved; only missing event types are added"

if $DRY_RUN; then
    dryrun "Would merge Stop and Notification hooks into $CLAUDE_SETTINGS"
else
    hooks_result=$(python3 - "$CLAUDE_SETTINGS" << 'PYEOF'
import json, sys, os

path = sys.argv[1]
if os.path.exists(path):
    try:
        settings = json.load(open(path))
    except json.JSONDecodeError as e:
        print(f"error: {path} contains invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)
else:
    settings = {}
hooks = settings.setdefault("hooks", {})

new_hooks = {
    "Stop": [{"matcher": "*", "hooks": [{"type": "command",
        "command": "if [ -n \"$ZELLIJ\" ]; then zellij action rename-tab \"✓ $(basename \"${CLAUDE_PROJECT_DIR:-$PWD}\")\"; notify-send -u critical \"Claude [$(basename \"${CLAUDE_PROJECT_DIR:-$PWD}\")]\" \"Task done\"; fi"}]}],
    "Notification": [{"matcher": "*", "hooks": [{"type": "command",
        "command": "if [ -n \"$ZELLIJ\" ]; then zellij action rename-tab \"● $(basename \"${CLAUDE_PROJECT_DIR:-$PWD}\")\"; notify-send -u critical \"Claude [$(basename \"${CLAUDE_PROJECT_DIR:-$PWD}\")]\" \"Needs your input\"; fi"}]}]
}

added = [e for e in new_hooks if e not in hooks]
for event in added:
    hooks[event] = new_hooks[event]

if added:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    json.dump(settings, open(path, "w"), indent=2)

print("added" if added else "skip")
PYEOF
)
    if [ "$hooks_result" = "skip" ]; then
        skip "Stop and Notification hooks already present"
    else
        ok "Merged Stop and Notification hooks"
    fi
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
    echo "Run:  source ~/.bashrc"
    echo "Undo: ./install.sh --uninstall"
fi
