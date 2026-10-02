# ADR 0007: Managed Codex subscription provider

Status: implemented on the Issue #44 branch; pending reviewed PR integration.
Owner: backend/AI contexts. Date: 2026-10-03.

## Decision

HaloCue can run writing proposals and text-only AA direction through the official
Codex CLI app-server, authenticated with ChatGPT. The user requested subscription
quota instead of metered model APIs. The shared transport lives in
`services/halocue/codex_agent.py`; each owning service keeps its validation and
proposal adapter. Public connection state is versioned by
`packages/contracts/codex-connection/1.0.schema.json`.

The CLI owns OAuth and refresh credentials in an independent HaloCue profile under
the integrated user-data directory. HaloCue neither reads the user's normal Codex
credentials nor accepts API keys, custom endpoints or token uploads for this
provider. The child environment removes inherited provider credentials. The CLI
is an external dependency, not bundled in the published Beta 2 archive.

After a successful Codex activation, a profile-level `subscription-only.enabled`
marker blocks other model providers in writing and production. Existing API
profiles remain stored, but cannot be used or silently selected as a fallback.
The bundled legacy transports also check this policy at each outbound request,
including pinned providers and retries. Already dispatched requests cannot be
undone. Offline editing remains available. Rollback must be deliberate local
administration, never an automatic response to an auth, quota or model error.

The UI requires the user's acknowledgement that extra paid Codex usage is off.
The available account protocol cannot inspect or disable that billing setting;
this acknowledgement is not an automated billing guarantee. Account type and
quota are checked before inference. Missing usage is reported as unknown, and
exhaustion stops the operation without purchasing credits or calling an API.

Native tools are restricted to HaloCue's registered tools. Calls are checked
against the active thread and turn and pass through the existing server-scoped
executor and proposal checks. Native shell, file edits, web, MCP and extra agent
operations are disabled/rejected. The process uses the CLI's stable read-only
sandbox; this does not claim OS-level read-root confinement. Official CLI 0.159.2
rejects the older `readOnly.access` option. Protocol incompatibility fails rather
than switching to a permissive mode. Writes to formal revisions still require
the user's proposal acceptance.

One native turn, including tool continuations, produces one ledger receipt from
the final cumulative token usage. Its scope is `observed_codex_turns`, not a count
of the CLI's internal HTTP attempts. Reported cache tokens can be divided by
reported input tokens; no cache rate is invented when unavailable. Cost remains
null because the subscription receipt provides no per-request monetary cost.
The existing max-token setting reserves context/output budget; it is not a hard
native output ceiling. Existing non-Codex request accounting stays unchanged.

## Migration and boundaries

Alternatives considered: direct model APIs violate the requested billing mode;
MCP alone supplies tools and does not provide subscription inference; browser
automation of a chat page lacks the official structured transport and stable
tool/usage receipts. The official local app-server keeps the account provider in
charge of authentication and gives HaloCue a bounded native integration.

Model configuration gains the `codex` provider, subscription acknowledgement and
billing mode; public state and agent usage gain additive fields. Existing files
need no bulk conversion. Login data, CLI profile, story inputs and generated
outputs stay outside Git and are not inserted into project backups.

This slice supports text generation and AA JSON direction. Vision-based asset
recognition is explicitly unsupported. It does not publish a new executable,
replace Beta 2, or prove the whole AA render/export pipeline on a new release.

## Evidence and review

The synthetic peer tests auth/quota rejection, malformed output, cancellation,
tool receipts, cumulative accounting, and the subscription-only transport guard.
Real tests used the installed official Windows CLI 0.159.2, a managed ChatGPT
login and a previously authorized official story excerpt. Writing produced a
reviewable proposal without changing the formal revision; direction validated
all 12 source rows against the existing annotation schema. See the Issue #44
handoff for commands and results. Main receives this change only via reviewed PR.

Sources: [official app-server documentation](https://learn.chatgpt.com/docs/app-server),
[authentication](https://learn.chatgpt.com/docs/auth), and the installed CLI's
generated experimental protocol schema. The experimental protocol remains an
external compatibility dependency.
