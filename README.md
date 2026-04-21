# ccwork

Claude Code in zellij — persistent sessions, desktop notifications, and automatic conversation resume.

## What it does

- **One command to get back in** — `ccwork` attaches to your session or creates it. Detach with `Ctrl+o` `d` and come back later; all your tabs are where you left them.
- **Conversations resume automatically** — `claude` picks up the last conversation for the current project. Hint appears when one exists.
- **Desktop notifications** — a popup appears when Claude finishes or needs input. Silent outside zellij.
- **Auto-named tabs** — tabs rename to the current directory.

## Install

**macOS / Linux — one line:**

```bash
curl -fsSL https://raw.githubusercontent.com/kleer001/ccwork/main/install.sh | bash
```

Or clone and run manually:

```bash
git clone https://github.com/kleer001/ccwork
cd ccwork
./install.sh --dry-run   # preview all changes
./install.sh             # apply
source ~/.bashrc
```

Full details and manual setup: [docs/setup.md](docs/setup.md).

## Try it

```bash
ccwork          # attach or create the session
cd my-repo
claude          # start or resume Claude Code
```

Detach with `Ctrl+o` `d`. Run `ccwork` again later. Everything is still there.

## Why not the others?

| | **ccwork** | [CCManager](https://github.com/kbwo/ccmanager) | [Agent of Empires](https://github.com/njbrake/agent-of-empires) | [agent-session-manager](https://github.com/izll/agent-session-manager) | [Agent Deck](https://github.com/asheshgoplani/agent-deck) |
|---|---|---|---|---|---|
| **No build step** | ✅ bash | ⚠️ npm install | ❌ cargo build | ❌ go build | ❌ go build |
| **Claude session resume works on install** | ✅ | ⚠️ manual config required | ❌ [open bug #343](https://github.com/njbrake/agent-of-empires/issues/343) | ✅ claimed | ✅ |
| **tmux not required** | ✅ zellij | ✅ | ❌ required | ❌ required | ❌ required |
| **No background daemon** | ✅ | ✅ | ✅ | ✅ | ❌ `notify-daemon` |
| **Terminal intact after re-attach** | ✅ | ❌ [#293 ghost rows + blank viewport](https://github.com/kbwo/ccmanager/issues/293) | ✅ | ✅ | ❌ [#708 mouse input broken](https://github.com/asheshgoplani/agent-deck/issues/708) |
| **Bad config causes visible error** | ✅ | ✅ | ❌ [#595 silently reverts to defaults](https://github.com/njbrake/agent-of-empires/issues/595) | ✅ | ✅ |
| **Running tests won't destroy live sessions** | ✅ | ✅ | ✅ | ✅ | ❌ [#676 confirmed](https://github.com/asheshgoplani/agent-deck/issues/676) |

## Key bindings

| Action | Keys |
|---|---|
| New tab | `Ctrl+t` → `n` |
| Switch tabs | `Ctrl+t` → `←` / `→` |
| Rename tab | `Ctrl+t` → `r` |
| Close tab | `Ctrl+t` → `x` |
| Detach (keep session running) | `Ctrl+o` → `d` |
| Lock mode (pass keys to app) | `Ctrl+g` — toggle |
