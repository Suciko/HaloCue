# HaloCue context map

This is a multi-context repository. Read the system-wide context below and then
the context file for the code being changed. Read relevant ADRs before proposing
or implementing a cross-context change.

## System-wide invariants

- Product intent and release boundaries are defined in
  `docs/product-direction-1.x.md`. Do not infer them from chat history.
- `HaloCueProject` is the canonical product model.
- AA and MMT are presentation adapters over the same story, IDs, variables, and
  save state.
- StoryForge `StudioProject v2` is a renderer/export format, not the product
  model.
- Published writing revisions are immutable and are handed to production by
  versioned contracts.
- AI proposals never silently become formal revisions.
- User assets, API keys, game data, reverse-engineering output, and generated
  artifacts stay outside the public source tree.
- AA presentation compatibility is implemented as behavior/coordinate/resource
  role data. Observable logical keys and relative locations may be recorded in
  the resource contract; real BA/AA bytes are user-supplied or explicitly
  authorized local data.
- Durable project truth, collaborator handoffs, feedback, and Skill proposals
  follow `docs/agents/long-term-memory.md` and ADR-0006. Local agent memory is
  recall only.
- The maintainers work on separate computers. GitHub commits, PRs, Issues, and
  handoffs are the shared boundary; absolute local paths are never contracts.

## Contexts

| Context | Owner | Read when |
| --- | --- | --- |
| `contexts/client/CONTEXT.md` | `apps/desktop-client` | Changing routes, windows, AA/MMT presentation, or client state |
| `contexts/backend/CONTEXT.md` | `services/halocue` and root Python compatibility code | Changing persistence, jobs, releases, adapters, or HTTP APIs |
| `contexts/ba-editor/CONTEXT.md` | `feature/1.1-ba-editor` | Changing BA import, node editing, validation, or StoryForge mapping |
| `contexts/ai-galgame/CONTEXT.md` | `feature/1.0-runtime` and later AI work | Changing providers, memory, TTS, tools, or dynamic dialogue |

## Shared references

- Cross-context contracts: `packages/contracts/`
- Canonical model: `packages/project-model/`
- Architectural decisions: `docs/adr/`
- Collaboration handoffs: `docs/handoffs/`
- GitHub issue conventions: `docs/agents/`
- Product direction: `docs/product-direction-1.x.md`
- Current repository layout: `docs/architecture/current-layout.md`
- Long-term memory and Skill governance: `docs/agents/long-term-memory.md`,
  `docs/agents/skill-proposals.md`
- Remote collaboration: `docs/agents/remote-collaboration.md`

## Change routing

If a change touches two contexts, define or update a versioned contract first,
add a migration if the wire shape changes, and add one end-to-end test proving
both contexts consume the same IDs and hashes.
