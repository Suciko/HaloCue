# Domain documentation rules

This repository uses the multi-context layout described by `CONTEXT-MAP.md`.

Before exploring a change, read `CONTEXT-MAP.md`, the relevant context file under
`contexts/`, and ADRs under `docs/adr/`. Use the domain terms defined there in
issue titles, code, tests, and handoffs. If a change crosses contexts, update a
versioned contract and record the decision in an ADR before implementation.

Context documents explain ownership and invariants. They do not duplicate
commands or configuration that can be read directly from the environment.
