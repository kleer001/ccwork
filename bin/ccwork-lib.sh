# ccwork-lib.sh — helpers shared by ccwork's bash scripts. Source it; do not run it.

CCWORK_SOCK="${XDG_RUNTIME_DIR:-$HOME/.cache}/ccwork/ccwork.sock"

# Escape a string for a JSON string literal: \, ", and the C0 controls that
# can appear in a path or a title (newline, CR, tab). Any other control
# char makes the line malformed, and the server drops it.
ccwork_json_escape() {
    local s=$1
    s=${s//\\/\\\\}          # \  → \\
    s=${s//\"/\\\"}          # "  → \"
    s=${s//$'\n'/\\n}        # LF → \n
    s=${s//$'\r'/\\r}        # CR → \r
    s=${s//$'\t'/\\t}        # TAB → \t
    printf '%s' "$s"
}

# Write one line to the ccwork socket. A short timeout keeps a dead GUI from
# stalling the caller. Returns non-zero when the line was not sent.
ccwork_send() {
    if command -v socat >/dev/null 2>&1; then
        printf '%s\n' "$1" | timeout 1 socat - "UNIX-CONNECT:$CCWORK_SOCK" >/dev/null
    elif command -v nc >/dev/null 2>&1; then
        # nc -UN: UNIX + don't wait for server close.
        printf '%s\n' "$1" | timeout 1 nc -UN "$CCWORK_SOCK" >/dev/null \
            || printf '%s\n' "$1" | timeout 1 nc -U "$CCWORK_SOCK" >/dev/null
    else
        return 1
    fi
}
