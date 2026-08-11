# Android Home Polish Design

**Goal:** Improve the Android first screen's hierarchy and vertical density without changing PC behavior or removing any workflow action.

## Scope

- Apply all layout changes under `body.android-native` and the existing `max-width: 600px` breakpoint.
- Keep the current top-bar actions, story actions, asset filters, import actions, and four workflow stages.
- Do not change the desktop layout, API responses, story state, or navigation behavior.

## Layout

The Android top bar becomes a quiet application header. The title and three actions share a compact surface: the title remains the strongest element, while the actions use a low-contrast segmented treatment instead of three large outlined buttons. The existing hide-on-down-scroll and show-on-up-scroll behavior remains unchanged.

The active story card shows the source filename as its primary label. Internal workspace paths are not rendered as the title. Project name, file type, size, and modification time remain available in one clamped metadata line. Status chips and the two story actions use tighter spacing while retaining at least a 44 px touch target.

The custom-asset section stays fully expanded when assets or active tasks exist. When every count is zero and no task is active, it receives an `is-empty-state` class and becomes a compact summary/action area: title, counts, filters, directory scan, and a single-line empty message remain available.

The four workflow stages remain visible in one row. On Android phones their container, indices, labels, and separators are reduced so the current stage remains obvious without occupying a large card.

## Visual Rules

- Use the existing neutral background, blue accent, and green completed state.
- Reduce border and shadow emphasis instead of introducing new decorative surfaces.
- Keep typography at readable mobile sizes with zero letter spacing.
- Clamp long text rather than allowing internal paths or metadata to create multiple large rows.
- Preserve 44 px minimum touch targets for commands.

## Verification

- Add host contract assertions for the Android-only compact classes and CSS selectors.
- Run the focused UI contract, complete Python suite, JavaScript syntax checks, and Gradle builds.
- Install the APK on vivo `V2324HA`, capture the first screen, and verify no overlap, truncation, or broken actions.

## Verification Record

- Command surfaces use flex centering (`align-items`, `justify-content`, and `text-align`) while informational copy, catalog rows, and metadata remain left aligned.
- In-app browser QA passed at 360 x 800 and 412 x 915 for the home screen, material workbench, settings, import dialog, and review toolbar. No horizontal document overflow was found.
- DeepSeek uses `deepseek-v4-flash`; a temporary unsaved text request succeeded with that exact returned model.
- Full host suite: 90 collected, 89 passed, 1 skipped. JavaScript syntax checks passed.
- Gradle `assembleDebug assembleDebugAndroidTest` succeeded. The APK and test APK were installed on vivo `V2324HA` (Android 16 / API 36), and all 30 instrumentation tests passed.
- Full browser workflow produced a valid `完整流程测试.aap` after approving 7 cards and validating 0 blocking errors.
- Device visual QA covered home, active story, settings, material workbench, and import dialog. The dialog preserved state across portrait, landscape, and restored portrait orientations without overlap or reset.

## Follow-up verification

- Native Android system-bar padding is applied by `MainActivity`; secondary fullscreen WebView surfaces therefore suppress their duplicate `env(safe-area-inset-*)` additions under `body.android-native`.
- The recent-story Continue control occupies its own centered command row on narrow Android screens.
- The launcher source of truth is the existing PC `branding/halocue-icon.png` at 1024px; Android density assets are generated with high-quality downsampling and preserve its transparent glow and three-arc silhouette.
- Focused UI contracts passed (15 tests), Gradle debug and androidTest APK builds passed, and direct device instrumentation passed all 30 tests. After ADB reconnected, manual window-manager rotation passed portrait -> landscape -> portrait with the same top-resumed MainActivity and the import dialog retained throughout.
- The launcher background is pure white to match neighboring Android icons. Both adaptive and legacy icons retain the original PC artwork; the adaptive foreground uses `ContentScale 0.60` so the glow and three arcs remain inside the launcher mask.
