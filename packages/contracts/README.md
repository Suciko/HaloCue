# Cross-context contracts

This package owns versioned JSON contracts shared by the client, backend, BA
editor, and adapters. A wire-shape change requires a new version or an explicit
migration plus consumer tests. Planned contracts include `halocue-project/1.0`,
`script-release/1.1`, `production-request/1.1`, `performance-draft/1.0`,
`build-bundle/1.0`, and `scene-descriptor/1.0`.

Resource manifests must identify the logical role, local URI, SHA-256, provenance,
and redistribution scope. A manifest reference is not a license grant and a
public contract example must use synthetic resources.
