# Scene sources and release-owned production receipts (1.0 correction)

## Ownership

A Scene asset reference is an **author-selected source**. A production copy is a
**result belonging to one frozen release and one ProductionRun**. Consuming a source
must not change the author's scene, its source digest, or its review inputs.

`script-release/1.0` and `production-asset-handoff/1.0` retain their existing source
reference shape. New author snapshots always include `production_copy: null`.
The production service must keep rejecting non-null preclaimed copies. The writing
service and harness use the same source serializer. Client gate fingerprints use
the same null field, including when the browser still holds an old global copy.

## Receipt projection

`production-asset-usage/1.0` remains the provider of explicit copy proof:

```json
{
  "schema_version": "production-asset-usage/1.0",
  "production_run_id": "run-synthetic",
  "references": [{
    "scene_id": "scene-synthetic",
    "reference_id": "reference-synthetic",
    "source_asset_id": "BG_Synthetic",
    "source_version": "synthetic/1",
    "content_hash": "synthetic-resource-hash",
    "production_copy": {
      "copy_id": "copy-synthetic",
      "content_hash": "synthetic-resource-hash"
    }
  }]
}
```

Writing validates run identity, each scene/reference identity and source version/hash
against the **verified immutable release manifest**, not the current author rows.
Unknown or duplicate refs and missing copy identity/hash are rejected before any
writes. Partial receipts accumulate only within the same release/run.

The additive `release_asset_receipts` table is keyed by
`(release_id, production_run_id, scene_id, reference_id)` and stores receipt JSON.
It intentionally does not reference mutable scene-asset rows. Deleting/replacing
an author source cannot delete release-owned proof. Persistence does not bump the
work's authoring version or change source-reference timestamps.

`production-asset-status/1.0` adds an optional, additive `references` array with the
confirmed receipts for this release/run; existing status/count/capability fields
remain. Source snapshots and author UI do not claim a global task-copy status.

## Migration and compatibility

- Existing databases add an empty receipt table through normal schema initialization.
- Old `scene_asset_references.production_copy_json` bytes are retained but never
  inferred as belonging to a particular run, shown as author proof, or frozen again.
- Historical proof is repopulated only through a matching explicit production receipt.
- Frozen manifests, source digests and gate records are never rewritten. An old
  release that already froze a non-null copy remains verifiable but its handoff is
  explicitly rejected by the preclaimed-copy guard. Re-review and freeze a new
  release to hand off source-only references.
- Backup/restore includes the receipt projection in the normal writing database.
- Existing status consumers can ignore the added field. Tests exercise the new
  consumer, the retained legacy guard, migration, and real synthetic loopback handoff.

## Validation boundary

Receipts confirm identity-matched local production copies, not playback quality,
rights to redistribute assets, or full successful delivery. The replay and admission behavior is specified below; other production mutations
are outside this admission contract.
No real AA asset bytes are part of these fixtures or this contract.

## Replay and creation admission

The existing `POST /api/v1/production-runs` is replayable for a validated upstream
release identity. Its guard covers the lookup, creation, run save, integrated custom
copy check/attach, and receipt publication. A retry with the same release ID/hash
reuses the same run; a conflicting content hash remains a 409. Unrelated release
IDs and requests without an upstream release are not globally serialized.

The local OS lock coordinates cooperating threads/instances/processes sharing the
production directory. Lock files under `.handoff-locks/` must not be removed while
callers may exist. Owner process exit releases admission, but acquisition has no
timeout. Windows exclusion/exit behavior is tested; POSIX uses flock and is not
claimed runtime-tested on Windows. This does not make arbitrary production-state
mutation safe across multiple active processes.

Writing's ordinary handoff request retains its existing linked-run/no-assets and
complete-proof fast paths. If a run exists but proof is pending, it replays the same
verified frozen release command. It never reads mutable Scene references to repair
that release. A different returned run ID cannot silently replace the known link.
Repeated GET usage reads remain read-only. Missing, malformed-schema or wrong-run
receipt files must not be counted as success; a valid replay may rebuild the proof.

No new external provider/model request is introduced by local run/receipt replay.
Successful proof is still not a claim that AA playback, export or delivery succeeded.
