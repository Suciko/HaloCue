# Cross-context contracts

This package owns versioned JSON contracts shared by the client, backend, BA
editor, and adapters. A wire-shape change requires a new version or an explicit
migration plus consumer tests. Current editor/render contracts include
`halocue-project/1.1`, `character-capabilities/1.0`,
`render-timeline/1.0`, `scene-evaluation/1.0`, and `render-sequence/1.0`.
Planned contracts include
`script-release/1.1`, `production-request/1.1`, `performance-draft/1.0`,
`build-bundle/1.0`, and `scene-descriptor/1.0`.

Resource manifests must identify the logical role, local URI, SHA-256, provenance,
and redistribution scope. A manifest reference is not a license grant and a
public contract example must use synthetic resources.

The `resource-manifest/1.0` schema lives in
`resource-manifest/1.0.schema.json`. Its `lookup` object records observable
adapter data such as an AA logical key and relative resource location. This is
the compatibility boundary needed for an official-looking presentation; it is
not a copy of an application implementation or a machine-specific absolute
path.

The cue-based canonical project schema lives in
`halocue-project/1.1.schema.json`. Both editor modes operate directly on this
shape: simple mode projects one Cue into a low-cost task flow, while
professional mode exposes the same Cue's ordered events and advanced fields.
The deterministic `halocue-project/1.0 -> 1.1` migration is owned by
`packages/project-model`.

The `character-capabilities/1.0` schema stores stable expression, motion,
emoticon, and transition state IDs. Adapter-specific animation names stay in
namespaced logical fields; local resource paths remain outside the project.

The `render-timeline/1.0` schema lives in
`render-timeline/1.0.schema.json`. It records deterministic, end-exclusive
frame ranges generated from a validated scene descriptor. Browser preview and
offline export consume the same event IDs, durations, and frame boundaries;
wall-clock callbacks are presentation controls, not part of this contract.

The `scene-evaluation/1.0` schema lives in
`scene-evaluation/1.0.schema.json`. It binds a descriptor and its timeline
evaluation to one scene and carries non-fatal diagnostics for namespaced
professional events that a presentation adapter does not render yet. The
editor, browser preview, and offline adapters can therefore share one explicit
intermediate result without duplicating canonical project data.

The `render-sequence/1.0` manifest binds a resumable numbered PNG sequence to
the SHA-256 of its descriptor and timeline. A sequence can reuse verified
frames after interruption, but never mix frames from different render inputs.

At runtime a user may select an AA installation or an explicitly authorized
pack. The importer verifies the selected file's SHA-256 and may stage a copy in
the user's local project/cache directory. The staged bytes remain user data and
are never committed, bundled into a public release, or used as a license grant.
Public fixtures use placeholders so CI stays deterministic.
