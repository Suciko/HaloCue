# Direct external MCP connection 1.0

This author-facing snapshot describes a persistent, revocable connection to
explicitly selected works. It contains no token. MCP tools cannot change the grant.
No task package is needed to find scenes, read materials/prose or propose edits.

Four tools share server-side scope checks and the existing writing Agent registry:
find scenes, read prose, search material and propose numbered paragraph changes.
Reads pin exact revision, candidate and paragraph hashes behind a read ID. Edits
only supply that ID plus paragraph numbers and replacement prose. The service
checks stale/unread content and automatically handles pending-candidate refinement.
Identical retry returns the same proposal and its status/diff/review link.
No apply or inference tool is exposed.

The three additive tables (`mcp_connections`, `mcp_scene_reads`, `mcp_edit_receipts`)
are initialized on service start and old-backup restore. Raw connection files
remain outside writing backup payloads. Every backup restoration revokes its
connections and needs fresh authorization. Selecting a new grant revokes the
old connection atomically. Rollback leaves the extra tables ignored by old code.

The optional external-task contract remains a fallback for hosts without MCP;
its 24-hour task expiry does not apply to the persistent workspace connection.
