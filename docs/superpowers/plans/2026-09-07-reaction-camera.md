# Dialogue-free reaction target visibility —03-D01 design notes

User authorized autonomous repair, but no automatic new creative decisions beyond
already accepted bounded beat. Baseline next after compiler diagnostics batch.

Synthetic RED exists at output/autonomous-20260907/test_reaction_camera_probe.py:
@camera_hold A;A dialogue;validated B(face01,actwave,wait1200)after beat;A next dialogue.
Current render/parse/build makes3rows but B is absent from reaction row, keeping only
wait. No model/database/AA resources involved.

Required fix should generate one-line camera B for the accepted synthetic beat,
not a new held camera. Next ordinary line retains original hold A. Preserve target,
anchor,position/reason and stable beat identity as sidecar metadata; don't add debug
fields to ScriptData. Test actual row target/face/action/pause once, not just camera
command existence. Valid narrator/no-portrait/teacher ordinary lines remain allowed.

Before beats can steal source directives: insert_annotation_beats currently inserts
just before a line after previous pending directive nodes. Simply prepending camera B
can consume/override the author's one-line camera/wait/fx meant for the anchor.
Inspect explicit directive metadata and pending prefix boundaries first. Preserve
source prefixes with their authored carrier; if contradictory one-line intent cannot
be safely retained, emit a source-located blocking diagnostic/proposal conflict rather
than silently overriding or dropping the accepted reaction. Do not only move beat
insertion before direction normalization: _beat_item lacks required identity metadata.

Use same diagnostic/sidecar result paths as annotate_script and production draft
proposal pipeline. Current annotation return has beats/proposals/diagnostics but no
beat→compiled-line source map; implement a narrow deterministic sidecar if consumer
needs it and test roundtrip. Claim scope only when production consumer actually reads
the diagnostic and rejects lost target intent; don't add decorative validation flags.

Acceptance matrix: before/after, multiple targets same anchor,hold A vs A+B,explicit
source one-line camera conflict,5slots full,scene boundary,duplicate anchor,unknown
anchor/rejected resource,ordinary offscreen/narrator/teacher lines,late/cancelled job
publication remaining fenced. Preserve exact authored dialogue and unrelated source
prefixes, wait count1. Standard prompt/rules untouched; real playback still unverified.
