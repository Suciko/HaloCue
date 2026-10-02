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
