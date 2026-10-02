# codex-connection/1.0

Owner: shared backend transport, consumed by writing, production and settings UI.
Implementation/review: Issue #44 and ADR 0007. This schema describes the public
connection object, not its HTTP envelope or the external Codex protocol.

`GET /api/v1/settings/codex` returns `{connection: <state>}`. Local POST routes
`codex/login`, `codex/logout`, `codex/configure` manage only HaloCue's own CLI
profile. Configure accepts only `cli_path`; login/logout need an empty object.
The integrated production prefix is `/production/api/v1/settings/`.

Login returns only `{type, auth_url}`. The official OAuth URL is transient and
must not be logged, saved to a project, or committed. HaloCue returns no access
token, email, login identifier, purchased credit balance or API key. Public quota
windows retain only usedPercent, windowDurationMins and resetsAt. Missing quota
is `not_reported`, not zero usage. Model discovery is not proof of entitlement;
the selected model must pass an actual connection test before activation.

Existing model-settings requests gain provider `codex`, model and
`subscription_only_acknowledged: true`. Keys, key environment names and custom
endpoints are rejected. Billing is `chatgpt_subscription`. A successful save
activates a shared strict marker; existing API profiles remain stored but blocked.
The purpose selection activates writing, direction, or both. If the second
activation fails, the UI reloads the actual state and reports partial completion.

Usage is one final cumulative receipt per native turn, including tool exchanges.
The ledger scope is `observed_codex_turns`; its compatibility field
`physical_request_count` counts observed native turns, not internal HTTP calls.
Agent usage adds `codex_turn_count` and `observed_http_request_count`, with scope
`provider_calls_plus_legacy_summaries` when Codex is present. Legacy providers
keep existing fields and scope. Unreported usage remains unknown and monetary
cost stays null. The max-token configuration reserves output/context budget;
the app-server does not expose it as a hard output-token limit.

Migration is additive: no rewrite of old profiles or drafts; auth/profile data
stays outside Git and project backup payloads. Contract tests JSON round-trip
synthetic ready, logged-out, API-auth, exhausted and uninstalled states and reject
secret fields. The external CLI protocol was tested with Windows CLI 0.159.2.
