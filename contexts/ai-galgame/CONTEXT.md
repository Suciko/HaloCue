# AI GalGame context

## Responsibility

The AI GalGame workspace owns character cards, provider configuration, streaming
dialogue, memory, TTS, tool permissions, and dynamic scene proposals.

## Invariants

- Providers implement a common typed interface and report capabilities.
- Streaming can be cancelled; failed calls produce structured errors and do not
  create fake success records.
- Tool definitions are filtered by policy and execution is checked again at the
  executor boundary.
- Memory is durable, scoped, source-linked, and never silently treated as canon.
- Generated story changes are Proposals. User acceptance creates a new immutable
  Revision with a base revision and input hash.
- LingChat is an AGPL-3.0 reference implementation; its code is not copied into
  this MIT repository.
