# HaloCue repository layout

This repository is the formal Git source for HaloCue. The 0.9/0.95 Python
compatibility surface remains at the repository root while the 1.x migration is
implemented on feature branches.

## Current layout

```text
HaloCue/
├── apps/desktop-client/       1.x Tauri/React client boundary
├── services/halocue/          1.x local service boundary
├── packages/project-model/    canonical HaloCueProject model
├── packages/contracts/        versioned cross-context contracts
├── contexts/                  context-owned invariants
├── docs/                      direction, ADRs, handoffs, migration records
├── legacy/0.9/                0.9 historical boundary documentation
├── tests/                     root 0.9 compatibility tests until migration
└── root Python modules        0.9/0.95 compatibility surface
```

## Branch ownership

```text
main                    stable reviewed integration
release/0.95            immutable 0.95 release history
feature/1.0-runtime     maintainer's 1.0 migration and runtime slices
feature/1.1-ba-editor   collaborator's BA editor slices
chore/contracts         shared model, schema, ADR, and governance slices
```

The old local 1.0 workspace is not copied into `legacy/0.9` and is not a
second source tree. Its migration sources are recorded in
`docs/version-lineage.md` and the local archive map. Each migrated slice must
have a GitHub Issue, a focused commit, tests, and a handoff.

## Source mapping for 1.0 migration

| Old archive source | New ownership boundary |
| --- | --- |
| `07-正式版产品设计` | `contexts/`, `docs/adr/`, and versioned contracts |
| `08-HaloCue-1.0` production backend | `services/halocue/` adapters and production jobs |
| `09-HaloCue-1.0-Writing` writing backend | contracts and later writing service slices |
| `10-HaloCue-1.0-Integrated` composition root | client/service integration tests and adapters |
| `11-HaloCue-1.0-后端协作交接包` | `docs/handoffs/` evidence only |

The mapping is intentionally a boundary, not a permission to copy all old
source files at once. The canonical model and contracts are established first;
then each vertical slice moves behavior and tests into its owner.
