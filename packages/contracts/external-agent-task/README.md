# External Agent task/result 1.0

`task-1.0.schema.json` is the frozen `scene.text.edit` package. The embedded
`result_schema` equals `result-1.0.schema.json`; tests compare it to the backend
validator. There is no migration from an older external-task format.

The input hash covers canonical JSON of the package before `input_hash` is added:
UTF-8, sorted keys, compact separators, literal Unicode; prefix `sha256:`.
Agents copy all hashes rather than recomputing them. Paragraph edits reference
stable IDs and exact original text hashes, never offsets alone.

File import and scoped MCP submission create the same pending scene proposal.
Only the existing explicit proposal acceptance produces a formal revision.
One task pins one saved revision and at most 40 exported paragraphs. Reading the
next window cannot widen it. Relevant confirmed character cards are a bounded
snapshot (at most four, at most 12,000 characters each); this is not a full library
export. No API secrets, capability tokens, or source file paths enter the package.

Tasks persist in an additive SQLite table. Reopen/revoke and 24-hour expiry do not
change manuscript state. Exact duplicate results return the original proposal
receipt; changed duplicates, stale revisions, overlapping pending proposals,
unknown fields and out-of-scope blocks fail without partial edits.

MCP connection files remain in the local integrated user-data directory outside
project backup payloads. Restoring a task database on another machine preserves
file exchange, but does not restore its MCP capability. Create a new task there.
