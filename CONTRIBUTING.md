# Contributing to HaloCue

HaloCue has two active compatibility horizons: the existing 0.9 Python
application and the planned 1.x client/service packages. Keep changes narrow,
typed, tested, and easy to hand off.

## Before opening a pull request

1. Create or identify a GitHub Issue with a demonstrable vertical slice.
2. Read `AGENTS.md`, `CONTEXT-MAP.md`, the owning context, and relevant ADRs.
3. Work from the matching branch: `feature/1.0-runtime`,
   `feature/1.1-ba-editor`, or `chore/contracts`.
4. Keep unrelated files and local data out of the commit.
5. Run the narrowest checks for the changed context and record the commands.

For cross-session work, also follow `docs/agents/long-term-memory.md`. New
product or architecture ideas go through `.github/ISSUE_TEMPLATE/proposal.yml`;
repeated workflows go through `docs/agents/skill-proposals.md` before becoming
an active repository Skill.

## Pull request requirements

- Explain the user-visible behavior and the owning context.
- List schema/contract changes and migrations explicitly.
- Include tests for the happy path, error path, and persistence/round-trip path
  when the change crosses a boundary.
- Add or update an ADR when the change alters ownership, wire format, licensing,
  or a system-wide invariant.
- Do not include API keys, personal paths, user projects, game assets, reverse
  engineering output, generated archives, or model caches.

## Handoffs

School-break and collaborator deliveries must include a record under
`docs/handoffs/`. The record names the PR and commit, changed contracts,
migrations, test results, known issues, local commands, and open decisions.
