# Preview compilation coalescing tracer handoff

Date: 2026-08-27

## Outcome

Preview compilation now has an explicit coordinator between editor working
state and the preview runtime. Rapid project changes no longer rebuild the
Scene Descriptor, Render Timeline, Scene Performance Plan, and Preview Intent
on every React render.

The coordinator applies these rules:

- working-project changes enter a 72 ms latest-only window;
- a newer request cancels the older timer and becomes the only compilable
  snapshot;
- Scene, Cue, mode, or event address changes compile immediately;
- exact playhead changes rebuild only Preview Intent and reuse Scene Evaluation;
- finishing a gesture flushes its pending final snapshot immediately; and
- component disposal invalidates pending generations.

The generation check is retained even though compilation is currently
synchronous. This gives a stable boundary for moving compilation to a worker or
another asynchronous adapter later without permitting stale publication.

## Evaluation versus intent

A Preview Compilation contains both the Scene Evaluation and resolved Preview
Intent. When only mode, selected event, or exact playhead changes, the
coordinator reuses the existing evaluation object and rebuilds only the intent. Moving the
professional playhead therefore does not rebuild the descriptor, timeline, or
performance plan.

The iframe mounts immediately when a new evaluation is published. The former
second 140 ms mount timer was removed because the compilation coordinator now
owns coalescing. Intent-only publications continue through `applyIntent` on the
current Preview Session and do not remount stage media.

## Verification

Coordinator tests cover latest-only publication, commit-boundary flush,
evaluation reuse for intent-only changes, and cancellation on disposal.
Verification completed with 66 scene-editor tests and the production
TypeScript build, plus 35 focused Python/model/browser regression tests. The
whitespace check also passed.

## Remaining work

The independent autosave scheduler is now recorded in its later tracer and
uses editor revisions rather than preview generations. Further compilation work
should focus on worker execution only when profiling proves the synchronous
compiler exceeds the current short scheduling window.
