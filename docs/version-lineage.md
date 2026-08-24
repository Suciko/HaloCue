# Version lineage and migration evidence

This document separates release history, compile evidence, and runtime
integration evidence. A tag is a source snapshot; it is not automatically a
claim that every later workspace has been merged into `main`.

## Public source snapshots

| Snapshot | Commit | Meaning | Evidence status |
| --- | --- | --- | --- |
| `0.9-baseline` | `b68da06` | Historical 0.9 compatibility anchor on `main` | Reproducible Git tag |
| `v0.9.3` | `b68da06` | Public 0.9.3 source snapshot | Reproducible Git tag |
| `v0.95` | `4956a64` | 0.95 release seed | Reproducible Git tag and release |
| `v0.95-r12` | `9ae1f99` | 0.95 iteration 12 | Reproducible Git tag |
| `v0.95-r15` | `e8c40d6` | 0.95 iteration 15 | Reproducible Git tag |
| `v0.95-r23` | `df41f13` | Latest public 0.95 release snapshot | Reproducible Git tag and release |
| `0.95-compile-baseline` | `df41f13` | Maintainer-confirmed compilable 0.95 source | Reproducible Git tag; CI build evidence pending |

`v0.95-r23` is on the separate `release/0.95` history and is not an ancestor
of the current `main`. The migration must therefore import its behavior through
an explicit compatibility slice instead of pretending that a fast-forward is
available. The `0.9-baseline` tag remains immutable so existing links and
checksums keep their meaning.

## 0.95 compile baseline

The maintainer confirms that the 0.95 release can be compiled successfully.
Until the command and tool versions are captured in CI, this is recorded as
maintainer evidence rather than a new CI claim. The migration issue must attach:

- the exact source commit (`df41f13795dd24d58736286531dc6e845795accf`);
- the Windows build command and Python/dependency versions;
- the produced archive name and SHA-256;
- a clean-machine smoke result for launch and one representative compile.

The source and archive remain outside this repository unless their normal
license and redistribution scope permits publication.

## 1.0 runtime baseline

The maintainer confirms that the local HaloCue 1.0 integration workspace runs.
The workspace is a research and migration input, not a second public source
tree. Before code is promoted into `apps/desktop-client` or `services/halocue`,
the receiving slice must record:

- the source archive/workspace identifier and commit or handoff record;
- the start command and port/window behavior;
- a smoke path covering project load, one scene, and recovery;
- tests copied as tests, not as an unreviewed source-tree replacement;
- known differences from the 0.9 compatibility surface.

## Migration gates

1. Keep the 0.9 compatibility suite runnable while importing 0.95 behavior.
2. Convert 0.95 resource behavior into `HaloCueProject` and the versioned
   resource manifest; never make an absolute developer path a contract field.
3. Import the 1.0 runtime behind the shared contracts and prove one AA/MMT
   state can round-trip before adding the BA editor.
4. Record every accepted difference in an ADR or handoff rather than silently
   overwriting an earlier baseline.
