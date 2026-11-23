---
name: worktree
description: Manage this repository's git worktrees in local/worktrees/ - create one for a task, list them with their state, remove one that is no longer needed, and clean up every worktree whose branch was merged or abandoned. Use when the user asks for a worktree, to see the worktrees, or to clean them up, and at the end of a task done in a worktree.
---

# Worktrees

Work from the main clone's root: the directory that holds `.agents/` and whose `.git` is a directory, not a file. Inside a worktree, `git rev-parse --path-format=absolute --git-common-dir` gives the main clone's `.git`; run everything below from its parent.

Every worktree of this repository lives in `local/worktrees/<name>`, where `<name>` is the branch's short description (`feat/registry-entities` → `local/worktrees/registry-entities`). `local/` is ignored by git, so the main clone never sees the worktrees' files. Never create a worktree anywhere else, and never touch a worktree outside `local/worktrees/` (Claude Code's own `.claude/worktrees/` among them).

The request names one action: `new`, `list`, `remove <name>` or `prune`. Without one, `list`.

## new

1. Create the branch as `.agents/skills/new-branch/SKILL.md` says, as a worktree at `local/worktrees/<name>`.
2. Prepare it: files git ignores are not in the worktree. Copy the ones the services need to run and test (`.env` files of the services, never anything under `local/`) from the main clone after the user's yes, then run the install command from `.agents/project.md` in the worktree.
3. Report the path; from then on every command for the task runs in that directory.

## list

`git fetch --prune origin`, then for every entry of `git worktree list --porcelain` under `local/worktrees/` show one line:

- the name, the branch, and the last commit's date;
- **dirty** when `git -C <path> status --porcelain` prints anything;
- **unpushed** when the branch has no upstream, or `git -C <path> log @{upstream}..HEAD --oneline` prints anything;
- the pull request's state from `gh pr list --head <branch> --state all --json number,state,url` (none, open, merged, closed);
- **stale** when git lists the worktree as `prunable` (its directory is gone).

Then show directories in `local/worktrees/` that are not worktrees: leftovers to delete.

## remove <name>

1. Check the worktree as `list` does.
2. **Dirty** or **unpushed** work, or a pull request that is still open: stop and show what would be lost (`git -C <path> status --short`, the unpushed commits). Remove only after the user's explicit yes for this worktree, and only then with `--force`.
3. `git worktree remove <path>` (without `--force` when the checks passed).
4. Delete the local branch when its pull request is merged (pull requests are squash-merged, so git does not see the branch as merged: `git branch -D <branch>` is right here), or when the user says the work is abandoned. Otherwise keep the branch and say so.
5. `git worktree prune`, and report what was removed and what was kept.

## prune

Run `list`, then propose to remove, in one list for one confirmation:

- worktrees whose pull request is merged or closed, with nothing dirty or unpushed;
- worktrees git lists as `prunable`;
- leftover directories in `local/worktrees/` that are not worktrees.

Leave out everything else and say why (dirty, unpushed, open pull request, no pull request yet). After the user's yes, remove each as `remove` says, without asking again for the ones in the confirmed list.

## Rules

- Do not remove a worktree that the current session or another agent is working in: when in doubt, ask.
- Never delete a branch on the remote.
- Never run `git worktree remove --force` or `git branch -D` on work that is not merged without the user's yes for that worktree.
- If a git command fails, show the error and stop.

At the end of a task done in a worktree, once its pull request is merged, offer `remove <name>`.
