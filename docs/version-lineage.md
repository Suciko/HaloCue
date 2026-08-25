# Version lineage and migration evidence

This repository keeps the 0.9/0.95 public source line on `main` and records
the 0.95 release history separately from the 1.x migration branches.

## Public snapshots

| Snapshot | Commit | Meaning |
| --- | --- | --- |
| `0.9-baseline` / `v0.9.3` | `b68da0671c80e61429bb2f034f7263d68a07d895` | Historical 0.9 compatibility anchor on `main` |
| `v0.95` | `4956a64c1cd31886ee915cea8293b0490a0b59fc` | First public 0.95 release snapshot |
| `v0.95-r12` | `9ae1f9967860672367576c7a5e209f96143bcc38` | 0.95 iteration 12 |
| `v0.95-r15` | `e8c40d61f8bfd145729a8160e2ab3a2a3c0438df` | 0.95 iteration 15 |
| `v0.95-r23` / `0.95-compile-baseline` | `df41f13795dd24d58736286531dc6e845795accf` | Latest public and compile-baseline snapshot |

`v0.95-r23` and `0.95-compile-baseline` both point to `df41f13`. The release
line is evidenced by the stable tag family, the compile baseline, and the
published GitHub Releases for `v0.95`, `v0.95-r12`, `v0.95-r15`, and
`v0.95-r23`.

## Migration rule

`origin/main` (`b68da06`) and `origin/release/0.95` (`df41f13`) have no common
ancestor. This PR therefore uses an explicit, reviewable compatibility
transplant into a new migration branch. It does not fast-forward, overwrite,
force-push, or rewrite either existing branch.

`release/0.9.4.5` (`2a6e532`) is historical and is not a migration source.
The existing `0.9-baseline`, `v0.9.3`, and all 0.95 tags remain immutable.

This PR generates a new 0.95 mainline snapshot from the reviewed `main`
compatibility surface; its commit will therefore be new and will not equal
`df41f13`. It does not copy the unrelated `release/0.95` tree. That tree is a
large 126-file divergence and includes release-specific Spine/runtime material
outside this migration's scope. Keeping it as evidence rather than merging it
avoids importing private or 1.x work and keeps the change reviewable.

The impact is that the new mainline snapshot has no automatic ancestry to
`release/0.95`; the exact source commit and tag mapping above remain the
reproducible release evidence. Rollback is a normal revert of the PR merge,
which returns `main` to `b68da06` without moving or deleting any tag. No
force-push or history rewrite is required.

## Release ownership

After this migration is reviewed, `main` is the current formal 0.95 release
line. The migration branch is intentionally a compatibility/version-line
snapshot, not a code merge from `release/0.95`. `release/0.95` remains the
preserved release history, while
`feature/1.0-runtime` and `feature/1.1-ba-editor` remain separate development
lines and are not merged by this work.
