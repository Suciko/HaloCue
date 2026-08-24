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
