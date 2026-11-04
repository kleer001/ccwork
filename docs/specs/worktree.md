# Git worktrees in ccwork

A worktree row is a sidebar row whose folder is a linked git worktree. It has
its own folder, its own branch and its own terminal. It shares the history of
its repository with the main checkout. This spec covers phase 1. Phase 2 (merge
a worktree back, diff review, pull request) comes directly after phase 1 and
gets its own spec.

## 1. Scope

**Phase 1**

- The row action "Make worktree…" makes a linked worktree of the row's
  repository, next to the main checkout, and adds a row for it.
- A worktree row shows that it is a worktree, from git alone (section 4).
- A new worktree gets copies of the small gitignored files and rebuilds the
  dependencies, with no setup file in the repository (sections 5.4 and 5.5).
- A row follows Claude Code into a worktree that Claude makes, and back
  out (section 6).
- "Remove from sidebar" on a worktree row can delete the worktree and its
  branch, by opt-in, after it shows what goes with them (section 7).
- The dashboard shows one card for each repository, with all of its
  worktrees (section 8).

**Not in phase 1**

- Merge, diff review and pull request (phase 2).
- Links to large ignored files. A program that writes through a link changes
  the main checkout's file (`research/worktree-glyphs-and-shared-files.md`).
- `.worktreeinclude` and a setup script for each repository. Add each one
  when a repository needs it.
- Submodules. A new worktree has empty submodule folders (F7), and ccwork
  does not delete a worktree that has submodules (section 7).
- A `WorktreeCreate` or `WorktreeRemove` hook. Claude Code keeps its own
  worktree logic and location.

**Rule: no row action deletes work by default.** Each delete is opt-in, and
"keep" is the default answer. ccwork uses only git commands that refuse to
lose tracked work: `git worktree remove` without `--force`, and
`git branch -d`, not `-D`. Before a delete, ccwork shows the ignored files
that git deletes with no question (F3).

## 2. Terms

| Term | Meaning |
|---|---|
| Main checkout | The folder of the repository's own `.git` folder. |
| Linked worktree | A folder that `git worktree add` made. Its `.git` is a file. |
| Common dir | `git rev-parse --path-format=absolute --git-common-dir`. The same for the main checkout and each linked worktree of one repository. |
| Worktree row | A row whose folder is a linked worktree. |
| Source row | The row that "Make worktree…" runs on. It can be a main-checkout row or a worktree row. |
| Main name | The folder name of the main checkout, for example `ccwork`. |
| Home folder | The folder of a row before it follows Claude into a worktree (section 6). |

## 3. Facts

Each fact names its source. "Tested" means a run with git 2.43, uv 0.10 or
Claude Code 2.1.314 in a temporary repository.

- **F1.** In a linked worktree, `git rev-parse --show-toplevel` prints the
  worktree folder. "Add Repo" and "Rebind to…" accept a worktree folder.
  Tested.
- **F2.** A folder is a linked worktree when
  `git rev-parse --path-format=absolute --git-dir` and
  `git rev-parse --path-format=absolute --git-common-dir` differ. Without
  `--path-format=absolute`, the two differ in a subfolder of the main
  checkout too. Tested.
- **F3.** `git worktree remove <dir>` refuses a worktree with changed or
  untracked files unless it gets `--force`. Ignored files do not count: the
  command deletes them, with no question, and exits 0. It also refuses a
  worktree that has submodules, even a clean one. Tested.
- **F4.** `git branch -d` refuses a branch with commits that are not merged,
  and a branch that a worktree has checked out. It deletes the branch's
  `branch.<name>.*` config. Tested.
- **F5.** `git ls-files -z --others --ignored --exclude-standard --directory`
  lists each ignored file by name, and each wholly ignored folder as one
  entry that ends in `/`. Tested.
- **F6.** `git check-ref-format "refs/heads/<name>"` accepts `feature/x` and
  refuses `bad..name` and `@{-1}`. The `--branch` form expands `@{-1}` to the
  previous branch and accepts it. Tested.
- **F7.** `git worktree add` checks out the commit only. Uncommitted changes
  stay in the source folder, and submodule folders are empty in the new
  worktree. Tested.
- **F8.** `claude -w <name>` and the `EnterWorktree` tool make
  `<repo>/.claude/worktrees/<name>` on branch `worktree-<name>`. At exit,
  Claude removes a clean worktree and asks "keep or remove" for a worktree
  with changes. Source: code.claude.com/docs/en/worktrees.
- **F9.** What the hooks see. With `claude -w`, every event has `PWD`,
  `CLAUDE_PROJECT_DIR` and payload `cwd` set to the worktree. With
  `EnterWorktree` in a session, Stop and SessionEnd have `PWD` and payload
  `cwd` set to the worktree, and `CLAUDE_PROJECT_DIR` set to the main
  checkout. Tested with `claude -p` only. Evidence:
  `research/claude-worktree-hook-probe/`.
- **F10.** `bin/ccwork-hook-sink` sends `cwd` as `${CLAUDE_PROJECT_DIR:-$PWD}`.
  The SessionStart rebind in `MainWindow._on_hook_event` moves a row to
  `git_toplevel(cwd)` when that is a different folder. So `claude -w` moves
  the row into `.claude/worktrees/<name>`. When Claude then removes the
  worktree at exit, the row shows `(path missing)`. This is a bug now.
- **F11.** `RepoStore.rebind` pushes the old folder into `recent` when its
  last row leaves it (`src/core/repo_store.py`).
- **F12.** A worktree inside the repository makes the main checkout's
  `git status --porcelain` print `?? .claude/`, so the dashboard marks the
  repository as dirty. `<common dir>/info/exclude` is local and is never
  committed. Tested.
- **F13.** Claude Code saves permission approvals from a worktree session to
  the main checkout's `.claude/settings.local.json`, and they apply in every
  worktree. Source: code.claude.com/docs/en/worktrees.
- **F14.** A Python venv is not portable: its scripts hold absolute paths to
  its folder. Source: docs.python.org/3/library/venv.html.
- **F15.** `uv pip freeze --python <venv>/bin/python` lists the exact
  packages of a venv. An editable package shows as `-e file:///<path>`.
  Tested.

## 4. Worktree row

The worktree row is a row type that ccwork derives from git. It adds no
stored data.

- **W1.** `RepoListModel.refresh_branches` already runs git for each row. It
  also runs the F2 check and finds the main name. A row is a worktree row
  when its folder is a linked worktree.
- **W2.** The model gets one role, `ROLE_WORKTREE_OF`: the main name for a
  worktree row, else empty.
- **W3.** Line 2 of a worktree row is `<main name> ↳ <branch>`, for example
  `ccwork ↳ fix-auth`. The glyph takes the place of the dot. A main-checkout
  row keeps `ccwork · main`. `fit_line` elides the branch first, then the
  name, as now.
- **W4.** The title tab shows the same mark: `ccwork ↳ fix-auth · <title>`.
- **W5.** The glyph and its color are `worktree_glyph` (default `↳`, U+21B3)
  and `worktree_color` (default: the line-2 color) in `badge_theme.py`, so
  `badges.toml` can change them.
- **W6.** A row on a worktree folder gets the mark in each case: a row from
  "Make worktree…", a row that follows Claude into a worktree (section 6),
  and a worktree folder that the user adds with "Add Repo".

## 5. Make worktree

### 5.1 Menu

The row menu gets "Make worktree…" directly below "Clone this repo". The
item is off when the row's folder is missing or is not in a git repository.
"Clone this repo" keeps its label and its function: a second row on the same
folder.

### 5.2 Dialog

- Under the title: "A worktree is a second folder on a new branch, in the
  same repository."
- One field: the name. The name is the branch name.
- Under the field, the dialog shows what it will make:
  - the folder: `<parent of main checkout>/<main name>-<name>`, with each `/`
    in the name changed to `-`;
  - the branch: `<name>`;
  - the start commit: `from <source branch> at <short hash>`, or
    `from detached HEAD at <short hash>`;
  - when the source folder has uncommitted changes: "Uncommitted changes stay
    in `<source folder>`. The new worktree does not get them." (F7)
- OK stays off, and the dialog says why, while one of these is true:
  - the name is empty;
  - `git check-ref-format "refs/heads/<name>"` refuses it (F6);
  - the branch exists;
  - the folder exists.

### 5.3 Git and the new row

1. `git -C <source folder> worktree add -b <name> <folder> HEAD`. The new
   branch starts from the source row's current HEAD. On a git error, ccwork
   shows git's message, adds no row, and makes no other change.
2. When the source row is on a branch,
   `git -C <folder> config branch.<name>.ccworkBase <source branch>`. Phase 2
   merges into that branch. `git branch -d` deletes this config (F4).
3. ccwork adds the row at once and selects it. The row takes the badge of
   the source row. Its title is blank.
4. ccwork copies the ignored files (5.4), then starts the row's terminal in
   the worktree folder. The terminal runs the dependency setup (5.5).

From step 3 on, the row and the worktree stay. A later failure shows in the
row's terminal, and the user can remove the row with section 7.

### 5.4 Gitignored files

ccwork reads the ignored entries of the source folder with F5:

- It skips each entry that ends in `/`. So `.venv/`, `node_modules/`,
  `build/` and `tmp/` stay behind.
- It skips `.claude/settings.local.json` (F13).
- It copies each file of 1 MiB or less, with its mode and times.
- It does not copy a file over 1 MiB, or a symbolic link.

The new terminal prints, before the first prompt:

```
Copied 4 ignored files.
Not copied (over 1 MiB or a link):
  models/base.safetensors   6.9 GB
  data/index.json           130 MB
```

When a copy fails, the terminal prints the file name and the error, and
ccwork copies the other files. Each list shows up to 10 names, then the
count of the rest, because the report goes to the terminal in an
environment variable (`CCWORK_NOTICE`). A control character in a name prints
as `?`.

### 5.5 Dependencies

The new terminal rebuilds what the source folder has, in view, before the
first prompt. Ctrl+C stops it. ccwork passes the commands in
`CCWORK_SETUP_CMD`, and `bin/ccwork-bashrc` runs them once after shell init.

**Python.** A venv is a folder `.venv` or `venv` in the source folder with a
`pyvenv.cfg`. The new venv has the same folder name.

| The source folder has | ccwork runs in the worktree |
|---|---|
| a venv and `uv.lock` | `uv venv --python <version> <venv>`, then `uv sync --active` with `VIRTUAL_ENV=<venv>` |
| a venv and no `uv.lock` | `uv venv --python <version> <venv>`, then `uv pip install --python <venv>/bin/python -r <freeze file>` |

- `<version>` is the `version` line of the source `pyvenv.cfg`, or its
  `version_info` line, which `uv venv` writes instead.
- The freeze file is the output of `uv pip freeze` on the source venv (F15).
  It goes in the worktree's private git dir (`git rev-parse --git-dir`), so
  `git worktree remove` deletes it. An editable entry (`-e file://…`) whose
  path is in the source folder gets the worktree folder instead. A `name @
  file://…` entry does too, when its path is in the worktree; a build output
  that the worktree does not have, such as a wheel in an ignored `dist/`,
  keeps the source path. Other entries do not change.
- When `uv` is not on `PATH`, the terminal prints "uv not found: no venv
  made" and makes no venv.

**Node.** When the source folder has `node_modules/`, the terminal runs the
install command of its lock file:

| Lock file | Command |
|---|---|
| `package-lock.json` | `npm ci` |
| `pnpm-lock.yaml` | `pnpm install --frozen-lockfile` |
| `yarn.lock` | `yarn install --frozen-lockfile` |

With no venv and no `node_modules/`, nothing installs.

## 6. Claude's own worktrees

Claude's worktrees stay in Claude's place, `<repo>/.claude/worktrees/<name>`.

- **C1. Exclude line.** When a row first shows a folder under
  `.claude/worktrees/`, ccwork adds the line `/.claude/worktrees/` to
  `<common dir>/info/exclude`, if the line is not there. This keeps
  `git status` and the dashboard clean (F12).
- **C2. Follow in.** On SessionStart, UserPromptSubmit and Stop, ccwork reads
  the payload `cwd`. When its real path is the row's folder, ccwork runs no
  git. Otherwise ccwork gets `git_toplevel(cwd)`; a subfolder of the row's
  folder has the row's folder as its top level and changes nothing. A path
  prefix check is not enough, because Claude's worktrees are inside the main
  checkout's folder. When the top level is a different folder and its common
  dir is the row's common dir, the row rebinds to that folder. When the row has no home folder yet, ccwork stores the old folder
  as `home` on the row in `repos.json`. Subagent events never move a row. A
  `cwd` in a different repository uses the SessionStart rebind as now.
- **C3. Follow out.** On `ClaudeExited`, a row with a `home` rebinds to its
  `home`, and ccwork clears `home`. This fixes the `(path missing)` bug in
  F10.
- **C4. Restart.** At startup, a row with a `home` whose folder is missing
  rebinds to its `home`, and ccwork clears `home`.
- **C5.** The rebinds of C2, C3 and C4 do not push a folder into `recent`
  (F11).
- **C6.** The exit prompt "keep or remove" belongs to Claude. ccwork does not
  answer it.

## 7. Remove

- "Remove from sidebar" on a worktree row shows a check box "Also delete the
  worktree folder and its branch". It is off by default. On a main-checkout
  row the dialog does not change.
- Under the check box, the dialog lists the ignored entries of the worktree
  (F5): "These ignored files and folders are deleted too:", then the names,
  up to 10, and the count of the rest. With no ignored entries, the list does
  not show.
- The check box is off and disabled, with the reason, when:
  - another row uses the same folder;
  - a Claude session runs in the row's terminal;
  - the worktree has submodules (F3).
- With the box off: the row goes, the folder and the branch stay, and the
  row goes into `recent`.
- With the box on:
  1. `git -C <main checkout> worktree remove <folder>`. When git refuses (F3),
     ccwork shows git's message and keeps the row. Nothing changes. Claude
     locks its worktree while a session runs, and a crash leaves the lock;
     for a locked worktree the message adds "If no session uses it, run:
     git worktree unlock `<folder>`". ccwork does not unlock it.
  2. `git -C <main checkout> branch -d <branch>`. When git refuses (F4),
     ccwork says: "The folder is deleted. The branch `<branch>` stays, because
     it has commits that are not merged." For any other refusal (for example,
     another worktree has the branch), ccwork says that the folder is deleted
     and the branch stays, with git's message. The branch is the one that git
     names for the folder at that time, not the row's cached branch.
  3. The row goes, and it does not go into `recent`.
- A row whose worktree folder is gone (a delete that a crash stopped) is not
  a worktree row, because git cannot name its repository. It gets the
  plain dialog and goes into `recent`; its branch stays.
- Idle expiry moves a worktree row into `recent`. It never deletes a folder.
- Crash recovery does not change. It records the session folder, and
  `claude --resume` runs there.

## 8. Dashboard

- `repo_stats.gather_stats` groups rows by common dir. Each repository gets
  one card, with the main name.
- The card counts the commits of the window from the HEAD of each grouped
  folder, and counts each commit hash one time.
- The card is dirty when any grouped folder is dirty.

## 9. Build plan

Each slice gets its own tests and its own commit, in this order.

1. **Follow in and out** (section 6): `main_window.py`, the `home` field in
   `repo_store.py`. Fixes the F10 bug.
2. **Worktree row** (section 4): `refresh_branches`, `ROLE_WORKTREE_OF`, the
   delegate, the title tab, `worktree_glyph` and `worktree_color`.
3. **Make worktree** (5.1 to 5.3): `repo_store.py` (git calls; each raises
   with git's stderr) and `repo_sidebar.py` (menu and dialog).
4. **Remove** (section 7): `repo_sidebar.py` and `repo_store.py`.
5. **Copy ignored files** (5.4): a new `src/core/worktree_files.py`.
6. **Dependencies** (5.5): the setup commands and `CCWORK_SETUP_CMD` in
   `bin/ccwork-bashrc`. Check it first on ccwork's own `.venv`.
7. **Dashboard, docs, live check** (section 8): `repo_stats.py`;
   `CLAUDE.md`, `README.md`, `docs/guide.md`; the live check below.

**Live check** on Xvfb, with an interactive Claude Code session:

- `claude -w` in a normal row, then exit with remove: the row follows in and
  comes back.
- `EnterWorktree` and `ExitWorktree` in a session: confirm the payload `cwd`
  of SessionStart, UserPromptSubmit and Stop, and that the row follows.
- A subagent with `isolation: worktree`: the row does not move.
- After a crash in an `EnterWorktree` session: find the folder that
  `claude --resume` needs, and check that crash recovery records it.
- "Make worktree…" on ccwork itself, with its `.venv`.
- The delete check box on a clean and on a dirty worktree.

## 10. Done when

Each item runs in a temporary git repository unless it names the live check.

| Step | Expected result |
|---|---|
| Make worktree `fix/a` from a clean `main` row. | Folder `<parent>/<main name>-fix-a`, branch `fix/a`, `branch.fix/a.ccworkBase = main`. The new row is selected, and line 2 is `<main name> ↳ fix/a`. In its terminal, `pwd` prints the folder and `git branch --show-current` prints `fix/a`. |
| In the dialog, type nothing, then `bad..name`, then `@{-1}`, then an existing branch name, then a name whose folder exists. | OK stays off each time, and the dialog names the reason. |
| Make a worktree from a row with a detached HEAD. | The preview says `from detached HEAD at <hash>`. The worktree is made with no `ccworkBase`. |
| Make a worktree from a row with an uncommitted edit. | The dialog shows the uncommitted-changes line. The new worktree has the committed text. |
| Open the dialog, make the branch from a shell, then press OK. | `git worktree add` fails. ccwork shows git's message and adds no row. |
| Make a worktree from a folder with an ignored `.env`, an ignored 2 MiB file and an ignored `tmp/` folder. | `.env` is copied. The terminal lists the 2 MiB file as not copied. `tmp/` is not in the worktree. |
| Make a worktree from a folder with a `.venv` and `requirements.txt` (no `uv.lock`). | The terminal makes `.venv` with the same Python version and the same packages. The project's tests run in the new row with no manual install. |
| `claude -w x` in a row, then exit with remove (live check). | The row shows `<main name> ↳ worktree-x` while Claude works, and its main checkout after exit, with no `(path missing)`. `recent` does not change. |
| A row has a `home` and a missing folder at startup. | The row is on its `home`, and `home` is clear. |
| A row first shows a folder under `.claude/worktrees/`. | `<common dir>/info/exclude` has `/.claude/worktrees/`, and the main checkout's `git status` is clean. |
| Remove a clean worktree row with an ignored `.env`, with the box on. | The dialog lists `.env`. The folder and the branch are deleted. The row is gone and not in `recent`. |
| Remove a dirty worktree row with the box on. | git refuses, ccwork shows the message, and the row and the folder stay. |
| Remove a worktree row whose branch has an unmerged commit, with the box on. | The folder is deleted, the branch stays, and ccwork says why. |
| Remove a worktree row of a repository with a submodule. | The box is off and disabled, with the reason. |
| The dashboard with a repository that has two worktree rows and one shared commit. | One card, with the main name. The shared commit counts one time. |
