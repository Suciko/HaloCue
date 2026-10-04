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
