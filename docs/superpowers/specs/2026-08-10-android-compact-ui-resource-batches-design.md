# Android Compact Workbench and AA Resource Mapping

## Goal

Make the Android WebUI reclaim first-screen space and preserve the PC annotation/index behavior when the original AA installation contains both its ordinary resource package and a later extra package.

HaloCue does not import either AA resource package. The original AA application owns that workflow. HaloCue ships a generated mapping which translates the PC-compatible annotations to the identifiers actually published by the supplied extra package.

## Confirmed constraints

- Android must not probe or write the original AA application's `Android/data` directory.
- The ordinary package and extra package are imported by AA itself, potentially at different times through AA's same import entry.
- The PC index remains authoritative for annotations, background keys, sound keys, character identifiers, outfit keys, and face IDs.
- Extra-package character identifiers may differ from the PC identifier. Translation must happen only when serializing a selected character into the generated `.aap`.
- Same-name outfits are not interchangeable. Ambiguous aliases must be resolved with `outfit_key`; an identifier-only global replacement is forbidden.
- Spine rendering remains unavailable on Android. Atlas metadata may still provide face IDs and semantic labels for manual face selection.

## Design

### 1. Compact mobile workbench

The Android top bar uses touch-safe compact spacing. When the runtime and resource mapping are ready, the readiness panel collapses to a short summary and the recent-story area becomes a single compact entry, keeping the script picker in the first viewport.

On a scrollable story page, the action bar hides while scrolling down and reappears immediately when scrolling up. Settings remain in a drawer and are never pinned over the story content. The native Android shell owns system-bar insets, so the WebUI must not add the same top inset a second time.

### 2. Built-in PC and extra-package mapping

`aa_resources.json` is the PC-compatible base index. `scripts/build-android-resource-mapping.ps1` reads only mapping metadata from a user-supplied extra package while developing the APK:

- `manifest.json` supplies package identifiers and Spine portrait paths;
- each portrait's `.atlas` supplies face IDs and labels;
- `outfit_key` joins extra-package entries to the correct PC outfit;
- spelling variants in face labels are normalized without changing the numeric face ID.

The generated `android_resource_mapping.json` is packaged in the APK. At runtime `android_resource_mapping.merge_mapping()` overlays the extra-package data onto the PC index. It preserves the PC identifier used by annotations, records `android_package_identifier` per outfit, refreshes face lists, and appends package characters missing from the PC index.

During compilation, only selected serialized character identifiers are translated. If one PC identifier has multiple outfits, translation requires the selected `outfit_key`; otherwise it stays unchanged rather than guessing.

### 3. Android settings

Android settings show mapping readiness and counts instead of PC-only AA path or Spine controls. The current bundled mapping represents:

- 943 PC-index characters plus 40 extra-package-only characters, for 983 selectable characters;
- 580 backgrounds;
- 310 sounds;
- 192 mapped extra-package character entries;
- 52 identifier aliases;
- 1 skipped extra-package character entry.

## Acceptance criteria

1. On the target phone, the first screen reaches the script picker without duplicated system-bar spacing.
2. On a loaded story, scrolling down hides the action bar and scrolling up immediately restores it.
3. Android settings do not expose the PC AA installation path or Spine settings.
4. Settings report 983 characters, 580 backgrounds, 310 sounds, and 52 extra-package aliases.
5. PC identifiers remain stable in annotations and are translated only for the selected Android package outfit during `.aap` serialization.
6. Ambiguous same-name outfits do not receive a global alias.
7. Mapping generation, compiler synchronization, Android host tests, and device instrumentation remain green.
