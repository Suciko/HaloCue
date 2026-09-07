# Unconsumed one-line directive diagnostics —03-D03

Goal: legal one-line prefix directives at EOF/scene boundary must not disappear
without a source-located error. No new standalone event/timeline semantics.

Existing Pending state is consumed on the next dialogue event. Add shared diagnostic
logic over lossless nodes: record each one-line prefix's source line, consume on a
valid next line, flush errors for remaining prefixes at scene/separator boundary and
EOF. Never attach to previous dialogue or a different scene; never discard nodes.
Use code dir.unconsumed with error severity and precise command/source line.
Persistent commands (bg/trans/bgfx/bgm/music/stage/auto/camera_hold) are not one-line
prefixes and must not be newly rejected. Pending kinds include wait/se/sound/place/
popup/raw/bgshake/clearst/hidemenu/showmenu/aronatouch/shot/st/stm/zoom/enter/exit/move/
fx/camera/hl. Check actual compiler semantics rather than guess from names.

Integrate shared diagnostics into compile_document and static production preflight;
reuse current draft line→card mapping so errors block existing approval/compile gates.
Do not mutate source, infer new dialogue, or change compiler emitted events. A prior
ready state must not bypass revalidation in normal compile path. Scope code ownership:
diagnostics.py and production legacy_adapter.preflight_script plus focused tests;
no script2aap.py modifications while canonical-face fix is in progress.

TDD tests: terminal wait/se/clearst all lines reported; next scene/separator prevents
carry; pure-directive scene errors; repeated waits before dialogue remain two cues;
normal attached prefixes/persistent-only commands don't get unconsumed errors;
static preflight and compile_document agree on codes/lines; draft block count attaches
to exact cards. Root and service fixtures synthetic, isolated legacy root, no AA/model.

No claim of03-N02 standalone events or full performance semantic correctness. Review
and verify both this and face slice before immutable combined regression.

## Executed

Scoped reviews and1629-test unchanged-commit combined regression accepted. Exact
commands and boundaries: `docs/handoffs/2026-09-07-compiler-resource-consumption.md`.
