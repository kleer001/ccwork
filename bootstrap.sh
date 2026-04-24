#!/usr/bin/env bash
# ccwork bootstrap — clone, venv, install. Safe to re-run.
#
# One-liner:
#   bash -c "$(curl -sSfL https://raw.githubusercontent.com/kleer001/ccwork/main/bootstrap.sh)"
#
# Env overrides:
#   CCWORK_REPO_URL  (default: https://github.com/kleer001/ccwork)
#   CCWORK_DEST      (default: $HOME/ccwork)
#   CCWORK_BRANCH    (default: remote HEAD)
#
# The whole script is wrapped in _main() so a partial download (curl
# cutting mid-stream) can't execute a truncated payload — bash only calls
# _main after it's fully parsed the file. set -euo pipefail bails on any
# early failure.

set -euo pipefail

_main() {
    local repo_url="${CCWORK_REPO_URL:-https://github.com/kleer001/ccwork}"
    local dest="${CCWORK_DEST:-$HOME/ccwork}"
    local branch="${CCWORK_BRANCH:-}"

    _say()  { printf 'ccwork-bootstrap: %s\n' "$*"; }
    _fail() { printf 'ccwork-bootstrap: ERROR: %s\n' "$*" >&2; exit 1; }

    # ── Preflight ────────────────────────────────────────────────
    command -v git     >/dev/null 2>&1 || _fail "git not found. Try: sudo apt install git"
    command -v python3 >/dev/null 2>&1 || _fail "python3 not found. Try: sudo apt install python3 python3-venv"

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

    # ── Clone / update ───────────────────────────────────────────
    if [ -d "$dest/.git" ]; then
        _say "updating existing clone at $dest"
        git -C "$dest" fetch --prune origin
        if [ -n "$branch" ]; then
            git -C "$dest" checkout "$branch"
        fi
        # Fast-forward whatever branch we're on.
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

    # ── Finish ───────────────────────────────────────────────────
    echo
    _say "Done. Next steps:"
    _say "  source ~/.bashrc    # pick up the PATH change"
    _say "  ccwork              # launch"
    echo
    _say "To undo:   cd $dest && ./install.sh --uninstall"
}

_main "$@"
