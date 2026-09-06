# Cross-context contracts

This package owns versioned JSON contracts shared by the client, backend, BA
editor, and adapters. A wire-shape change requires a new version or an explicit
migration plus consumer tests. Planned contracts include `halocue-project/1.0`,
`script-release/1.1`, `production-request/1.1`, `performance-draft/1.0`,
`build-bundle/1.0`, and `scene-descriptor/1.0`.

Resource manifests must identify the logical role, local URI, SHA-256, provenance,
and redistribution scope. A manifest reference is not a license grant and a
public contract example must use synthetic resources.

The `resource-manifest/1.0` schema lives in
`resource-manifest/1.0.schema.json`. Its `lookup` object records observable
adapter data such as an AA logical key and relative resource location. This is
the compatibility boundary needed for an official-looking presentation; it is
not a copy of an application implementation or a machine-specific absolute
path.

At runtime a user may select an AA installation or an explicitly authorized
pack. The importer verifies the selected file's SHA-256 and may stage a copy in
the user's local project/cache directory. The staged bytes remain user data and
are never committed, bundled into a public release, or used as a license grant.
Public fixtures use placeholders so CI stays deterministic.
