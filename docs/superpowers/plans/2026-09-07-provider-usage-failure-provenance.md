# Preserve provider usage through rejected output and failure —05-004

> Next bounded backend slice after UI immutable regression. Do not call partial
> response metadata a complete cross-workflow cost ledger;05-003/05-001 remain wider.

**Goal:** The reported usage of a rejected/truncated/refused response is not discarded,
and a failed next call never inherits usage from a previous successful call. Service
adapters preserve reported/unknown/cache/input-total semantics rather than reducing
all missing usage to apparently known zero consumption.

## Observed source

`LLMWritingProvider._call_llm` currently calls validate_completion before _capture_usage
and before resetting thread-local last_usage. A rejected response loses its own usage
and may expose stale previous usage. `_provider_usage` and `_merge_usage` in the writing
service drop usage_status/cache_status/input_tokens_semantics and can sum partially
unknown costs into a misleading complete-looking total. Provider retries live in
_open_with_retry and are not comprehensively counted by the current snapshot model.

## Implementation boundaries / TDD

- [ ] Synthetic valid-response then truncated/refused response with usage proves
      last_usage refers to the current failed response, while content is still rejected.
- [ ] Reset call-local usage before request construction/transport; malformed JSON,
      missing usage, connection exceptions and exhausted retries cannot reuse prior
      values. Unknown usage is not asserted to mean zero billable use.
- [ ] Safely normalize untrusted usage numbers (wrong types/negative/nonfinite) without
      hiding the primary completion failure or manufacturing a monetary estimate.
- [ ] Capture response usage before semantic output validation and preserve its status
      through DomainError details/current-run audit. Do not retain hidden reasoning or
      raw secret response data in logs/audits merely to expose usage.
- [ ] Update service normalization/merge contract to keep status/cache/input semantics;
      partial reported costs remain partial or unknown, not a complete accounting sum.
      Define migration/compatibility behavior for older aggregate rows with no status.
- [ ] Verify actual failure consumers for conversation, review, scene and adaptation
      persist/retrieve these fields; identify which still require separate durable
      usage-ledger work. Avoid a getter-only fix declared as complete workflow repair.
- [ ] Focused provider/tool/HTTP retry/activation/pinning/adaptation tests, scoped review,
      unchanged-commit broad regression and exact ledger/handoff evidence.

No live transport, paid provider, model-spec lookup, secrets, AA execution or new
pricing tables needed. Use synthetic API response shapes already used by tests.
Actual physical attempt accounting and unified hard authorization budget require
separate coordinated changes; preserve those as unresolved rather than guessing costs.
