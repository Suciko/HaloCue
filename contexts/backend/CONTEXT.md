# Backend context

## Responsibility

The backend owns durable project state, immutable writing revisions, production
runs, adapter capabilities, asset manifests, background jobs, and the local
service boundary. Root Python modules are the 0.9 compatibility surface while
`services/halocue` is the planned 1.x boundary.

## Invariants

- Production consumes a frozen `ScriptRelease`, never a mutable writing draft.
- `ProductionRequest`, `PerformanceDraft`, and `BuildBundle` carry versioned
  schemas and input hashes.
- Long jobs are resumable and idempotent; late results cannot mutate newer state.
- The service listens on localhost by default and never exposes API keys to the
  browser.
- StoryForge and AA are adapters selected by declared capabilities.

## Existing compatibility

The 0.9 root modules and tests remain the baseline. Migration into the 1.x
service is incremental; do not copy the root implementation into a second
package without an explicit ownership decision and regression coverage.

## Language

**Teacher Identity**:
The production-local presentation identity shared by explicitly bound teacher
speakers. Its display name and organization may change without replacing the
identity; it does not redefine a writing-owned character.
_Avoid_: narrator, slot zero

**Teacher Binding**:
An explicit association between a source speaker and the task's Teacher
Identity. Several source spellings may refer to the same identity without
changing the source dialogue.

**No-Portrait Character**:
A named speaking character without a visible portrait. A Teacher Identity uses
this representation for ordinary dialogue, but not every no-portrait character
is a teacher.
