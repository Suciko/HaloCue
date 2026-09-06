# ADR-0002: Repository and ownership streams

- Status: accepted
- Date: 2026-08-24

## Decision

`Suciko/HaloCue` remains the unified MIT repository. Existing 0.9 code is kept
as the compatibility surface while 1.x work is organized under explicit
contexts and packages. Runtime/client work uses `feature/1.0-runtime`; BA editor
work uses `feature/1.1-ba-editor`; shared contracts use `chore/contracts`.

## Consequences

Handoffs are PRs with tests and contract notes, not archive replacement. Large
research inputs remain outside the public repository. A future split requires a
new ADR and a migration plan.
