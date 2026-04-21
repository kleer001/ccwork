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

| Tool | What it promises | What it actually is |
|---|---|---|
| **ccwork** | persistent Claude sessions | a wrapper script and an alias |
| [CCManager](https://github.com/kbwo/ccmanager) | "manages" 8+ agent types | a TUI app you have to learn |
| [Agent of Empires](https://github.com/njbrake/agent-of-empires) | multi-agent orchestration | tmux + git worktrees + a web dashboard + Docker + mobile access |
| [agent-session-manager](https://github.com/izll/agent-session-manager) | live session preview | Go + Bubble Tea + tmux, compiled binary required |
| [Agent Deck](https://github.com/asheshgoplani/agent-deck) | "real-time agent monitoring" | another TUI you didn't ask for |
| [Canopy](https://github.com/The-Banana-Standard/canopy) | workspace organization | a whole desktop app (Tauri) |

If you need to monitor 12 agents across 3 clouds from a mobile dashboard, there's a tool for that. If you just want `claude` to still be there when you come back, use ccwork.

## Key bindings

| Action | Keys |
|---|---|
| New tab | `Ctrl+t` → `n` |
| Switch tabs | `Ctrl+t` → `←` / `→` |
| Rename tab | `Ctrl+t` → `r` |
| Close tab | `Ctrl+t` → `x` |
| Detach (keep session running) | `Ctrl+o` → `d` |
| Lock mode (pass keys to app) | `Ctrl+g` — toggle |
