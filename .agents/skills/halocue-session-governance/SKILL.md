---
name: halocue-session-governance
description: Use for any HaloCue coding, architecture, or collaborator handoff session; load the product direction and memory protocol, classify new decisions, and produce a reviewable handoff or Skill proposal when the work ends.
---

# HaloCue session governance

Use this Skill at the start of every HaloCue work session and before handing
work to the other collaborator.

## Start

1. Read `docs/product-direction-1.x.md`.
2. Read `CONTEXT-MAP.md`, the owning context, and relevant `docs/adr/` files.
3. Read `docs/agents/long-term-memory.md`,
   `docs/agents/remote-collaboration.md`, and the newest applicable handoff.
4. Run `git status --short --branch`; preserve unrelated changes.
5. Identify the GitHub Issue, branch, and smallest demonstrable vertical slice.

Completion criterion: the current release, owning context, issue, branch, and
source-of-truth documents are written down before code changes begin.

## During work

Keep product ideas in Issues, accepted cross-context decisions in ADRs or
contracts, and session state in a handoff. Link rather than duplicate accepted
decisions. Keep external research and user data outside the repository.

When the same workflow repeats across two sessions or handoffs, create a
candidate under `docs/agents/skill-proposals/` using its template. A candidate
is a proposal, not an active Skill.

Completion criterion: every new durable claim has a source, owner, status, and
review path.

## End

1. Run the narrowest relevant tests and record exact commands and results.
2. Commit only the focused slice and push its short-lived branch when possible.
3. Create or update `docs/handoffs/YYYY-MM-DD-<slice>.md` with the commit, PR,
   contracts, tests, known issues, next action, and decisions needing review.
4. Link any new proposal or Issue from the handoff.

Completion criterion: another developer can continue from the branch, Issue,
and handoff without access to this chat.
