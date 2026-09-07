# Input and stored preference validation repairs

User authorized autonomous repair without intermediate design questions. Branch:
`codex/1.0-autonomous-hardening-ui`. No main merge, new dependencies, or 1.1 edits.

## 01-009 — request JSON shape (local critical path)

Current writing HTTP parser returns arbitrary JSON and lets malformed/negative
Content-Length flow into int/read. Invalid clients become 500 or unbounded reads.
Require one nonnegative ASCII-decimal length within the existing per-route bound,
keep absent/zero body as {} for existing callers, parse UTF-8 JSON, require object.
Reject duplicate lengths/unsupported transfer encodings without reading the stream.
Do not change successful response envelopes. Tests: unit guarded-read boundary and
actual loopback POST requests for scalars/lists/invalid JSON/objects, no domain writes
on rejection. Status400 for bad input and413 for existing size limits.

## 06-F09 — saved preference validation (independent slice)

Keep documented fields only; validate enum/int bounds matching existing UI. Do not
activate currently ineffective read-only controls. Unknown legacy keys are ignored,
known invalid stored values/corrupt JSON produce a specific observable error; no
silent defaults or overwrite of corrupt bytes. Missing file still returns defaults.
Use atomic replacement for saves; reject invalid partial updates before modifying
file. Concurrent calls within one store should not lose unrelated fields.
Tests: valid legacy/default/partial writes, all invalid types/ranges, corrupt file
preserved/read/save errors, replace failure original preserved. No model/real data.

Reject silent coercion/clamping and silently resetting damaged configuration: both
hide user data loss. Keep behavior small rather than a new settings platform. The
settings UI must surface a load warning without blocking unrelated model controls.

## Gates

TDD for both slices. Scoped review and focused HTTP/settings regressions. Freeze a
commit before broad writing/production/integrated plus preserved-prompt regression.
Keep ledger scopes explicit; neither is a group04 security audit or real-AA proof.
