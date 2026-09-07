# Canonical face-ID consumption — 03-D02

Goal: a face ID approved against the frozen character resource index must survive
render/parse/compile without silently retaining the default face. Do not weaken
annotation evidence/variant guards or change prompts, teacher/Sel, main, or1.1.

Verified RED: local temporary-only compile of A(S2_01) with frozen face id S2_01
and label alternate returns00; alternate and01 pass (1fail/2pass). No DB/model calls.

Design: retain canonical IDs and label aliases as separate per-character namespaces
in res_lookup. resolve_face tries exact canonical ID first, then legacy1–2digit
normalization, then case-insensitive label alias. Do not permit arbitrary alphanumeric
IDs absent from the frozen character. Canonical ID wins an alias collision. Character
identifiers remain the scope; nonnumeric ID case is exact unless also a genuine label.
Keep numeric legacy semantics and warnings; no resource discovery or new dependency.

Tests: S2_01,label and numeric full compilation; no-label canonical ID; uppercase/
lowercase ID distinction; alias casefold; canonical-vs-label collision; wrong character
or costume identifier does not borrow another table; annotation_safety legal field
through render/parse/build emits expected faceId, while missing evidence still fails.
A missing face remains visibly diagnosed by existing warning; no fake success/metadata
is emitted into AA rows. Evaluate whether structured diagnostics need separate wiring
through existing consumer before claiming all invalid-face diagnostics resolved.

Reject flat alias-only patch without exact-ID priority (collisions), broad regexp
acceptance (unverified IDs), and standard prompt edits (not needed). Test first,
narrow code review, focused root compiler/safety tests then preserved service suite.
This does not solve03-D01 beat camera loss or03-D03 terminal prefix diagnostics.
