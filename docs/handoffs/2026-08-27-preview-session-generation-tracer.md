# Preview Session generation tracer handoff

Date: 2026-08-27

## Outcome

The browser preview now has an explicit session boundary instead of relying on
cleanup timing alone. Every successful mount owns a monotonically increasing
generation and exposes it through its controller.

Mount follows a prepare/commit shape:

1. validate the descriptor and derive or validate its timeline and performance
   plan;
2. keep the current session alive if preparation fails;
3. dispose the previous valid session;
4. commit a new generation and attach its runtime work.

## Stale-work rule

A controller is current only while its generation still owns the shared stage.
Once replaced or disposed, its seek, play, pause, and advance commands are
inert. Delayed callbacks also verify ownership before mutating the DOM:

- background and actor image completion;
- realtime Spine ready/error completion;
- typewriter and playback animation frames;
- location-label and staggered entrance timers; and
- asynchronous resource-inspector clipboard feedback.

Calibration and resource-inspector handlers are now assigned per session and
released on disposal, avoiding listener accumulation across repeated mounts.

## Proof

The browser regression mounts a scene whose background response is deliberately
delayed, immediately replaces it with a second scene, then proves:

- the old controller reports stale and cannot seek the new stage;
- the delayed old background cannot overwrite the current background; and
- an invalid replacement performance plan is rejected without invalidating the
  current session.

Verification completed with 48 scene-editor tests and 61 Python/model/browser
integration tests. The TypeScript production build, Ruff, browser JavaScript
syntax check, and whitespace check also passed.

## Remaining work

This tracer owns browser-session lifetime only. Later Preview Session slices
still need explicit editor selection/seek intent, scene identity across the host
bridge, and removal of the live click-to-advance CSS compatibility path. The
Editor Transaction Module remains separate.
