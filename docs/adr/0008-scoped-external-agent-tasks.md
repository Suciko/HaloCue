# ADR 0008: Scoped external Agent task exchange

Status: implemented on Issue #46 branch, pending PR review.
Date: 2026-10-03. Owners: backend and AI contexts.

## Decision

An external Agent can edit an author-selected window of saved scene prose through
a frozen JSON task. File exchange and a task-scoped stdio MCP server submit the
same versioned result to existing scene edit validation and pending proposals.
The author accepts or rejects through the existing inline manuscript comparison.
This transport never invokes a model, purchases credits, or falls back to a model
API. External account billing and token usage are unknown to HaloCue.

The first task kind is `scene.text.edit`. New-story generation, AA direction and
general project editing need separate future scoped contracts. MCP is a tool
interface for the external host, not a way to obtain inference from any arbitrary
subscription. A host without MCP can import/attach the task and return JSON; even
a plain chat can exchange the package manually if it can follow the result format.

The local source-runtime bridge uses the official Python MCP SDK maintained v1
line (`mcp>=1.30,<2`). It runs separately from the application. A dedicated
`.venv-agent` is preferred; no interpreter or MCP SDK is added to the existing
published Beta archive. The bridge offers task/window/cards/status reads and one
submit tool, plus a resource/prompt. It exposes no apply, shell, filesystem,
arbitrary URL, sampling, or general work-library tool.

Each connection has a random capability stored in a private local file; only its
hash goes into the task table. Requests are loopback-only, bypass proxy variables
and refuse HTTP redirects. The capability expires after 24 hours and can be
revoked. Prompt/reference text is data and cannot expand scope. Frozen revision,
paragraph hashes, JSON field validation and atomic proposal creation stay on the
server. The tool host's general filesystem abilities remain the host's own policy;
this bridge is not an OS sandbox for the external Agent.

## Alternatives and consequences

Managed Codex inference remains ADR 0007. Generic browser automation would have
fragile login, output and quota reporting. Requiring a paid model API would violate
the requested operating mode. Task exchange works without such an interface but
requires a deliberate export/import step when the host has no MCP.

The additive `external_agent_tasks` SQLite table and versioned contracts require
no rewrite of formal revisions. Project backups contain task records, not private
connection files. Imported results still need a current matching revision. Old
code ignores the additive table; rollback leaves task history intact. Revocation
or expiry stops further submission, not an already-created pending proposal.
Exact retry is idempotent. Optional MCP installation failure leaves file exchange
available and is reported truthfully in the UI.

## 2026-10-03 amendment: direct conversational MCP

Maintainer correction: MCP hosts must operate HaloCue from their own normal
conversation without asking the author to create/export/import a task. File
exchange is a fallback for hosts without MCP. The prior single-task protocol
remains compatible, but is no longer the default setup UI or tool catalog.

The settings page authorizes selected works once and produces one local stdio
configuration. The direct server exposes four tools: find scenes, read a scene,
search its work's material, and propose numbered paragraph changes. Finding a
scene combines work/chapter/scene discovery. The server captures exact revision,
pending candidate and paragraph hashes behind a read ID; the host passes only
that ID plus paragraph numbers and replacement prose. Reading automatically
selects the latest pending candidate, so normal refinement needs no candidate ID.
Scope and stale-content checks remain at the final atomic proposal commit.

The additive `mcp_connections`, `mcp_scene_reads`, and `mcp_edit_receipts` tables
persist authorization, exact read snapshots and idempotent submissions. Only
capability hashes enter the database; private files remain outside backups.
The connection lasts until disconnect or reauthorization, survives restart,
and is revoked after backup restoration so revoked capabilities cannot reappear.
The four-tool surface has no accept/apply, model, shell or arbitrary-file tool.
Results include inline diff, proposal status and a local review link.

This is a 1.0 source-preview change on Issue #46 / stacked PR #47, pending review.
The published Beta artifact is not rebuilt. SDK/client evidence is distinct from
compatibility evidence for any named third-party Agent host.

## 2026-10-03 amendment: direct AA performance proposals

Maintainer explicitly prioritizes AA production above prose MCP. Issue #48 extends the integrated 1.0 connection to independently selected production run IDs (connection contract 1.1), including legacy/imported tasks without a writing origin. Work grants do not imply AA grants; migration defaults old connections to an empty AA scope.

Four additional tools find productions, read bounded card windows, retrieve frozen resource choices and propose performance batches. Read IDs hide stable card IDs and draft versions. Proposals can change line annotations, edit directives, resolve background requests or insert validated directives, preserving source dialogue/speakers. Background/sound keys must already belong to the task's frozen resource snapshot. New asset import and cast mapping remain explicit HC task operations. There is no inference, author-acceptance, compile or install tool exposed to external hosts.

Production owns the versioned external-performance-proposal/1.0 projection and task-local private snapshots/receipts. The main review surface displays human-readable before/after changes and author apply/reject actions. Applying revalidates draft/face/resource choices, locks the draft, commits the batch with a fixed-file rollback journal and invalidates prior build/install claims; startup/next-read recovery rolls back interrupted acceptance. Rejection leaves the draft unchanged, including stale proposals. SDK plus synthetic preview/compile evidence is separate from named-host subscription compatibility or native AA playback evidence. This source-preview amendment remains pending PR review.
