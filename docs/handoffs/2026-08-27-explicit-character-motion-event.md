# Explicit character motion event handoff

Date: 2026-08-27

## Scope

Issue: #24, `[Phase 2] Integrate collaborator BA editor through reviewed slices`

PR: #27, `feat(1.1): add canonical dual-mode BA scene editor`

This vertical slice replaces newly authored motion stored on persistent actor
state with an ordered `character-motion` event. It carries the event through
the editor, deterministic timeline, performance compiler, browser preview,
offline Python adapter, evaluation diagnostics, and capture tests.

## Contract decisions

- `scene-events/1.1` registers `character-motion` as a renderable,
  timeline-supported, visual-only event with a 500ms default duration.
- `render-timeline/1.1` schedules the new event kind using the same stable,
  end-exclusive frame semantics as other authored events.
- `scene-performance/1.3` extends numeric keyframes to opacity, vertical offset,
  scale, and rotation; value spaces may be absolute, relative, or factors.
- `scene-evaluation/1.4` binds the new timeline/performance versions and reports
  `scene.character_motion_target_unavailable` at the stable
  `event:<event_id>` path when the target does not occupy its slot.
- Existing `enter.motion_id` and `dialogue.motion_id` remain readable and
  compilable. New Inspector edits remove local legacy carriers and author the
  explicit event instead.

## Editor behavior

- Simple Inspector motion trials use the existing cancel-on-interrupt
  transaction. Hover/focus previews the candidate without history; click
  commits one project revision.
- Selecting a non-idle motion creates or updates one stable explicit motion
  event. Selecting idle removes the transient event; undo restores its ID.
- The event is inserted after the target character enters and before it exits.
  Professional insertion automatically moves to the nearest valid occupied
  position instead of silently compiling an impossible target.
- Professional mode exposes typed slot, character, and capability-aware motion
  controls, plus the summary `#slot · motion/id`.
- Preview trials locate the compiled generic motion operation and play only its
  bounded frame range.

## Motion behavior

- `motion/nod` keeps the shared offset/rotation keyframes and strong ease.
- `motion/appear` preserves the established visual poses: opacity factor
  `0.55 -> 1`, vertical offset `10 -> -3 -> 0`, and scale factor
  `0.985 -> 1.01 -> 1`, using the emphasized ease-out token.
- Keyframes compose with entrance contributions by multiplying opacity/scale
  factors and adding positional offsets.
- Play and sample are seek-safe. Skip and reduced motion omit transient motion
  operations and leave a clean baseline.
- Browser rendering resets prior inline performance state before applying each
  sampled frame, so reverse or discontinuous seeks cannot retain stale opacity.

## Verification

- Frontend: 22 Vitest files, 129 tests passed.
- Frontend production build: passed.
- Focused Python contract/model/export tests: 48 passed.
- Focused Playwright deterministic capture tests: 2 passed.
- Cross-runtime parity covers enter, nod rise/peak/recovery, appear
  rise/overshoot/recovery, shake, and exit frames.
- Repository-wide Python regression: 2195 passed, 14 skipped in 589.41s.

## Known next gaps

- The timeline remains sequential. Mature Studio-like editing needs explicit
  parallel/overlap semantics, track ownership, collision rules, and interval
  manipulation before multiple effects can be composed visually in one range.
- Background pan, hit effects, emoticon pop, dialogue-panel motion, and several
  legacy CSS pulses still need migration into the same performance protocol,
  one tracer bullet at a time.
- Motion discovery and parameters are still capability presets, not a full
  keyframe editor. The protocol now provides the seam for that later work.

## Safety and repository state

No Studio, AA, decompiled application, or real game resource bytes were copied.
Only observed interaction and motion semantics were independently implemented.
Unrelated user-owned changes in `AGENTS.md`, `CONTEXT-MAP.md`,
`contexts/ba-editor/CONTEXT.md`, and the three untracked long-term research
documents remain outside this slice and must not be staged.
