# Skill proposal: isolated 1.0 acceptance

- Status: proposed, inactive
- Proposer: Codex
- Date: 2026-10-01
- Owning context: backend/client
- Review: PR https://github.com/Suciko/HaloCue/pull/40, issues #28/#41

## Trigger

Use for maintainer-authorized 1.0 integration acceptance involving existing local user data, model calls or AA delivery. Do not use for unit-only checks or 1.1 design work.

## Evidence

The independent-dataset workflow is documented in `docs/handoffs/2026-10-01-1.0-direction-recovery.md` and `docs/handoffs/2026-10-01-1.0-review-export-qa.md`. It prevents test review actions from adopting a user's live draft and keeps credentials/assets outside the repository.

## Draft SKILL.md procedure

Inputs: explicit task scope, target commit, authorized local data, selected acceptance route. Outputs: isolated evidence, test results and a reviewable handoff.

1. Read repository governance and prior acceptance evidence; record release, branch, issues and baseline.
2. Create a separate local dataset and localhost runtime. Snapshot source data/release hashes before mutations; keep proprietary bytes and secrets outside Git.
3. Prefer no-model continuation when generation evidence already exists. For real calls, use only the already authorized provider/context and record actual receipts without publishing credentials or raw account metadata.
4. Exercise saving, review gates, preview and compile in the isolated copy. Install only into a synthetic disposable AA target unless live installation is explicitly requested.
5. Compare exact source rows, immutable releases and bundle hashes. Reproduce failures on the prior baseline before attributing regressions; distinguish stale fixtures from actual runtime defects.
6. Run appropriate checks, save a UI proof, commit the focused repair, and publish only sanitized handoff evidence in the existing review trail.

Each step completes when its stated evidence exists; incomplete release gates remain explicit.

## Benefit and risks

- Benefit: repeatable continuation without changing pending user decisions.
- Failure modes: copied absolute configuration may still point at live AA data; enforce the installation boundary separately. Do not infer model usage/cost from missing telemetry.
- Privacy/provenance: repository MIT implementation and synthetic fixtures only; authorized local BA/AA bytes stay private under ADR-0004. No external implementation body or new third-party tool is included.

## Dry run

The review/export handoff records a two-scene run: one isolated face edit, 46 cards reviewed, successful AAP compile, 33 exact source rows preserved, valid bundle hashes, unchanged source production inventory and zero new model requests.

## Review checklist

- [x] Narrow trigger, explicit inputs/outputs and observable checks.
- [x] No credentials, private assets or personal filesystem paths included.
- [x] License/provenance boundary recorded.
- [ ] Maintainer has reviewed the dry run and procedure.

## Activation

Approval PR, active Skill path and activation commit: unset. This proposal does not install or modify an active Skill.


## Additional portability evidence (2026-10-04)

Issue [#56](https://github.com/Suciko/HaloCue/issues/56) and
[PR #57](https://github.com/Suciko/HaloCue/pull/57) expose a missed release
invariant: deep-directory extraction on the author machine did not exercise
fixed-parent path assumptions. Compare the
[Electron handoff](../../handoffs/2026-10-03-1.0-electron-icon.md) and
[R3 receipt](../../handoffs/2026-10-04-1.0-portable-startup.md).

Proposed addition for packaged-preview acceptance: validate the final ZIP at a
physical shallow drive-root path, rename the owned copy to include Chinese and
spaces, use an unrelated current directory, remove developer Python variables
and PATH, and exercise normal isolated LocalAppData without a HaloCue override.
Require restart persistence, bundled-resource health, immutable program bytes,
owned-process cleanup and CRC/per-file manifest hashes. Refuse existing QA roots
and verify containment before relocation or recursive cleanup. The reusable
first-party command is `tools/verify_portable_release.py`; R3's C/E-drive dry run
passes eight headless starts, alongside four native window starts and frozen
AA/MCP acceptance. This covers controlled local conditions, not a collaborator's
ACLs, antivirus or Windows version. Keep actual receiving-machine retest and
remote CI status explicit. No new third-party reference, asset or active Skill
is introduced; this candidate remains proposed and inactive for owner review.
