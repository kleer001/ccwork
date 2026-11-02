# Worktree and branch glyphs; sharing large ignored files across worktrees

## Answer

No tool in this survey uses a dedicated non-Private-Use Unicode glyph for a worktree. The only dedicated worktree icons found are Nerd Font code points (lazygit). For a branch, U+2387 (⎇) is the documented Unicode example in vim-airline, and ᚠ (U+16A0) is its built-in utf-8 default. For shared large files, the established tools choose reflink, hardlink or symlink with a read-only or locked state (DVC, git-annex). The sources show no standard worktree-level lock or marker convention.

## Findings

### Branch and worktree glyphs

| Tool | Branch glyph | Worktree glyph | Usable without a Nerd Font | Source |
|---|---|---|---|---|
| lazygit (Nerd Font v3 default) | U+F062C | linked U+F0339, missing U+F033A | No (Supplementary PUA-A) | https://raw.githubusercontent.com/jesseduffield/lazygit/master/pkg/gui/presentation/icons/git_icons.go |
| lazygit (Nerd Font v2 patch) | U+FB2B (Alphabetic Presentation Forms, not PUA) | PUA code points | Not for worktree | same URL |
| lazygit (icons off) | plain branch name | current worktree marked `  *`; main worktree gets a label (English text not confirmed) | Yes, text only | https://raw.githubusercontent.com/jesseduffield/lazygit/master/pkg/gui/presentation/worktrees.go |
| vim-airline | `⎇` (U+2387) in the documented "unicode symbols" example (doc/airline.txt line 396); `ᚠ` (U+16A0) is the built-in utf-8 default; `` is the powerline default | none | Yes for ⎇ and ᚠ | https://github.com/vim-airline/vim-airline/blob/master/autoload/airline/init.vim |
| oh-my-posh | U+E0A0 (Powerline, PUA) | none shipped; template fields `.IsWorkTree`, `.MainWorktree`, `.WorktreeCount` let users add one | No | https://ohmyposh.dev/docs/segments/scm/git |
| Starship | Nerd Font symbol, code point unconfirmed | no linked-worktree indicator | No | https://raw.githubusercontent.com/starship/starship/master/src/configs/git_branch.rs ; https://starship.rs/config/ |
| konoma (TUI) | ⎇ shown only with `ui.icons=true`; search snippet only, unverified | none | Yes if confirmed | https://docs.rs/crate/konoma/0.28.3/source/src/ui/icons.rs |
| agnoster | Powerline PUA; fork gist snippet only | none | No | https://gist.github.com/agnoster/3712874 |

- lazygit glyph values were read through a fetch summary. Treat them as likely, not literal. Sources: the git_icons.go URL above and https://raw.githubusercontent.com/jesseduffield/lazygit/master/pkg/gui/presentation/icons/icons.go.
- lazygit icons are off by default. With icons off, worktrees are marked with text only. Source: the icons.go and worktrees.go URLs above.
- Starship has no worktree module. Its `git_status` `worktree_*` options describe file state, not linked worktrees. Source: https://starship.rs/config/
- Other worktree TUIs avoid emoji or use plain symbols. git-workty uses a triangle, filled circle and check mark, with ASCII fallback `>` and `*` (https://docs.rs/git-workty/0.3.2/src/git_workty/ui.rs.html). worktrunk replaced emoji with ◎ ✓ ✗ ▲ ↳ ○ ❯ for terminal compatibility (https://docs.rs/crate/worktrunk/0.8.4/source/CHANGELOG.md). Both are snippet-only.
- A Cursor forum thread suggests a plain-text `[worktree: branch]` badge instead of a glyph (snippet only). Source: https://forum.cursor.com/t/label-worktrees-while-in-terminal/170004
- gwm-cli uses Nerd Font folder glyphs (PUA, snippet only). Source: https://docs.rs/crate/gwm-cli/latest/source/src/tui/wt_tree.rs
- No evidence found for ⑂, ⌥, ᚴ, 🌿 or 🌳 as a worktree marker. Source: web search results; no primary URL.

### GUI clients and IDEs

- No GUI source documents a worktree icon.
- VS Code lists worktrees as separate entries in Source Control Repositories; icons are not described. Source: https://code.visualstudio.com/docs/sourcecontrol/branches-worktrees
- A third-party list reports codicons named "worktree" and "worktree-small". Not confirmed against the official repo. Source: https://composables.com/icons/icon-libraries/vscode-codicons
- Octicons has `git-branch` and `repo-forked`, but no worktree icon was found. Sources: https://primer.style/octicons/git-branch-16/ ; https://primer.style/octicons/icon/repo-forked-24
- IntelliJ has a Worktrees tab in the Git tool window; no icon is named. Source: https://www.jetbrains.com/help/idea/use-git-worktrees.html
- GitKraken shows worktrees in the Left Panel. When the folder name differs from the branch, it shows the folder name under the branch name. Source: https://help.gitkraken.com/gitkraken-desktop/worktrees/
- Tower, Fork, Sublime Merge and Sourcetree have only third-party evidence. Source: https://gitmeridian.com/git-worktrees/ (a competing vendor, not authoritative).

### Sharing large ignored files

| Tool | Method | Write protection | Source |
|---|---|---|---|
| worktrunk `wt step copy-ignored` | Copy by reflink where supported; on ext4 a full copy. No symlink or hardlink mode. Files must match gitignore and `.worktreeinclude`. | not applicable (copies) | https://worktrunk.dev/step/ |
| DVC `cache.type` | reflink, hardlink, symlink or copy. Tries reflink first, then copy. | Hardlinks and symlinks are made read-only; `dvc unprotect` is needed to modify them | https://doc.dvc.org/user-guide/data-management/large-dataset-optimization |
| git-annex | Locked files are symlinks. `git annex unlock` makes a pointer file with a working copy, and the change must be committed. `annex.thin` uses a hardlink and can lose the old version on modification. | "Content of annexed files is protected from being changed"; permission bits not confirmed | https://git-annex.branchable.com/git-annex-unlock/ ; https://git-annex.branchable.com/tips/unlocked_files/ |
| pnpm | Default `auto`: hardlink, then clone, then copy on Linux. ext4 never supported cloning, so it hardlinks. | Not documented. Docs say a hardlinked edit changes every project. `clone-or-copy` is used for packages that write to their files. | https://pnpm.io/settings/node-modules |
| uv `link-mode` | clone (default on Linux and macOS), copy, hardlink, symlink. Docs discourage symlink. ext4 fallback not confirmed. | not stated | https://docs.astral.sh/uv/reference/settings/ |
| Hugging Face Hub cache | `snapshots/` symlinks into `blobs/` by hash. With symlinks disabled, files are stored per revision. | None described | https://huggingface.co/docs/huggingface_hub/guides/manage-cache |

- Established practice on ext4 is a link plus a read-only or locked state (DVC, git-annex), or a full copy (worktrunk). Hardlink is the pnpm default on ext4. All of these protect against shared writes in different ways.
- A symlinked or hardlinked write changes the shared file. pnpm states this for hardlinks. Source: https://pnpm.io/settings/node-modules
- Editors can break links on save. Vim `backupcopy=no` renames the original and writes a new file, so "the new file will not be a link". `yes` preserves links and overwrites in place. `breakhardlink` forces the rename behavior. Source: https://vimhelp.org/options.txt.html
- Inference from the vim text, not stated by the source: under rename-over, the main checkout file is untouched. Under in-place overwrite, the main file changes.
- SQLite before 3.10.0 had undefined behavior when opened through a symlink. Since 3.10.0 it resolves symlinks to a canonical name. Renaming or unlinking an open database, or moving a hot journal, can corrupt it. Source: https://sqlite.org/howtocorrupt.html
- git-annex supports worktrees since version 6.20180719. It replaces the worktree `.git` file with a symlink. Bare repository plus worktrees is "not really supported". Source: https://git-annex.branchable.com/tips/Using_git-worktree_with_annex/ (last edited 2019-01-21)

### Lock and marker conventions

- `git worktree lock` writes a `locked` file with a reason under `$GIT_DIR/worktrees/<id>/`. It prevents pruning, moving and deletion of the worktree. It is not file locking and does not cover ignored files. Source: https://git-scm.com/docs/git-worktree
- `git lfs lock` is a server-side advisory lock on LFS-tracked paths that checks pushes. It gives no OS write protection. Source: https://github.com/git-lfs/git-lfs/blob/main/docs/man/git-lfs-lock.adoc
- No standard lock or marker for files shared by links was found in this survey. DVC read-only protection and the git-annex locked/unlocked model are the closest conventions. Neither is a worktree-level standard. Sources: the DVC and git-annex URLs above.

## Conflicts

- Branch glyph in vim-airline. A CSDN mirror says `plugin/airline.vim` assigns ⎇ to the branch key (https://blog.csdn.net/gitblog_00076/article/details/141741853). The upstream `autoload/airline/init.vim` sets ᚠ as the utf-8 default (https://github.com/vim-airline/vim-airline/blob/master/autoload/airline/init.vim). Direct reading of the source resolves this. ⎇ is the documented unicode example (doc/airline.txt line 396). ᚠ is the built-in utf-8 default. The upstream source is more authoritative than the secondary mirror.

## Gaps

- The Starship branch symbol code point is unconfirmed (blank in the fetch).
- The lazygit English text for the main worktree label is unconfirmed. The lazygit values came from a fetch summary.
- The Nerd Font glyph names are not confirmed. The codicon codepoint for worktree is not found.
- konoma's ⎇ use is unverified. Powerlevel10k, gitstatus, lightline, fugitive, Pure and Spaceship were not read.
- Vendor docs for Tower, Fork, Sublime Merge and Sourcetree were not found.
- git-annex lock permission bits and symlink target are unconfirmed.
- DVC `unprotect` internals and the full fallback order are unconfirmed.
- The uv ext4 fallback for `clone` is unconfirmed.
- Whether SQLite resolves symlinks for `-wal` and `-journal` sidecar files is unconfirmed.
- gtr, Conductor, Claude Code `.worktreeinclude` and Cursor `worktrees.json` were not researched for symlink and warning behavior.
- Whether Git LFS locks apply to untracked or ignored files is unconfirmed.
- Blocked URLs: none. The dvc.org URL redirected to doc.dvc.org and was followed.

## Sources

- https://raw.githubusercontent.com/jesseduffield/lazygit/master/pkg/gui/presentation/icons/git_icons.go — lazygit git_icons.go
- https://raw.githubusercontent.com/jesseduffield/lazygit/master/pkg/gui/presentation/icons/icons.go — lazygit icons.go
- https://raw.githubusercontent.com/jesseduffield/lazygit/master/pkg/gui/presentation/worktrees.go — lazygit worktrees.go
- https://raw.githubusercontent.com/starship/starship/master/src/configs/git_branch.rs — Starship git_branch.rs
- https://starship.rs/config/ — Starship configuration reference
- https://ohmyposh.dev/docs/segments/scm/git — oh-my-posh git segment
- https://github.com/vim-airline/vim-airline/blob/master/autoload/airline/init.vim — vim-airline init.vim
- https://blog.csdn.net/gitblog_00076/article/details/141741853 — CSDN mirror of vim-airline docs (secondary)
- https://docs.rs/crate/konoma/0.28.3/source/src/ui/icons.rs — konoma icons.rs (snippet only)
- https://gist.github.com/agnoster/3712874 — agnoster gist (snippet only)
- https://docs.rs/git-workty/0.3.2/src/git_workty/ui.rs.html — git-workty ui.rs (snippet only)
- https://docs.rs/crate/worktrunk/0.8.4/source/CHANGELOG.md — worktrunk CHANGELOG (snippet only)
- https://docs.rs/crate/gwm-cli/latest/source/src/tui/wt_tree.rs — gwm-cli wt_tree.rs (snippet only)
- https://forum.cursor.com/t/label-worktrees-while-in-terminal/170004 — Cursor forum thread (snippet only)
- https://code.visualstudio.com/docs/sourcecontrol/branches-worktrees — VS Code branches and worktrees
- https://composables.com/icons/icon-libraries/vscode-codicons — third-party codicon list
- https://primer.style/octicons/git-branch-16/ — Octicons git-branch
- https://primer.style/octicons/icon/repo-forked-24 — Octicons repo-forked
- https://www.jetbrains.com/help/idea/use-git-worktrees.html — IntelliJ Use Git worktrees
- https://help.gitkraken.com/gitkraken-desktop/worktrees/ — GitKraken worktrees
- https://gitmeridian.com/git-worktrees/ — third-party worktree GUI article
- https://worktrunk.dev/step/ — worktrunk wt step
- https://doc.dvc.org/user-guide/data-management/large-dataset-optimization — DVC large dataset optimization
- https://git-annex.branchable.com/git-annex-unlock/ — git-annex unlock
- https://git-annex.branchable.com/tips/unlocked_files/ — git-annex unlocked files tip
- https://git-annex.branchable.com/tips/Using_git-worktree_with_annex/ — git-annex with git-worktree
- https://pnpm.io/settings/node-modules — pnpm node_modules settings
- https://docs.astral.sh/uv/reference/settings/ — uv settings
- https://huggingface.co/docs/huggingface_hub/guides/manage-cache — Hugging Face cache
- https://git-scm.com/docs/git-worktree — git-worktree
- https://github.com/git-lfs/git-lfs/blob/main/docs/man/git-lfs-lock.adoc — git-lfs-lock
- https://vimhelp.org/options.txt.html — Vim options
- https://sqlite.org/howtocorrupt.html — SQLite how to corrupt
