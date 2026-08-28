# Handoff: AA local resource mapping

## Evidence source

The local reference directory is `E:\AzureArchive_decompiled` (the actual
directory name uses an underscore between `AzureArchive` and `decompiled`).
The 0.8.8 IL2CPP skeleton identifies `ScenarioResourceManager` and the Studio
slot-property editors. Its Addressables catalog confirms these resource rules:

- backgrounds: `defaultlocalgroup_assets_uis/03_scenario/01_background/<key>.jpg.bundle`;
- character runtime bundles: `characters_assets_<id>all.bundle`;
- official picker portraits: `avatars_assets_all.bundle`;
- AA's custom workspace overrides are resolved before the official Addressables
  resource.

## Local index

The installed catalog at
`E:\AzureArchive\App\AzureArchive_Data\StreamingAssets\aa\catalog.json`
and cache at `E:\AzureArchive\资源文件` were scanned on 2026-08-25. The local
index contains 1,554 background previews and 805 avatar previews with zero
failed bundles. It lives in the user's AA data area and is not committed.
To make the existing local HTTP preview route use that index, start HaloCue
with `HALOCUE_AA_PREVIEW_INDEX=E:\AzureArchive\存储文件\data\halocue-official-previews`.

## Repository contract

`aa_preview_resolver.py` resolves logical AA keys through that index and lets a
host provide an allowlisted URL such as
`/api/resources/preview?kind=background&key=BG_School`. Browser descriptors carry
logical keys and preview URIs, never absolute Windows paths or extracted game
resources. `preview.js` renders transparent avatar PNGs when the host supplies
those URIs and falls back to a deterministic placeholder when the local index
is unavailable.

## Verification

```text
python -m pytest -q tests/test_aa_preview_resolver.py tests/test_ba_scene_preview.py tests/test_ba_scene_preview_ui.py
node --check apps/desktop-client/scene-preview/preview.js
```
