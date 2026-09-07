# Stable speaker prompt assembly —05-007

Current annotate_script sorts a set of display names only by descending occurrence
count. Equal counts retain randomized set iteration; dedup by characterID then chooses
a randomized alias representative. Full synthetic annotate assembly under seeds1..4
produced4different static hashes (verified RED), despite same input/resources.

Use counts computed in one pass and preserve first source occurrence as tie breaker.
Keep current primary frequency order and characterID dedup; among tied aliases, first
source mention becomes representative. Unicode names use exact authored spelling;
no case folding/renaming source. Deterministic stable name only final tie if needed.
Rule text and build_system implementation unchanged. Existing effective static hash
already distinguishes generated checkpoint inputs; add assembly version to run
fingerprint for explicit change identity, without editing standard rules hashes.

Tests full annotation mocked local agent capture of static+fingerprint across process
hash seeds, unequal frequency order, tied aliases,Unicode,changed cast insertion order.
Use temporary source/cast/index/llm paths and fake provider only; no actual config DB.
Retain gold standard prompt/rule tests. Scope annotate.py used-speaker assembly and
focused new test; no broad performance refactor/remote cache hit or literary claim.

## Executed

95a11fd;scoped review and1713-test immutable regression accepted.
See docs/handoffs/2026-09-07-stable-speaker-order.md for evidence and boundaries.
