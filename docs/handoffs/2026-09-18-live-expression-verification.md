# 1.0 live expression continuity verification

- Kind: handoff; status: local tested implementation, uncommitted/unpushed.
- Date: 2026-09-18; branch: `codex/1.0-release-readiness-20260914`; parent Issue: #15.
- Owner: legacy annotation + production backend + embedded review UI.
- Authority: maintainer explicit request to verify with real model calls; product direction and backend invariants preserved.
- Pre-existing dirty files preserved; no remote publication, user work replacement or AA install.

## Findings / fixes
Actual provider execution revealed that new task snapshots did not carry the rich face labels seen in an older task. `merge_model_constraints` preferred any database capability list wholesale over index capabilities. A sparse DB left just five basic face labels, while the input index had an exact outfit with 21 rich records. Replace wholesale selection with exact spine_signature/outfit/face merging; weaker evidence cannot erase strong semantics. Vision-only unregistered IDs cannot be promoted by `_union_faces`.

`annotate._model_face_scope` now shares frozen character variant selection between prompt and validation. If a cast has explicit selectors they are authoritative; otherwise use the frozen character record. Ambiguous skeleton matches fail closed. Visually confirmed semantic annotations enrich only IDs already registered in the same character face table; no cross-outfit labels or visual-only invented IDs. Tests cover DB sparsity, exact scope, explicit misses, ambiguity, source immutability and the real new-run freeze boundary.

The review UI incorrectly described empty face as default. The compiler inherits prior character face state until scene/bg/place reset. Update wording to say no change/inherit and require explicit base face to recover from a strong reaction. No automatic face edits.

## Live experiment
Same prewritten 17-dialogue scene (12 portrait-character lines), one frozen background, both profiles with collaborative AI. Predefined rubric: ordinary report, transient surprise, reassurance, embarrassment, return to report. Four real gemini-3.8-flash requests: baseline and fixed, each conservative and standard once. Each succeeded in one physical request, no retries. The provider model ID is reported, not an independently authenticated upstream vendor identity.

Fixed prompts explicitly verified 21 usage annotations. Resource semantics matched, except automatically generated task-local teacher identifiers. Existing snapshots were not modified. Fixed conservative: 5 face changes/11 portrait-line transitions, 2 bubbles, 0 actions. Fixed standard: 8 changes/11, 3 bubbles, 4 actions. Both preserve all dialogue, explicit background and frozen face validity; all cards remain pending. No intensity-3 faces; surprise transitions to a suitable calm face. Conservative report smile is a manual style-review note, not automatically repaired. Single sample is not statistical proof of superiority or whole-product acceptance.

Total provider-reported tokens across four calls: 29,606 input / 2,852 output. No pricing claims. No raw provider secrets included in reports.

## Validation
- Focused combined root/production suite: 299 passed (face pipeline, asset catalogue/evidence/scope, semantic allowlists, annotation constraints/agent/entrypoint, conservative policy, authored backgrounds, production annotations/UI/service/HTTP/profile suites).
- Integrated navigation UI suite: 15 passed.
- New pipeline regression initially failed before fix; original sparse prompts and baseline output retained locally.
- `node --check services/halocue/production/ui/app.js`, scoped Ruff and diff checks pass.
- Live desktop dark/light and mobile dark review screenshots: 6 profile/theme/size combinations, no JS errors or overflow, no production writes. Feedback settings sync remains unrelated shell POST.
- Original user's production draft is identical before/after. No compilation or installation; no full repository suite claim.

Maintainer-local evidence: `<LOCAL_LIVE_EXPRESSION_QA>` holds RESULT.md, ISSUE_LOG.md, LINE_REVIEW.md, predeclared rubric, baseline/fixed run IDs, sanitized request metrics, prompt resource sections, tests and screenshots. No shared prerequisite on local paths or private assets.

## Open observations
Initial browser reload after baseline completion made embedded stage controls invisible; re-navigation to the explicit run worked, no duplicate generation. Independent production runs can display the previous writing work's header title, despite verified run/card identity. These are recorded navigation/context defects, not claimed fixed in this scope.

No long multi-chunk/cross-character performance or native AA face playback tested. End-of-scene short face has no subsequent sample to prove recovery. Old snapshots are deliberately not migrated; future work must make any refresh explicit and versioned.
