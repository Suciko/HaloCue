# HaloCue 1.x product direction

- Status: accepted direction
- Last reviewed: 2026-08-24
- Owner: HaloCue maintainers

This document is the product north star for 1.x. It answers why the product is
being built and what a release is allowed to optimize for. Architecture details
belong in `docs/adr/`; implementation work belongs in GitHub Issues and PRs.

## Release positioning

| Line | Role | Product promise |
| --- | --- | --- |
| `0.95` | historical baseline | The existing project compiles and remains reproducible. |
| `1.0` | compatibility/runtime assistant | Help authors produce and preview AA-style work while preserving an AA edge adapter. |
| `1.1` | independent video-first studio | Replace AA as the primary authoring workflow with a simpler, faster editor and deterministic video export. |
| `1.2` | AI narrative product | Add AI GalGame behavior, dynamic MMT events, memory, relationships, and proposal-based generation. |

The version number describes product responsibility, not a promise that every
feature of the reference applications will be copied.

## 1.1 north star

The primary artifact is a video for a platform. A packaged, playable GalGame is
not the default deliverable.

- Main GalGame/AVG performance: `16:9` landscape video.
- Mixed AVG plus MMT performance: `16:9` landscape video.
- MMT-only performance: `16:9` landscape or `9:16` portrait video.
- Export is a deterministic headless render pipeline, followed by audio muxing
  and FFmpeg encoding. Desktop screen recording is a debugging fallback, not
  the canonical export path.
- AA/AAP compatibility remains an import, preview, and optional export edge.
  `HaloCueProject` is never shaped around AAP limitations.

### AA-compatible stage layout

The 1.1 editor exposes **five visible portrait positions**, numbered `1` to
`5`, matching the existing AA runtime and compiler validation. AAP keeps a
six-entry `characters` array for serialization, but entry `0` is the
no-portrait narrator/off-screen speaker slot; it is not a sixth visible
position. Product copy, editor controls, validation, and export documentation
must call this “five visible positions” and must not describe it as a
six-position stage.

The ordinary-user workflow should begin with a clear scene, characters, and
timeline rather than exposing every advanced Studio-style property at once.
Advanced node, event, resource, and export controls remain available through an
explicit advanced mode.

## MMT as a presentation channel

MMT is a sidecar presentation over the same story, variables, resource IDs, and
save state. It is not a second project format.

In a mixed performance, an MMT cue can show a notification icon, vibration, and
sound; open a phone with an authored transition; freeze, dim, or blur the main
stage; play the message sequence; and close back into the stage. The cue records
whether it is optional, auto-open, interrupting, background, or standalone.

MMT-only mode disables main-stage components at render time so the renderer does
not spend power maintaining hidden GalGame state. It supports separate landscape
and portrait layout templates without duplicating the authored conversation.

## AI boundary

AI operates above the renderer:

```text
StoryIntent -> PerformancePlan -> SceneDescriptor/VideoComposition
            -> HaloCue renderer -> AAP/MMT/video adapters
```

AI may propose beats, dialogue, emotion, camera intent, MMT cues, and alternate
performances. It must not author raw AAP commands, physical resource paths, or
an unbounded script that bypasses validation.

The only path from generated content to a release is:

```text
Proposal -> schema/capability/resource checks -> preview -> human decision
          -> immutable Revision -> deterministic export
```

AI memory and generated proposals are evidence or candidates. They do not
override this direction, an accepted ADR, a versioned contract, or an explicit
maintainer decision.

## Change test

When a new idea is proposed, ask:

1. Does it improve the video-first authoring or viewing workflow?
2. Does it preserve one canonical project model and the AAP edge adapter?
3. Does it keep MMT composable without duplicating the story?
4. Does it reduce author effort or rendering cost without hiding control from
   advanced users?
5. Can it be implemented as a bounded vertical slice with observable tests?

If an idea changes these answers, record it as a product proposal and update
this document only after human review. A conversation or local AI memory is not
an accepted product decision.

## Evidence and provenance

AzureArchive, ChatArchive, LingChat, Studio 1.11, and related decompiled or
unpacked material are behavior evidence only. Observable layout and interaction
can guide independent implementations; proprietary bytes and recovered
implementation bodies stay in local research storage. See ADR-0003, ADR-0004,
and ADR-0005.
