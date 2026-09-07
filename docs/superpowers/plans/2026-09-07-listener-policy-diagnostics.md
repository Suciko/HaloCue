# Explicit listener-only camera diagnostics —03-C01 decision

Preserve standard prompt/rule semantics. prompt.py explicitly requires normal portrait
speakers visible and listener focus expressed by shared shot. Therefore do NOT silently
expand automatic annotation into ordinary offscreen portrait dialogue. Manual one-line
camera overrides and accepted dialogue-free reaction nodes remain separate supported
paths, unchanged.

Current normalize_director accepts resource-valid visible[B]/focuslistener metadata;
normalize_direction_plan discards it for current whoA portrait and emits camera_hold auto,
with no diagnostic. Fix missing feedback rather than silently rewriting prompt policy:
when rejecting a newly declared model camera because it excludes current portrait
speaker, record a source-located policy drop plus warning/message explaining the
constraint and alternatives(sharedshot or validated reaction). Keep existing safe fallback
and clear rejected visible intent; don't pretend the requested shot was performed.
Inherited hold reset remains separate continuity behavior. Fresh identical requested
camera declarations need diagnostics too even if redundancy normalization ran first.

Acceptance: fresh listener-only rejected with sourceid/line/message;fresh[A,B] kept;
inherited stalehold releases;manualcamera retains priority;no-portrait and emptyshot
next-speaker restoration retained. Official-style e2e bond should explicitly assert
current normal speaker slot plus rejection diagnostic, not just any camera command.
No change to raw standard prompt/rule golden hashes. Existing policy-drop proposals
must include rejected camera intent so reviewer can see before/after rather than false
success. No group04/literary/AAplayback claim. Rootpolicy and test-only bounded changes;
source exact dialogue and manual controls preserved.
