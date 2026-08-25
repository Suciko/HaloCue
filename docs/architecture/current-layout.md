# HaloCue repository layout

`main` is the current 0.95 public release line. The repository keeps the
Python compatibility surface at the root while release tooling, tests, and
documentation stay in separate top-level folders.

## Current layout

| Path | Responsibility |
| --- | --- |
| root Python modules | 0.9/0.95 compatibility surface and desktop runtime |
| `release_tools/` | public source export, bundle build, manifest, and scan helpers |
| `tools/` | release gates, verification, and source-cleanliness checks |
| `tests/` | packaging, workflow, runtime, and release smoke tests |
| `docs/` | release lineage, architecture notes, and private-release guidance |
| `branding/`, `css/`, `js/`, `ui.html` | shipped UI and branding surface |
| `data/halocue_labels.db` | desensitized public seed database |

## Branch ownership

| Branch | Role |
| --- | --- |
| `main` | reviewed 0.95 public release line |
| `release/0.95` | preserved 0.95 release history |
| `feature/1.0-runtime` | separate 1.0 migration work |
| `feature/1.1-ba-editor` | separate 1.1 editor work |

Public exports are derived from the Git index. Private source material, local
paths, generated assets, user data, and unreviewed 1.x work therefore remain
outside the canonical public source tree.
