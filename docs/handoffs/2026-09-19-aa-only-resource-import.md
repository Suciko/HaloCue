# AA-only resource import boundary

2026-09-19. Branch codex/1.0-release-readiness-20260914. Local changes; no commit/push/PR.

Supersedes the official-bundle follow-up suggested in prior import handoffs. User explicitly requires AA-managed local resources, not game-resource extraction.

- Production rebuild no longer calls AA cache/catalog discovery or harvest_official_characters. No Addressables/catalog prerequisite warnings.
- Production workspace inspection sets include_resource_cache=False. Shared legacy discovery retains its old default for compatibility, but production does not invoke its cache/catalog probes.
- build_index lazily imports extraction-only code within the legacy extraction function. Production imports only local manifest/project harvesters.
- Import reads the explicit aa_resources.json export in the selected workspace and previously imported same-workspace records, combines local CharacterOverrides and history mapping, and preserves background IDs, labels, registered characters and sounds. Different-workspace exports are rejected; old workspace lists are not carried over.
- Existing local decoded preview images can be reused; no bundle decoding is invoked. Internal legacy preview folder names retained for compatibility, not a requirement to extract resources.
- UI environment badge reports AA material directory availability rather than official resources.

Verification: 138 tests passed across background import, AA discovery, preview-root, production service and HTTP API suites. Includes actual local builder with official_catalog, UnityPy, official_preview_index imports forbidden, plus discovery probes replaced by failures. JS syntax and git diff checks passed. Existing current task data and AA workspaces not rebuilt or overwritten.

Limitations: no new AA format invented. The export reader consumes the existing aa_resources.json schema and CharacterOverrides mapping; assets absent from those maps/local images remain unresolved rather than being downloaded or decoded. Legacy standalone extraction code is retained but disconnected from this 1.0 import path.
