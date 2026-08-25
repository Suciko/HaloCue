# Handoff: BA presentation UI calibration

## Visual baseline

The formal 1.1 canvas stays a fixed `16:9` video frame. The reference BA
capture may have been taken at a different window ratio, so the implementation
uses normalized positions inside the 16:9 frame rather than copying its outer
pixel dimensions.

Current normalized presentation anchors:

- location chip: left edge, top `20%`, with the cyan accent inset inside the
  chip rather than attached to the canvas edge;
- dialogue rule: left `9.7%`, right `10.2%`, and dialogue panel bottom `3%`;
- lower scene shade: bottom `42%`, blue-black translucent gradient;
- default dialogue font: bundled Noto Sans SC variable font, weight `400`;
- actor layer is above the lower shade and below the dialogue layer;
- event progress, frame counters, AUTO, and MENU are not rendered in the
  finished frame.

The canvas still supports local AA background and portrait URIs through the
allowlisted host endpoint. Missing local portraits remain empty rather than
showing synthetic head/body placeholders in the formal frame.

## Verification

```text
python -m pytest -q tests/test_ba_scene_preview.py tests/test_ba_scene_preview_ui.py tests/test_aa_runtime_contract.py tests/test_render_timeline.py
python -m pytest -q tests/test_ba_scene_preview_ui.py -m browser
node --check apps/desktop-client/scene-preview/preview.js
git diff --check
```

Result: `17 passed`; browser regression passed; JavaScript syntax and diff
checks passed. A 1280x720 browser capture confirmed the stage ratio is `16:9`
and the dialogue rule/scene chip remain inside the target anchors.

## Product boundary

These controls are intentionally absent from the exported video frame. The
editor workbench may expose timeline navigation and export actions outside the
canvas; the canvas itself is only the authored performance.
