# ADR-0004: AA presentation compatibility and user-provided assets

- Status: accepted
- Date: 2026-08-24

## Decision

HaloCue may independently implement the observable presentation contract used by
the AA-style Blue Archive display: slot coordinates, layer ordering, luminance,
movement timing, typewriter behavior, dialogue labels, transitions, audio cues,
and resource lookup semantics. These values are treated as compatibility data
and are documented with their evidence source.

The runtime accepts resource IDs and local paths supplied by the user or by an
explicitly authorized asset pack. It records observable adapter keys and
relative resource locations in `resource-manifest/1.0`, verifies hashes, and
may stage a verified copy in the user's local project/cache directory. Physical
bytes remain outside the public source tree. Public fixtures use synthetic
placeholders.

The public repository does not ship Blue Archive or AzureArchive art, audio,
models, textures, AssetBundles, databases, or private/reverse-engineered source.
It does not copy AA private project files or reproduce its implementation. A
future importer must be explicit, opt-in, path-validated, and local-only unless
separate redistribution permission is documented. Copying an observed logical
key, slot coordinate, or relative location is compatibility data; copying the
underlying proprietary bytes is a separate provenance and redistribution
decision.

## Context

Matching the official-looking presentation requires the same visible layout and
resource roles. The exact game resources are copyrighted and their provenance
cannot be assumed from a local installation or a decompiled directory.

## Consequences

- A user with authorized resources can approach the official visual result by
  importing them into a local resource manifest.
- CI and public releases remain reproducible using placeholder resources.
- Presentation code and resource adapters can be tested independently of asset
  ownership.
- Requests to commit a real game asset, bundle, or copied private file block on
  provenance and redistribution approval.
