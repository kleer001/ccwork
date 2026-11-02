# Worktree practices of coding-agent tools

## Answer

Most tools copy gitignored files with a pattern list. The list is `.worktreeinclude` (Claude Code, Codex app, CCManager, agent-deck, Worktrunk narrowing), `preservePatterns` (emdash), `Copy Files` (Vibe Kanban) or `gtr.copy.*` (gtr). Cursor and Conductor use a setup script that runs `cp`. Folder defaults vary: inside the repo (`.claude/worktrees/`), sibling (gtr, agent-deck, Worktrunk), or an app data directory (emdash, Codex, Cursor). Most tools let the user change the folder. The sources confirm almost no UI marker. Only Worktrunk's `wt list` gutter and CCManager's status labels are documented. Several tools are not confirmed on most points (Orca, Superset location, Nimbalyst, Claude Squad).

## Findings

### 1. Gitignored and setup files

**Pattern-file copy (declarative)**
- Claude Code: `.worktreeinclude` in the project root. It uses `.gitignore` syntax. A file is copied only if it matches AND is gitignored. It applies to `--worktree`, subagent worktrees and desktop parallel sessions. It is not processed when a `WorktreeCreate` hook replaces creation. https://code.claude.com/docs/en/worktrees
- Codex app: `.worktreeinclude` in the repo root. Codex copies only ignored files that match. It also copies an ignored `AGENTS.override.md`. It skips source symlinks and does not overwrite existing files. It applies only to local managed worktrees. https://learn.chatgpt.com/docs/environments/git-worktrees
- CCManager: `.worktreeinclude` (gitignore syntax) copies files that match and are gitignored. The copy runs before the post-creation hook. https://github.com/kbwo/ccmanager ; https://github.com/kbwo/ccmanager/pull/330
- agent-deck: `.env` and `.mcp.json` are NOT copied by default. `.worktreeinclude` opts in. Directories copy recursively. Existing files are not overwritten. https://github.com/asheshgoplani/agent-deck
- emdash: `.emdash.json` key `preservePatterns` (example `[".env", ".env.local"]`). It copies untracked or gitignored files once at creation, and only if absent (the "only if absent" detail comes from a search snippet). https://emdash.com/docs/project-config
- Vibe Kanban: the UI field "Copy Files" takes a comma-separated list. The copy runs after worktree creation and before the setup script. The docs say to gitignore these files. https://vibekanban.com/docs/core-features/creating-projects
- gtr: git config keys `gtr.copy.include`, `gtr.copy.exclude`, `gtr.copy.includeDirs`, `gtr.copy.excludeDirs`. The `.gtrconfig` file has a `[copy]` section with the same names. https://github.com/coderabbitai/git-worktree-runner/blob/main/docs/configuration.md
- Worktrunk: `wt step copy-ignored`, wired as `[post-start] copy = "wt step copy-ignored"` in `.config/wt.toml`. It copies all ignored files by default, with built-in excludes. It skips existing files unless `--force`. `.worktreeinclude` narrows the copy. Extra excludes go in `[step.copy-ignored] exclude`. https://worktrunk.dev/step/ ; https://worktrunk.dev/config/

**Script-based copy**
- Cursor: `.cursor/worktrees.json`. Keys are `setup-worktree-unix`, `setup-worktree-windows` and `setup-worktree`. Each takes a command array or a script path. The example is `cp $ROOT_WORKTREE_PATH/.env .env`. The docs do not say Cursor copies `.env` automatically. https://cursor.com/docs/configuration/worktrees
- Conductor: the setup script handles untracked items. A guide example copies `.env` from `$CONDUCTOR_ROOT_PATH` (search snippet only). https://docs.conductor.build/tips/scripts
- Superset: the setup script. Variables are `SUPERSET_ROOT_PATH`, `SUPERSET_WORKSPACE_NAME`, `SUPERSET_WORKSPACE_PATH`. The `.env` copy example comes from a third-party mirror. https://docs.paradev.com/setup-teardown-scripts ; https://www.mintlify.com/superset-sh/superset/guides/setup-teardown-scripts

**node_modules and .venv**

| Tool | Handling | Source |
|---|---|---|
| Worktrunk | Docs example: a `pre-start` hook symlinks `node_modules`. Reflink copy on APFS, btrfs, XFS and ReFS. Full copy on ext4 and NTFS. | https://worktrunk.dev/step/ |
| gtr | `gtr.copy.includeDirs` (for example `node_modules`, `.venv`). Uses `cp -r`. Symlink or CoW not confirmed. | https://github.com/coderabbitai/git-worktree-runner/blob/main/docs/configuration.md |
| Cursor | Docs advise against symlinking `node_modules`. They suggest `bun`, `pnpm` or `uv`. | https://cursor.com/docs/configuration/worktrees |
| Claude Code | No setup key. Docs say to ask Claude to install dependencies. | https://code.claude.com/docs/en/worktrees |
| Other tools | Not confirmed. | |

**Setup and teardown**

| Tool | Setup | Teardown | Source |
|---|---|---|---|
| Conductor | `.conductor/settings.toml` `scripts.setup`; legacy `conductor.json` `scripts.setup` | `scripts.archive` (runs before archive). No delete-time key seen. | https://www.conductor.build/docs/core/conductor-json |
| Superset | `.superset/config.json` `setup`; also `run` | `teardown`. "Delete Anyway" skips it. | https://docs.paradev.com/setup-teardown-scripts |
| Vibe Kanban | UI "Setup Scripts" (runs before the agent) | UI "Cleanup Scripts" (after an agent turn; see Conflicts) | https://vibekanban.com/docs/core-features/creating-projects |
| emdash | `.emdash.json` `scripts.setup`, `shellSetup`; a `prepare` script is mentioned | `scripts.teardown` | https://emdash.com/docs/project-config |
| CCManager | Post-creation hook (key name not confirmed). Env: worktree path, branch, git root. Async. | None documented | https://github.com/kbwo/ccmanager |
| agent-deck | `.agent-deck/worktree-setup.sh` (non-fatal). Env: `AGENT_DECK_REPO_ROOT`, `AGENT_DECK_WORKTREE_PATH`. | `.agent-deck/worktree-destruction.sh` (runs before removal; non-blocking). Consent in `~/.local/share/agent-deck/worktree-script-consent.json`. | https://github.com/asheshgoplani/agent-deck |
| Worktrunk | `.config/wt.toml` hooks `pre-start`, `post-start` | `pre-remove`, `post-remove` (examples not confirmed) | https://worktrunk.dev/hook/ |
| gtr | `gtr.hook.postCreate` or `.gtrconfig` `[hooks] postCreate` | `gtr.hook.preRemove` (aborts on failure; `--force` skips), `gtr.hook.postRemove`. `git gtr trust` approves hooks. | https://github.com/coderabbitai/git-worktree-runner/blob/main/docs/configuration.md |
| Cursor | `.cursor/worktrees.json` (see above) | Not documented. Cleanup settings: `cursor.worktreeCleanupIntervalHours`, `cursor.worktreeMaxCount` (default 25). | https://cursor.com/docs/configuration/worktrees |
| Codex app | Local environment setup scripts, stored in `.codex` in the project root. File name and keys not confirmed. | No script. Keeps the 15 most recent managed worktrees by default. A snapshot is saved before deletion. | https://learn.chatgpt.com/docs/environments/local-environment ; https://learn.chatgpt.com/docs/environments/git-worktrees |
| Claude Code (desktop and CLI) | No setup key. `WorktreeCreate` hook replaces creation. | No script. `WorktreeRemove` hook. Desktop removes local worktrees about 30 days after archive or last open. | https://code.claude.com/docs/en/worktrees ; https://code.claude.com/docs/en/desktop |
| Orca | Third-party only: a setup command saved per repo. CLI `orca worktree create --setup run\|skip\|inherit` (unverified). `orca.yaml` holds `environmentRecipes` (unverified). | not confirmed | https://medium.com/@techlatest.net/orca-tutorial-multi-agent-ai-coding-workspace-from-scratch-7a58b410497b ; https://supercode.sh/en/skills/stablyai/orca/orca-per-workspace-env |
| Claude Squad, Nimbalyst/Crystal | not confirmed | not confirmed | |

Config file names: Conductor `.conductor/settings.toml`; Superset `.superset/config.json` (plus `config.local.json`, user override `~/.superset/projects/<repo-path>/config.json`); emdash `.emdash.json`; Worktrunk `.config/wt.toml`; Cursor `.cursor/worktrees.json`; gtr `.gtrconfig`; CCManager `.ccmanager.json` (global `~/.config/ccmanager/config.json`); agent-deck `~/.config/agent-deck/config.toml`; Claude Squad `~/.claude-squad/config.json` (programs and profiles only).

### 2. Worktree folder location

| Tool | Default | Configurable | Source |
|---|---|---|---|
| Claude Code (CLI and desktop) | `<project-root>/.claude/worktrees/<name>/`, branch `worktree-<name>` | Desktop: Settings "Worktree location" (SSH: "Worktree folder"). Hooks can place it elsewhere. | https://code.claude.com/docs/en/worktrees ; https://code.claude.com/docs/en/desktop |
| Codex app | `$CODEX_HOME/worktrees` | Yes: Settings > Worktrees > "Worktree root" | https://learn.chatgpt.com/docs/environments/git-worktrees |
| Cursor | Not stated in the docs. A forum snippet says fixed `~/.cursor/worktrees` (unverified). | Forum snippet says no (unverified) | https://forum.cursor.com/t/configure-worktree-location/149222 |
| emdash | `~/emdash/worktrees` | Yes: per project, then machine default | https://emdash.com/docs/project-config |
| agent-deck | `sibling` (`repo-branch`), `subdirectory` (`repo/.worktrees/branch`) or a custom path (`<path>/<repo_name>/<branch>`). Which one is the default is not confirmed. | Yes: `[worktree] default_location`, `--location`, `path_template` | https://github.com/asheshgoplani/agent-deck |
| gtr | `<repo-name>-worktrees`, a sibling of the repo | Yes: `gtr.worktrees.dir`, `gtr.worktrees.prefix`, env `GTR_WORKTREES_DIR` | https://github.com/coderabbitai/git-worktree-runner/blob/main/docs/configuration.md |
| Worktrunk | Not stated on the official pages. A search snippet says sibling `../<repo>.<branch>` (unverified). | Yes: `worktree-path` template in user config, per-project overrides | https://worktrunk.dev/config/ ; https://docs.rs/crate/worktrunk/latest/source/docs/static/config.md |
| CCManager | A `{branch}` path template. Key name and default parent not confirmed. | Template, yes | https://github.com/kbwo/ccmanager |
| Claude Squad | Third-party DeepWiki says `~/.claude-squad/worktrees/` (unverified) | not confirmed | https://deepwiki.com/smtg-ai/claude-squad/4.3-git-worktree-management |
| Conductor, Superset, Orca, Vibe Kanban, Nimbalyst/Crystal | not confirmed | not confirmed | |

### 3. UI marker for worktree versus main checkout

- Worktrunk (`wt list`, a CLI list): gutter `@` current worktree, `^` primary worktree, `+` other worktree, `/` branch with no worktree, `|` remote-only branch. The status column has more symbols, such as `⊘` detached HEAD, `⚐` branch in multiple worktrees, and `_` or `⊂` for safe to remove. https://worktrunk.dev/list/
- CCManager: status labels Waiting, Busy and Idle. Project counts show as `[active/busy/waiting]`. It shows git stats per worktree. No worktree icon is described. https://github.com/kbwo/ccmanager
- Claude Code desktop: a Worktree toggle (default off) before the session starts. Without it the session runs in the project folder. Desktop prepends a branch prefix to every worktree branch. The session list groups by folder. No worktree icon or label is described in the part of the page that was read. https://code.claude.com/docs/en/desktop
- Conductor: the docs say the branch is the simplest way to tell workspaces apart. The sidebar shows a secondary directory name (sample "warsaw-v2"). Search snippet only. https://docs.conductor.build/tips/workspaces-and-branches
- Codex app: a "Worktree" choice under the composer. The chat header has Open, Hand off and Create branch here. Branch prefix `codex/`. Worktrees start in detached HEAD. No icon or label is described. https://learn.chatgpt.com/docs/environments/git-worktrees
- No documented dedicated worktree glyph, and no documented single-line "repo / branch" format, appears in the sources for any tool.
- Not confirmed: Superset, Orca, Vibe Kanban, emdash, Nimbalyst/Crystal, Claude Squad, agent-deck, gtr (main-checkout mark), Cursor.

## Conflicts

| Topic | Claim A | Claim B | More authoritative |
|---|---|---|---|
| Conductor config precedence | `.conductor/settings.toml` makes Conductor ignore `conductor.json` https://www.conductor.build/docs/core/conductor-json | In-app Repository Settings override `conductor.json`; file lookup order is workspace, remote default branch, repo root https://docs.conductor.build/tips/conductor-json | A. It was fetched from the official page. B is a search snippet. The two claims cover different layers, so they may not truly conflict. |
| Superset teardown order | Official page is silent https://docs.paradev.com/setup-teardown-scripts | Teardown runs before worktree removal, after terminals close https://www.mintlify.com/superset-sh/superset/guides/setup-teardown-scripts | The official page. It does not contradict B, so B is plausible but unverified (third-party mirror). |
| Vibe Kanban cleanup timing | After each agent turn https://vibekanban.com/docs/core-features/creating-projects | When a workspace closes (search snippet) https://vibekanban.com/docs/settings/projects-repositories | A. It was fetched from the official page. B is unverified. |
| agent-deck config path | `~/.config/agent-deck/config.toml` https://github.com/asheshgoplani/agent-deck | `~/.agent-deck/config.toml` (snippet, v1.9.42) https://pkg.go.dev/github.com/asheshgoplani/agent-deck@v1.9.42 | A. It is the project README. B is a snippet of an older version. |
| Cursor folder location | Docs silent https://cursor.com/docs/configuration/worktrees | Forum: fixed `~/.cursor/worktrees`, no setting https://forum.cursor.com/t/configure-worktree-location/149222 | Official docs outrank the forum. The docs do not answer, so B stays unverified. |

## Gaps

- Orca: no primary source was fetched. Config, keys, folder, UI marker and teardown are not confirmed. Pages not read: https://onorca.dev/docs/model/worktrees , https://onorca.dev/docs/settings , https://onorca.dev/docs/cli/reference
- Superset: folder location and UI marker. The `workspaces` and `cli/env-vars` pages were not read (https://docs.paradev.com/workspaces).
- Conductor: folder location, UI icon and color, delete-time teardown. Most Conductor claims come from search snippets.
- Nimbalyst/Crystal: setup, copy, location and UI. Crystal is deprecated in favor of Nimbalyst (https://github.com/stravu/crystal). The Nimbalyst worktrees page was seen only as a snippet.
- Vibe Kanban: folder, config file, UI marker. The README says the project is sunsetting (https://github.com/BloopAI/vibe-kanban).
- Claude Squad: folder (official), copy, setup, teardown, UI marker. Source code was not checked.
- Codex app: the `.codex` file name and setup keys. Cursor: teardown and UI marker.
- Claude Code desktop: about half of the desktop page was not read (205,062 characters total; 100,000 read).
- CCManager hook and path-template key names. agent-deck `path_template` syntax, default location and TUI marker. gtr list marker for the main checkout. Worktrunk default `worktree-path`.
- Dates: no official page shows a date, except emdash ("last updated October 17, 2026").
- Blocked URLs: none returned 403. The hosts docs.conductor.build, docs.superset.sh and docs.emdash.sh redirect (308); some of those redirects were not followed.

## Sources

- https://www.conductor.build/docs/core/conductor-json — Conductor docs, conductor.json and settings
- https://docs.conductor.build/tips/conductor-json — Conductor docs, lookup and precedence (snippet)
- https://docs.conductor.build/tips/scripts — Conductor docs, scripts and env vars (snippet)
- https://docs.conductor.build/tips/workspaces-and-branches — Conductor docs, workspaces and branches (snippet)
- https://docs.paradev.com/setup-teardown-scripts — Superset (Paradev) setup and teardown
- https://www.mintlify.com/superset-sh/superset/guides/setup-teardown-scripts — Superset docs mirror (third party)
- https://medium.com/@techlatest.net/orca-tutorial-multi-agent-ai-coding-workspace-from-scratch-7a58b410497b — Orca tutorial (third party)
- https://supercode.sh/en/skills/stablyai/orca/orca-per-workspace-env — Orca skill page (third party)
- https://github.com/stravu/crystal — Crystal README
- https://vibekanban.com/docs/core-features/creating-projects — Vibe Kanban, Creating Projects
- https://vibekanban.com/docs/settings/projects-repositories — Vibe Kanban settings (snippet)
- https://github.com/BloopAI/vibe-kanban — Vibe Kanban README
- https://emdash.com/docs/project-config — emdash project config
- https://github.com/smtg-ai/claude-squad — Claude Squad README
- https://deepwiki.com/smtg-ai/claude-squad/4.3-git-worktree-management — DeepWiki (third party)
- https://github.com/kbwo/ccmanager — CCManager README
- https://github.com/kbwo/ccmanager/pull/330 — CCManager PR, .worktreeinclude
- https://github.com/asheshgoplani/agent-deck — agent-deck README
- https://pkg.go.dev/github.com/asheshgoplani/agent-deck@v1.9.42 — agent-deck on pkg.go.dev (snippet)
- https://code.claude.com/docs/en/worktrees — Claude Code worktrees docs
- https://code.claude.com/docs/en/desktop — Claude Code desktop docs
- https://learn.chatgpt.com/docs/environments/git-worktrees — Codex worktrees
- https://learn.chatgpt.com/docs/environments/local-environment — Codex local environments
- https://cursor.com/docs/configuration/worktrees — Cursor worktrees docs
- https://forum.cursor.com/t/configure-worktree-location/149222 — Cursor forum, location (snippet)
- https://worktrunk.dev/config/ , https://worktrunk.dev/step/ , https://worktrunk.dev/hook/ , https://worktrunk.dev/list/ — Worktrunk docs
- https://docs.rs/crate/worktrunk/latest/source/docs/static/config.md — Worktrunk config source (snippet)
- https://github.com/coderabbitai/git-worktree-runner — gtr README
- https://github.com/coderabbitai/git-worktree-runner/blob/main/docs/configuration.md — gtr configuration

## Summary table

| tool | copy mechanism (file/key) | setup / teardown (file/keys) | folder location (default; configurable?) | UI marker |
|---|---|---|---|---|
| Conductor | Setup script copies `.env` from `$CONDUCTOR_ROOT_PATH` (snippet); no copy key | `.conductor/settings.toml` or `conductor.json`: `scripts.setup`, `scripts.run`, `scripts.archive` | not confirmed | Branch name; secondary directory name (sample "warsaw-v2") (snippet) |
| Superset/Paradev | Setup script (`.env` example from mirror); no copy key | `.superset/config.json`: `setup`, `teardown`, `run` | not confirmed | not confirmed |
| Orca | not confirmed | Setup command per repo (third party); `--setup` flag unverified; teardown not confirmed | not confirmed | not confirmed |
| Crystal/Nimbalyst | not confirmed | not confirmed | not confirmed | not confirmed |
| Vibe Kanban | UI "Copy Files" list | UI "Setup Scripts" / "Cleanup Scripts" | not confirmed | not confirmed |
| Claude Squad | not confirmed | not confirmed | `~/.claude-squad/worktrees/` (third party, unverified); configurable not confirmed | not confirmed |
| CCManager | `.worktreeinclude` | Post-creation hook (key not confirmed); no teardown | `{branch}` path template; default parent not confirmed; template is configurable | Status Waiting/Busy/Idle; worktree icon not confirmed |
| emdash | `.emdash.json` `preservePatterns` | `.emdash.json` `scripts.setup` / `scripts.teardown`, `shellSetup` | `~/emdash/worktrees`; yes (per project, machine) | not confirmed |
| agent-deck | `.worktreeinclude` (opt in) | `.agent-deck/worktree-setup.sh` / `worktree-destruction.sh` | `[worktree] default_location` sibling, subdirectory or path; default not confirmed; yes | not confirmed |
| Cursor | No auto copy; `cp` in `setup-worktree*` | `.cursor/worktrees.json`: `setup-worktree`, `-unix`, `-windows`; no teardown | Not in docs; forum says `~/.cursor/worktrees`, fixed (unverified) | not confirmed |
| OpenAI Codex app | `.worktreeinclude` | Local environment in `.codex/` (file and keys not confirmed); no teardown script | `$CODEX_HOME/worktrees`; yes (Settings > Worktrees > Worktree root) | "Worktree" choice under composer; `codex/` branch prefix; no icon confirmed |
| Claude Code desktop | `.worktreeinclude` | No setup key; `WorktreeCreate` / `WorktreeRemove` hooks | `<project-root>/.claude/worktrees/`; yes (Settings "Worktree location") | Worktree toggle; branch prefix; no icon confirmed |
| worktrunk (wt) | `wt step copy-ignored` (`.worktreeinclude`, `[step.copy-ignored] exclude`) | `.config/wt.toml`: `pre-start`, `post-start`; `pre-remove`, `post-remove` | `worktree-path` template; default not confirmed (snippet: sibling); yes | `wt list` gutter: `@` current, `^` primary, `+` other |
| git-worktree-runner (gtr) | `gtr.copy.include` / `exclude` / `includeDirs` / `excludeDirs` | `gtr.hook.postCreate`; `preRemove`, `postRemove` (`.gtrconfig` `[hooks]`) | `<repo-name>-worktrees` sibling; yes (`gtr.worktrees.dir`) | not confirmed |
