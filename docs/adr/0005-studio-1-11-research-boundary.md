# ADR-0005: Studio 1.11 research boundary and evidence tiers

- Status: accepted
- Date: 2026-08-24

## Decision

HaloCue uses the locally unpacked Studio 1.11 installation as read-only
compatibility evidence. The unpacked files stay outside this repository. HaloCue
may independently implement the observed project structure, runtime behavior,
extension boundaries, save semantics, and resource lookup rules, but does not
import recovered source or production bundles into the product tree.

Research evidence is classified before it affects an implementation:

1. **Licensed upstream source** has a repository URL, immutable commit, and a
   verified license covering the file. It may be reused only as that license
   permits, with attribution and provenance recorded in the implementing PR.
2. **Installed public contracts** are readable SDK types, schemas, manifests,
   and documented extension identifiers needed for interoperability. They may
   guide a compatible, independently written adapter. Their source path and
   SHA-256 are recorded in `docs/research-inputs.sha256`.
3. **Recovered implementation evidence** includes beautified bundles, source
   map `sourcesContent`, decompiled output, and bytecode observations. It is
   behavior evidence only. HaloCue records observations and writes new code from
   its own contracts and tests instead of copying implementation bodies.
4. **Unlicensed comparison projects** may demonstrate behavior or architecture,
   but no code is reused until a license and immutable revision are verified.
5. **Game and application assets** remain local user data. Art, audio, models,
   fonts, databases, bundles, and other payload bytes are not committed or
   redistributed without explicit permission covering those exact files.

The `@avgplus/engine` package metadata in the installed 1.11 snapshot declares
MIT. That declaration is useful provenance evidence for the package, but it is
not assumed to grant rights to every bundled dependency, recovered source file,
font, model, image, audio file, or third-party comparison project. File-level or
upstream provenance is still required before reuse.

Studio's JSON block shape and extension system inform the StoryForge adapter:
blocks have stable IDs, types, properties, and children; extension and action
identifiers are namespace-qualified; project persistence is atomic; resource
resolution uses logical paths; and each preview/export computes a complete
asset closure. These are adapter concerns. `HaloCueProject` remains the
canonical product model, and StudioProject v2 remains an exchange/render format.

## Context

Studio 1.11 contains useful evidence for a less technical editing workflow and
for deterministic preview/export behavior. Parts of the installation are
readable TypeScript while other parts are compiled production output. A package
license alone does not establish the provenance of every file in an installer.

HaloCue also needs an AA-style result close to the observable BA presentation.
ADR-0004 permits reproducing coordinates, timing, logical resource keys, and
relative lookup locations while keeping proprietary resource bytes outside the
public repository. This ADR applies the same separation to Studio research.

## Consequences

- Studio research must produce a contract, test, or written observation before
  it changes product code.
- Adapter fixtures are synthetic and contain no extracted Studio or BA payloads.
- Stable interoperability names may appear in contracts; implementation bodies
  from recovered files do not.
- Preview and offline export must evaluate the same normalized block IR and
  resource closure deterministically.
- Missing provenance blocks code or asset reuse, but does not block an
  independently implemented compatibility layer.

## Alternatives considered

- **Treat the whole installer as MIT:** rejected because bundled and recovered
  files can have separate origins and licenses.
- **Ignore the installed contracts:** rejected because independently supporting
  observable open formats and identifiers is necessary for interoperability.
- **Make StudioProject v2 canonical:** rejected because it would couple HaloCue
  editing, MMT, AI proposals, and save state to one renderer's format.

## Migration and rollback

Existing contracts remain valid. New Studio-derived adapter fields must identify
their evidence tier and use versioned schemas. If provenance is later disproved,
remove the affected reuse, retain independently specified behavior where lawful,
and migrate projects through the versioned adapter boundary.
