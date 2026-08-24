# HaloCue agent guide

## Mission

HaloCue is a long-lived local-first toolchain for Blue Archive-inspired narrative
production. The 0.9 Python application remains supported while 1.x introduces a
shared project model, a desktop runtime, a BA story editor, an MMT presentation,
and an AI GalGame workspace.

## Before changing code

1. Read `CONTEXT-MAP.md` and the context file that owns the area being changed.
2. Read `docs/product-direction-1.x.md` for any 1.x planning or product-facing
   change, then read relevant records in `docs/adr/`.
3. Check `git status --short --branch` and preserve unrelated user changes.
4. Search for an existing domain type, adapter, contract, or test before adding one.
5. Identify the GitHub issue and branch for the change. One issue should describe
   one demonstrable vertical slice.
6. For a cross-session or collaborator change, follow
   `docs/agents/long-term-memory.md`,
   `docs/agents/remote-collaboration.md`, and read the newest applicable handoff.

## Repository boundaries

- Root Python modules and the existing `tests/` suite are the 0.9 compatibility
  surface. Keep them runnable while migrating.
- `packages/project-model` owns the canonical `HaloCueProject` model.
- `packages/contracts` owns versioned cross-context JSON contracts.
- `apps/desktop-client` owns the Tauri client and presentation workspaces.
- `services/halocue` owns the local service boundary and durable jobs.
- `contexts/` contains domain language and context-specific decisions.
- `legacy/0.9` documents the legacy boundary; it is not a second copy of the
  Python source.

## Design rules

- Keep one source of truth: AA and MMT are presentations of one project model.
- Treat StoryForge `StudioProject v2` as a renderer/export adapter, not the
  canonical product model.
- Cross-context changes require a versioned contract, migration, and round-trip
  tests.
- AI output creates a Proposal. Only an explicit user decision creates a formal
  Revision or changes a release.
- Keep file writes atomic, paths validated, and user data outside the repository.
- Use small, typed modules and stable IDs. Do not hide domain state in UI
  components or global mutable process state.
- Prefer deterministic evaluation so preview and offline export agree.
- Preserve licenses and provenance. Reverse-engineered applications and game
  assets are research inputs, not source code to copy into this MIT repository.
- AA compatibility may reproduce observable presentation behavior, documented
  coordinates, logical resource keys, and relative locations. Load real BA/AA
  bytes only from user-supplied or authorized local manifests; a verified local
  cache is user data, while public fixtures must be synthetic and hashed.

## Validation

Run the narrowest relevant checks first, then the full suite before merging:

```text
Python: pytest; ruff check; ruff format --check
TypeScript: tsc --noEmit; vitest; playwright
Rust: cargo fmt --check; cargo clippy -- -D warnings; cargo test
```

Do not claim a check passed if the required tool or dependency was unavailable.
Record the exact command and result in a handoff when a slice crosses contexts.

## Collaboration

- `main` is the release branch and receives reviewed pull requests only.
- `feature/1.0-runtime` is the runtime/client stream.
- `feature/1.1-ba-editor` is the BA editor stream.
- `chore/contracts` is the shared contract stream.
- When both maintainers work on 1.1, treat `feature/1.1-ba-editor` as the
  integration base and use one short-lived `feature/1.1-*` branch per slice;
  never share a mutable working branch.
- Use `docs/handoffs/` for school-break handoffs: commits, contracts, tests,
  known issues, commands, and decisions needing confirmation.
- The 1.1 editor is an alternating-time collaboration: the maintainer and
  collaborator work on separate branches in different time windows. Start a
  session by fetching and reading the newest handoff; end it by pushing a
  focused commit/PR and recording the exact handoff. Preserve the other
  developer's commits and resolve shared-file conflicts in a PR discussion.
- Use GitHub Issues as the task tracker. Triage labels are defined in
  `docs/agents/triage-labels.md`.
- New ideas and architecture concerns use `.github/ISSUE_TEMPLATE/proposal.yml`;
  implemented work is handed over through a focused PR and `docs/handoffs/`.
- The collaborator works from another computer. Use relative repository paths and
  remote commit/PR references; maintainer-local research paths are never shared
  prerequisites. See `docs/agents/remote-collaboration.md`.
- Repeated workflows become Skill proposals under
  `docs/agents/skill-proposals/`; only reviewed PRs activate a Skill under
  `.agents/skills/`.

## Agent skills

### Issue tracker

Issues are tracked in `Suciko/HaloCue` GitHub Issues. See
`docs/agents/issue-tracker.md`.

### Triage labels

Use the five standard Matt Pocock triage labels. See
`docs/agents/triage-labels.md`.

### Domain docs

This is a multi-context repository. See `docs/agents/domain.md` and
`CONTEXT-MAP.md`.

### Long-term memory

The source-of-truth hierarchy, collaborator feedback route, and Skill proposal
gate are defined in `docs/agents/long-term-memory.md`,
`docs/agents/skill-proposals.md`, and ADR-0006. The approved session Skill is
`.agents/skills/halocue-session-governance/SKILL.md`.

## Documentation routing

- Cross-system context: `CONTEXT-MAP.md`
- Product direction: `docs/product-direction-1.x.md`
- Remote collaboration: `docs/agents/remote-collaboration.md`
- Issue tracker and triage: `docs/agents/`
- Architecture decisions: `docs/adr/`
- Client: `contexts/client/CONTEXT.md`
- Backend: `contexts/backend/CONTEXT.md`
- BA editor: `contexts/ba-editor/CONTEXT.md`
- AI GalGame: `contexts/ai-galgame/CONTEXT.md`
