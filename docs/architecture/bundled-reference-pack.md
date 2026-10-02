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

The client opens the existing validation dialog. Only the author's subsequent
import action calls the existing version-checked `character-cards:import` flow.
No schema migration, automatic work-card seeding or canon mutation is introduced.
Prompt assembly continues to project selected work cards rather than send the
full reference library to the model.

`tools/verify_reference_pack.py` checks every compressed and uncompressed hash,
compares scenario shards to their original extraction manifest, and counts all
records and cards. Release scanning inspects decompressed JSON/JSONL as well as
plain cards. Compressed streams have finite per-line and total-byte limits;
only the three named reference shards receive a 64 MiB ZIP-member allowance.
