# ADR-0006: Controlled long-term memory and Skill governance

- Status: accepted
- Date: 2026-08-24

## Decision

HaloCue uses controlled accumulated memory. Durable project truth is checked
into the repository and reviewed like code. Agent-local memories, chat history,
and automatically drafted Skills are recall and proposal layers; they cannot
silently change product direction, architecture, contracts, licensing, or
release behavior.

The authority order is:

1. `docs/product-direction-1.x.md` for product intent and release boundaries.
2. Accepted ADRs, context documents, contracts, tests, and shipped behavior for
   system invariants and implementation facts.
3. GitHub Issues and PRs for proposed work, discussion, review evidence, and
   accepted implementation changes.
4. `docs/handoffs/` for the current asynchronous work-session state.
5. External research notes and raw conversations for evidence that still needs
   a decision.
6. Local Codex/OpenClaw memories for recall only.

An approved repository Skill is a reusable procedure. It is subordinate to all
of the layers above and must contain a clear trigger, scope, steps, and
completion checks.

## Memory record rules

When an agent records durable context, it must identify:

- `kind`: `direction`, `decision`, `invariant`, `fact`, `proposal`, `handoff`,
  or `skill-candidate`;
- `scope`: release, context, package, or issue/PR;
- `status`: `accepted`, `candidate`, `superseded`, `rejected`, or `expired`;
- `source`: file path, issue/PR URL, commit, or external URL;
- `observed_at` and, when relevant, `reviewed_at` or `expires_at`;
- the smallest claim that can be checked by another agent.

Secrets, API keys, personal paths, user projects, raw prompts containing private
content, and proprietary assets never enter a memory record. A fact that cannot
be source-linked remains a proposal or research note, not an invariant.

## Automatic Skill candidates

An agent may detect and draft a Skill candidate when a workflow is repeated at
least twice in separate sessions, appears in two handoffs/issues, or encodes a
high-value invariant that agents repeatedly miss. The agent creates a proposal
under `docs/agents/skill-proposals/` with evidence and a draft `SKILL.md`.

The proposal must include:

- trigger and non-trigger conditions;
- inputs, outputs, and owning context;
- numbered steps with observable completion criteria;
- evidence from handoffs/issues/commits;
- expected benefit and failure modes;
- license/provenance review for every referenced tool or asset;
- a test or dry-run showing that the procedure is useful.

The agent must not write directly to `.agents/skills/`, install a third-party
Skill, or modify an existing active Skill as part of detection. A maintainer
reviews the proposal in a PR. Proposals affecting product direction, contracts,
or shared ownership need approval from both collaborators; a local workflow
Skill may be approved by its owning maintainer. Only the approved PR moves the
draft into `.agents/skills/<name>/SKILL.md`.

## Consequences

- The project survives model changes, context compaction, and alternating work
  hours because its critical memory is versioned and reviewable.
- The collaborator has one visible feedback route: an Issue for a new idea or a
  PR/handoff for implemented work. No idea is lost in a private chat.
- Agents do more bookkeeping at session boundaries, but stale or conflicting
  memories can be superseded instead of silently accumulating.
- Automatic learning remains useful without granting an agent authority to
  rewrite the project's long-term rules.

## Alternatives considered

- **Chat history as the memory:** rejected because it is not reliably available
  to the other collaborator or to a new agent.
- **One giant `MEMORY.md`:** rejected because it mixes decisions, stale facts,
  proposals, and session state without ownership or review boundaries.
- **Unreviewed automatic Skill installation:** rejected because a repeated
  workflow can encode unsafe assumptions, license violations, or obsolete
  product behavior.

## References

- [Codex memories](https://learn.chatgpt.com/docs/customization/memories.md)
- [Codex Skills](https://learn.chatgpt.com/docs/build-skills.md)
- [OpenClaw memory](https://docs.openclaw.ai/concepts/memory)
- [OpenClaw Skills and Skill Workshop](https://docs.openclaw.ai/tools/skills)
