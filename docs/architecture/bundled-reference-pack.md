# Bundled reference pack 1.0

The maintainer authorized inclusion of the full curated character reference cards
and official staging dataset on 2026-10-02. `data/reference-pack/README.md` and its
`halocue-reference-pack/1.0` manifest define the provenance and non-MIT data scope.
The source index/export and PyInstaller data list include this exact directory.
No user works, private settings or game media are selected.

The writing service reads the bundled compressed corpus by default. Explicit
`official_corpus_dir` / `HALOCUE_BA_CORPUS_DIR` retains precedence. Both JSONL and
gzip JSONL remain supported. Stable record IDs and evidence URIs still identify
original source records; imported excerpts are work-owned copies.

Read-only HTTP additions under the existing `/api/v1` envelope:

- `GET /reference-characters/search?q=...`: `{available, items}`; each item has
  `id`, `name`, `aliases`, `summary`, and `source_kind=maintainer_curated_reference`.
- `GET /reference-characters/{url-encoded-id}/file`: the existing character-card
  import payload `{filename, content_base64, source_label}`. IDs resolve against
  enumerated files, never a client-supplied filesystem path.

The reference search/import screen retains its validation dialog and explicit
import action. Maintainer clarification on 2026-10-04 additionally authorizes
automatic reuse during author discussion: complete names and unambiguous aliases
in work/chapter messages select existing curated references, validate them with
the same importer, and copy missing cards into that work before the fixed model
context is assembled. This is reuse of existing source material, not AI-authored
canon. Repeated mentions preserve stable cards/revisions; existing custom,
unconfirmed and archived cards are never overwritten or restored automatically.
Ambiguous identities and unavailable/invalid references are reported in the
conversation. Explicit exclusions and requests to disable automatic card reuse
are respected for the message. When the author requests prose, recent original
author messages can supply previously mentioned names; assistant suggestions
and external attachment text do not select new cards automatically.

The optional `character_resolution` receipt in discussion content and its fixed
input uses [character-reference-resolution/1.0](../../services/halocue/writing/docs/contracts/character-reference-resolution-1.0.schema.json).
Old messages remain readable without a data migration. The receipt projects only
actual source-copy results, and is displayed as a compact author-facing card.
Non-explicit scene selection resolves brief character names through unique full
names/canonical names/aliases; shared aliases stay blocked. Explicit Scene IDs
and character-card selections retain their existing boundaries. Prompt assembly
continues to project selected work cards rather than send the full library to
the model. Generated settings, scene contracts and prose retain the existing
Proposal/Revision decision path.

`tools/verify_reference_pack.py` checks every compressed and uncompressed hash,
compares scenario shards to their original extraction manifest, and counts all
records and cards. Release scanning inspects decompressed JSON/JSONL as well as
plain cards. Compressed streams have finite per-line and total-byte limits;
only the three named reference shards receive a 64 MiB ZIP-member allowance.

## Complete research seed (2026-10-05)

The maintainer requested the later background/expression research be included.
`research/metadata.jsonl.gz` losslessly serializes the sanitized public metadata
database; `research-seed.json` records source/base/payload digests and row counts.
It includes 27649 face visual annotations (semantic/observation/backend/manual),
6850 scene visual annotations and 163998 official face usage records, preserving
resource, skeleton and outfit identity. Scene research is restricted to
`official_base` and `extra_pack` provenance. Installation/project tables remain
empty; physical paths, head images and private JSON fields are removed.

`bundled_metadata.materialize_bundled_metadata` verifies the base and compressed
payload hashes, reconstructs a transactional user-cache database, checks every
table count, and publishes the cache atomically. Subsequent launches reuse it.
The immutable application directory is never written. Legacy catalogs receive
missing rows after a local SQLite backup, without replacing existing user rows.
Writing's bundled-only projection refreshes when the seed digest changes;
explicitly imported catalogs and user override records remain authoritative.
Background lookup now prioritizes explicit author corrections over differently
cased research entries for the same logical key.

The work library identifies its counts as adopted work data and exposes bundled
character browsing directly. Capability data supplies the actual installed card
count. A simple author continuation can reuse recent original author mentions
from older conversations; assistant suggestions/attachments remain excluded.
