# Long-term memory protocol

This protocol keeps agents aligned with HaloCue's product direction while two
developers work in alternating time windows. It is the operational companion to
ADR-0006.

## Start of a work session

Complete these reads before editing code or deciding a cross-context change:

1. Run `git status --short --branch` and preserve unrelated changes.
2. Run `git fetch origin --prune` when network access is available. Inspect the
   target branch, open PRs, relevant Issues, and the newest handoff.
3. Read `docs/product-direction-1.x.md` for 1.0/1.1/1.2 scope.
4. Read `CONTEXT-MAP.md`, the owning `contexts/*/CONTEXT.md`, and relevant ADRs.
5. Read `docs/agents/issue-tracker.md` and `docs/agents/triage-labels.md` before
   creating or changing an Issue.

If a handoff, Issue, ADR, or test conflicts with local memory, trust the
reviewed repository record and report the conflict in the current PR or
handoff. Do not resolve it by silently editing the older record.

## Classify new information

Use the smallest durable home:

| Information | Durable home | Required action |
| --- | --- | --- |
| Product goal or release boundary | `docs/product-direction-1.x.md` | Product proposal and maintainer review before changing. |
| Cross-context decision or invariant | `docs/adr/` or context doc | Versioned ADR/contract and tests. |
| New idea, concern, or alternative | GitHub Issue | Use the proposal template and label it `needs-triage`. |
| Work completed in one session | `docs/handoffs/` | Record commit, PR, tests, contracts, and next action. |
| Repeated workflow | `docs/agents/skill-proposals/` | Draft a Skill candidate with evidence; wait for approval. |
| Temporary observation | PR comment or issue comment | Link the source; do not promote it automatically. |

Do not duplicate a decision in a handoff or Skill. Link to its source of truth.

## Collaborator feedback route

The collaborator can communicate new ideas even when the other maintainer is
offline:

1. Open a GitHub Issue using `.github/ISSUE_TEMPLATE/proposal.yml`.
2. State whether it is a product idea, architecture concern, compatibility
   observation, performance problem, or workflow improvement.
3. Include the affected release/context, evidence, alternatives, and an
   observable acceptance test. Attach no private assets or absolute paths.
4. Leave the Issue at `needs-triage` unless the maintainer has explicitly
   accepted its scope. A proposal that requires a human product or license
   decision uses `ready-for-human` after triage.
5. If code is already implemented, open a focused PR and add a handoff. The
   PR links the Issue; the handoff names the exact commit and remaining risks.

The next developer starts from the Issue/PR/handoff, not from a copied archive
or an assumption about what happened in the other person's chat.

## End of a work session

Before handing the repository to the other time window:

- commit only the focused vertical slice;
- record exact tests and their results;
- update or create `docs/handoffs/YYYY-MM-DD-<slice>.md`;
- link the Issue, PR, contract/schema changes, migrations, known issues, and
  decisions needing confirmation;
- push the branch when remote access is available;
- state the next safe command or next bounded slice.

An incomplete task is still a successful handoff when its boundary and next
action are explicit. Never hide unfinished work in a generic "continue later"
note.

## Stale memory and conflicts

Mark a record `superseded`, `rejected`, or `expired` with a link to the newer
record. Preserve the old record for audit; do not delete history to make a
conflict disappear. When two accepted records conflict, stop implementation at
the conflicting boundary and open a decision Issue/ADR update.

Local Codex memories and OpenClaw memory plugins can help retrieve relevant
notes, but they are not a substitute for these files. Keep local memory enabled
only if its privacy settings are acceptable, and never put project secrets or
proprietary resources in it.
