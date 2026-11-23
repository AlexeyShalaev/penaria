---
name: worktree
description: Manage this repository's git worktrees in local/worktrees/ - create one for a task, list them with their state, remove one that is no longer needed, and clean up every worktree whose branch was merged or abandoned. Use when the user asks for a worktree, to see the worktrees, or to clean them up, and at the end of a task done in a worktree.
argument-hint: "[new <task> | list | remove <name> | prune]"
---

Follow `.agents/skills/worktree/SKILL.md`, the same for every agent, with the request: $ARGUMENTS
