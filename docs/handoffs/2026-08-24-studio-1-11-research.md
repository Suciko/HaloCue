# Handoff: Studio 1.11 research boundary

## Delivery

- Branch: `chore/contracts`
- Research boundary commit: `888b9c1`
- Contract PR: `#19`
- Architecture decision: `docs/adr/0005-studio-1-11-research-boundary.md`
- Evidence inventory: `docs/research-inputs.sha256`
- Related issues: `#8`, `#13`, `#14`

## Research snapshot

The maintainer supplied an unpacked Studio 1.11 installation as a read-only
local research input. The snapshot includes extracted application files,
beautified production bundles, readable SDK TypeScript contracts, recovered
default-shell source, upstream comparisons, and an independent Rust/Bevy
comparison project. None of those files were copied into HaloCue.

Four contract-level evidence files were hashed in the research inventory:

- Studio project schema
- JSON block schema
- save schema
- default-shell extension manifest

The original installer ZIP was not present at its previously recorded path and
was not re-hashed. This does not affect the four unpacked-file hashes.

## Decisions carried forward

- `HaloCueProject` remains canonical; StudioProject v2 is an adapter format.
- The adapter uses a normalized JSON block IR with stable IDs, types, properties,
  children, metadata, and variables.
- Extension/action identifiers and adapter resource keys are namespaced.
- Resource paths are logical and adapter-relative. Preview/export computes and
  validates the complete asset closure before evaluation.
- Preview and offline export consume the same deterministic descriptor stream.
- Recovered source and bundles remain behavior evidence only unless their exact
  upstream source, immutable revision, and license are verified.

## Product and license boundary

The installed `@avgplus/engine` package metadata declares MIT, but that does not
automatically cover all bundled dependencies, recovered files, fonts, audio,
models, images, or comparison projects. Public fixtures remain synthetic. Real
BA/AA resource bytes are loaded only from a user-owned or explicitly authorized
local manifest under ADR-0004.

## Verification

The four SHA-256 values in `docs/research-inputs.sha256` were recomputed from the
local unpacked snapshot on 2026-08-24. Documentation formatting and repository
boundary checks should run in CI; this handoff adds no executable product code.

## Next owner actions

1. Define a versioned normalized block IR and round-trip fixtures under the
   shared contracts stream.
2. Implement asset-closure validation before the first deterministic preview.
3. Keep adapter extensions namespace-qualified and report unknown actions as
   structured diagnostics.
4. Attach upstream URLs, commits, and licenses before reusing any source rather
   than independently implementing its observed contract.
