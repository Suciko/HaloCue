# Cross-context contracts

This package owns versioned JSON contracts shared by the client, backend, BA
editor, and adapters. A wire-shape change requires a new version or an explicit
migration plus consumer tests. Current editor/render contracts include
`halocue-project/1.1`, `character-capabilities/1.0`, `scene-events/1.2`,
`render-timeline/1.2`, `scene-performance/1.4`, `scene-evaluation/1.5`,
`preview-intent/1.0`, `preview-intent/1.1`, and `render-sequence/1.1`.
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

The `scene-events/1.2` manifest is the shared event registry. It records which
events may enter the descriptor and deterministic timeline, whether an event
is visual-only, whether it supports non-blocking completion, its default
duration policy, and its simple-mode label. The TypeScript, Python, and browser
adapters read this manifest at their seams; they do not maintain independent
kind or duration tables. Version 1.2 adds the explicit `character-motion`
non-blocking capability while preserving the ordered event list as the source
of truth.

The `render-timeline/1.2` schema lives in
`render-timeline/1.2.schema.json`. It records deterministic, end-exclusive
frame ranges generated from a validated scene descriptor. Browser preview and
offline export consume the same event IDs, durations, and frame boundaries;
wall-clock callbacks are presentation controls, not part of this contract.
When `wait_for_completion` is false for a registry-supported event, the next
event starts at the same sequential cursor and `total_frames` is the maximum
end frame across all events. Every normalized timeline event exposes the
boolean completion policy.

The current `scene-performance/1.4` schema lives in
`scene-performance/1.4.schema.json`. It is the renderer-independent animation
plan compiled from authored scene events. It defines deterministic stage shake
plus character opacity, vertical-offset, and scale contributions with explicit
target/channel/value-space metadata, exact frame ranges, and one-to-many
source-event mapping. It also defines seek-safe numeric keyframes for character
motion: additive offset/rotation for `motion/nod`, and factor opacity/scale plus
additive offset for `motion/appear`.
Preview and export sample this plan even when wall-clock CSS animation is
disabled. `scene-performance/1.0` through `1.2` remain historical predecessors.

The current `scene-evaluation/1.5` schema lives in
`scene-evaluation/1.5.schema.json`. It binds a descriptor, timeline, performance
plan, and non-fatal diagnostics for namespaced
professional events that a presentation adapter does not render yet. The
editor, browser preview, and offline adapters can therefore share one explicit
intermediate result without duplicating canonical project data. It also reports
an explicit motion whose target character is not occupying the requested slot.

The `preview-intent/1.0` schema lives in `preview-intent/1.0.schema.json`. It
turns editor Cue/event selection into an explicit scene identity and exact
timeline frame. Cue selection resolves to the Cue's completed state; event
selection resolves to the event start. A selected extension event that is not
renderable records an explicit prior-renderable or scene-start fallback instead
of silently seeking an unrelated frame.

The additive `preview-intent/1.1` schema lives in
`preview-intent/1.1.schema.json`. It retains Cue/event intent and adds a
`playhead` selection with `explicit-frame` resolution and `exact` alignment.
Professional timeline scrubbing can therefore seek a deterministic
intermediate animation frame without changing project data or inventing an
event selection.

The `render-sequence/1.1` manifest binds a resumable numbered PNG sequence to
the SHA-256 of its descriptor, timeline, and performance plan. A sequence can
reuse verified frames after interruption, but never mix frames from different
render inputs.

At runtime a user may select an AA installation or an explicitly authorized
pack. The importer verifies the selected file's SHA-256 and may stage a copy in
the user's local project/cache directory. The staged bytes remain user data and
are never committed, bundled into a public release, or used as a license grant.
Public fixtures use placeholders so CI stays deterministic.
