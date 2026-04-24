#!/usr/bin/env bash
# ccwork bootstrap — clone, venv, install. Safe to re-run.
#
# One-liner:
#   bash -c "$(curl -sSfL https://raw.githubusercontent.com/kleer001/ccwork/main/bootstrap.sh)"
#
# Pass flags (see --help for the list):
#   bash -c "$(curl -sSfL .../bootstrap.sh)" -- --dry-run
#   curl -sSfL .../bootstrap.sh | bash -s -- --dry-run
#
# The whole body is wrapped in _main() and called at EOF so a truncated
# curl stream can't execute a partial payload. set -euo pipefail bails
# early on any failure.

set -euo pipefail

# Global because _main() calls it; defined at script scope for clarity.
_print_help() {
    cat <<'__HELP__'
ccwork bootstrap — clone, venv, install. Safe to re-run.

Usage:
    bash -c "$(curl -sSfL https://raw.githubusercontent.com/kleer001/ccwork/main/bootstrap.sh)"
    bash -c "$(curl -sSfL .../bootstrap.sh)" -- [FLAGS]
    curl -sSfL .../bootstrap.sh | bash -s -- [FLAGS]

Flags:
    -h, --help       Show this help and exit.
        --dry-run    Preflight + print what would happen; change nothing.
    -y, --yes        Skip the 3-second abort countdown (for CI / scripted use).
        --uninstall  Run install.sh --uninstall against the existing clone
                     at $CCWORK_DEST, then exit.

Environment:
    CCWORK_REPO_URL   Repo to clone from.
                      Default: https://github.com/kleer001/ccwork
    CCWORK_DEST       Where to clone to.
                      Default: $HOME/ccwork
    CCWORK_BRANCH     Branch to check out.
                      Default: remote HEAD

Behavior:
    Writes only under $HOME; no sudo required.
    Missing system packages (xterm, socat) produce warnings, not errors.
    Existing clone is fast-forwarded; existing venv is reused.
    Events are logged to ~/.local/share/ccwork/bootstrap.log.
__HELP__
}

_main() {
    local repo_url="${CCWORK_REPO_URL:-https://github.com/kleer001/ccwork}"
    local dest="${CCWORK_DEST:-$HOME/ccwork}"
    local branch="${CCWORK_BRANCH:-}"
    local dry_run=false
    local skip_countdown=false
    local do_uninstall=false

    # ── Arg parsing ──────────────────────────────────────────────
    for arg in "$@"; do
        case "$arg" in
            -h|--help)      _print_help; return 0 ;;
            --dry-run)      dry_run=true ;;
            -y|--yes)       skip_countdown=true ;;
            --uninstall)    do_uninstall=true ;;
            *)
                printf 'ccwork-bootstrap: unknown arg: %s\n' "$arg" >&2
                printf 'ccwork-bootstrap: see --help for usage.\n' >&2
                return 2
                ;;
        esac
    done

    # ── Logging setup ────────────────────────────────────────────
    # Log file is an append-only running history of every bootstrap run.
    # Skip creation in --dry-run so an abort really leaves zero footprint.
    local log=""
    if ! $dry_run; then
        local log_dir="${HOME}/.local/share/ccwork"
        mkdir -p "$log_dir"
        log="${log_dir}/bootstrap.log"
        printf '\n===== %s %s =====\n' "$(date '+%Y-%m-%d %H:%M:%S')" "bootstrap start" >> "$log"
    fi

    _say() {
        printf 'ccwork-bootstrap: %s\n' "$*"
        [ -n "$log" ] && printf '%s %s\n' "$(date '+%H:%M:%S')" "$*" >> "$log"
        return 0
    }
    _fail() {
        printf 'ccwork-bootstrap: ERROR: %s\n' "$*" >&2
        [ -n "$log" ] && printf '%s ERROR: %s\n' "$(date '+%H:%M:%S')" "$*" >> "$log"
        exit 1
    }

    # ── Uninstall shortcut ───────────────────────────────────────
    if $do_uninstall; then
        if [ -x "$dest/install.sh" ]; then
            _say "running $dest/install.sh --uninstall"
            (cd "$dest" && bash install.sh --uninstall)
            _say "uninstall complete. The clone at $dest remains — remove manually if done."
            return 0
        else
            _fail "no install.sh at $dest — either ccwork isn't installed, or CCWORK_DEST is wrong."
        fi
    fi

    # ── Preflight ────────────────────────────────────────────────
    command -v git     >/dev/null 2>&1 || _fail "git not found. Try: sudo apt install git"
    command -v python3 >/dev/null 2>&1 || _fail "python3 not found. Try: sudo apt install python3 python3-venv"

    # PySide6 >= 6.6 requires Python 3.9+. Check up-front — a pip error
    # three minutes into the install is a bad first impression.
    if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
        _fail "Python 3.9+ required; got $(python3 -V 2>&1). Install a newer python3 and retry."
    fi

    # python3-venv is a separate Debian package; surface the specific
    # missing-module error instead of letting 'python3 -m venv' fail
    # cryptically later.
    if ! python3 -m venv --help >/dev/null 2>&1; then
        _fail "python3-venv missing. Try: sudo apt install python3-venv"
    fi

    local runtime_missing=""
    command -v xterm >/dev/null 2>&1 || runtime_missing+=" xterm"
    if ! command -v socat >/dev/null 2>&1 && ! command -v nc >/dev/null 2>&1; then
        runtime_missing+=" socat"
    fi
    if [ -n "$runtime_missing" ]; then
        _say "note: runtime deps missing —${runtime_missing}. Install before launching: sudo apt install${runtime_missing}"
    fi

    # ── Plan summary + abort window ──────────────────────────────
    echo
    _say "About to:"
    _say "  clone   $repo_url${branch:+ (branch $branch)} → $dest"
    _say "  venv    $dest/.venv (create if missing)"
    _say "  deps    pip install -r $dest/requirements.txt"
    _say "  wire    $dest/install.sh (PATH, hooks, .desktop launcher)"
    echo

    if $dry_run; then
        _say "dry-run: nothing changed. Re-run without --dry-run to apply."
        return 0
    fi
    if ! $skip_countdown; then
        _say "Press Ctrl-C within 3 seconds to abort."
        sleep 3
        echo
    fi

    # ── Clone / update ───────────────────────────────────────────
    if [ -d "$dest/.git" ]; then
        _say "updating existing clone at $dest"
        git -C "$dest" fetch --prune origin
        if [ -n "$branch" ]; then
            git -C "$dest" checkout "$branch"
        fi
        local cur
        cur=$(git -C "$dest" symbolic-ref --short HEAD 2>/dev/null || echo "")
        if [ -n "$cur" ]; then
            git -C "$dest" pull --ff-only origin "$cur"
        fi
    elif [ -e "$dest" ]; then
        _fail "$dest exists but is not a git clone. Move it aside or set CCWORK_DEST=<other/path>."
    else
        _say "cloning $repo_url → $dest"
        if [ -n "$branch" ]; then
            git clone --branch "$branch" "$repo_url" "$dest"
        else
            git clone "$repo_url" "$dest"
        fi
    fi

    # ── Virtualenv + pip ─────────────────────────────────────────
    if [ ! -x "$dest/.venv/bin/python" ]; then
        _say "creating venv at $dest/.venv"
        python3 -m venv "$dest/.venv"
    else
        _say "reusing existing venv at $dest/.venv"
    fi
    _say "installing Python dependencies"
    "$dest/.venv/bin/python" -m pip install --upgrade pip >/dev/null
    "$dest/.venv/bin/pip" install -r "$dest/requirements.txt"

    # ── Shell + hook wiring ──────────────────────────────────────
    _say "running install.sh"
    (cd "$dest" && bash install.sh)

    # ── Post-install sanity check ────────────────────────────────
    # Import both PySide6 (confirms the wheel + system libs landed) and
    # src.main (confirms the repo layout is intact and PYTHONPATH works).
    # Either failure here usually means the install silently ate an error.
    _say "verifying install"
    if ! "$dest/.venv/bin/python" -c 'import PySide6' 2>/dev/null; then
        _fail "sanity check failed: the venv can't import PySide6. Check $log for details."
    fi
    if ! (cd "$dest" && "$dest/.venv/bin/python" -c 'import src.main') 2>/dev/null; then
        _fail "sanity check failed: python can't import src.main from $dest. Check $log for details."
    fi
    _say "verified: PySide6 + src.main import cleanly"

    # ── Shell-rc hint ────────────────────────────────────────────
    # install.sh only appends to .bashrc. Non-bash users need to add the
    # export themselves — surface that instead of letting `ccwork: command
    # not found` be their next experience.
    case "${SHELL:-}" in
        *zsh|*fish)
            local rc_hint_shell="${SHELL##*/}"
            local rc_hint_file
            case "$rc_hint_shell" in
                zsh)  rc_hint_file="~/.zshrc" ;;
                fish) rc_hint_file="~/.config/fish/config.fish" ;;
                *)    rc_hint_file="your shell rc" ;;
            esac
            echo
            _say "note: install.sh only edits ~/.bashrc, but your shell looks like $rc_hint_shell."
            _say "      Add this line to $rc_hint_file:"
            if [ "$rc_hint_shell" = "fish" ]; then
                _say "        fish_add_path $dest/bin"
            else
                _say "        export PATH=\"$dest/bin:\$PATH\""
            fi
            ;;
    esac

    # ── Finish ───────────────────────────────────────────────────
    echo
    _say "Done. Next steps:"
    _say "  source ~/.bashrc    # pick up the PATH change (bash)"
    _say "  ccwork              # launch"
    echo
    _say "To undo:"
    _say "  bash -c \"\$(curl -sSfL https://raw.githubusercontent.com/kleer001/ccwork/main/bootstrap.sh)\" -- --uninstall"
    [ -n "$log" ] && _say "Log:   $log"
}

_main "$@"
