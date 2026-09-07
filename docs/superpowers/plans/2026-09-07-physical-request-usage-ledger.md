# Physical request accounting —05-003 /05-001 next slice

> Follow the logical-response provenance fix; keep the full accounting requirement,
> not just an extra last-response counter or renamed incomplete total.

**Goal:** Every known outbound model HTTP attempt (including retries and failed/
interrupted attempts) is distinguishable from a logical workflow invocation, with
reported/unknown consumption kept explicit. Adaptation, normal conversation/tools,
review and automatic jobs must not bypass the chosen accounting boundary.

## Existing evidence / design constraints

Writing `_open_with_retry` can make up to request_attempts separate urlopen calls.
Current provider-usage snapshots describe the final response only; scope policy audits
now preserve failures but explicitly cover logical methods, not every physical call.
The root compatibility llm client already has bounded request_records/telemetry;
those records must be inspected/reused or mapped, not duplicated blindly. Annotation
telemetry truncation is not a durable complete cost ledger.05-006 timeout-return timing
is related, but must have its own exact finally-vs-return regression.

## Proposed implementation sequence

1. Specify separate identities: durable AgentRun/workflow, logical provider request,
   physical attempt ordinal/ID, terminal state and usage-observation status. Preserve
   old policy snapshots as legacy summaries without inventing their historical calls.
2. Add a small writing-owned durable event store/table and versioned public projection.
   Record dispatch intent before outbound work and terminal/usage updates idempotently.
   No raw prompts, response bodies, API credentials or hidden reasoning in the ledger.
   Retain user data outside the repository and normal backup/restore coverage.
3. Pass a scoped observer into the LLM client through the existing logical usage scope;
   do not route attribution through a process-global active run. All retry attempts
   must report even if no HTTP response or malformed/error content arrives.
4. Audit the callback lifecycle on retries, stream/read errors, response rejection,
   cancellation, worker lease loss, process crash and postcommit reporting failure.
   An unfinished dispatch intent becomes interrupted/unknown, never an invented zero.
5. Capture final-response usage before semantic validation as already fixed. If an
   earlier retry's body includes usage, inspect it once without consuming the error
   diagnostic stream twice. Avoid adding all cumulative provider counters per attempt.
6. Use ledger identity for aggregation/dedup, with known subtotal + incomplete/unknown
   counts. Preserve old API fields where necessary but label coverage; never add both
   legacy summary and its derived new events. Include logical_count/physical_count
   separately. Ongoing jobs have honest pending accounting, not final totals.
7. Cover direct model connection tests and root Production adapters explicitly as
   attributed or intentionally separate diagnostic calls; do not claim writing-only
   store equals all-program consumption. Integrate root request events through an
   adapter after inspecting its existing retry/stream accounting behavior.
8. The new event boundary can support future authorization gates, but do not market
   observed cost as a guaranteed hard spending cap.02-009/05-010 background permission/
   scheduling policies need explicit decisions and tests rather than assumed coverage.

## Required evidence

Synthetic request1 timeout/rate-limit then request2 success: one logical request, two
physical attempts, exactly one known response usage and one unknown attempt, no zero
claim or doubled final response. Multi-tool rounds, adaptation failure/retry, cancellation
with late usage, restart/interrupted attempt, duplicate observer delivery, backup/restore,
concurrent instances and malformed buckets all need tests. Add per-work API/UI details
showing physical coverage and unknowns. No live paid requests, pricing research, main
merge/push/release,1.1 edit or standard director/teacher/Sel semantic change.

Run TDD/scoped review/focused tests then unchanged-source broad regression. Update
05-003 only for coverage actually proved across relevant clients; uncovered root paths
or crash windows keep it partial. Library/version specifics should follow installed
source/docs rather than a new network dependency guessed for this task.
