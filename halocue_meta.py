PRODUCT_NAME = "HaloCue"
CHINESE_SUBTITLE = "AzureArchive 剧情演出工具"
ENGLISH_SUBTITLE = "Narrative Staging for AzureArchive"
VERSION = "1.0.0"
DISPLAY_NAME = "HaloCue 1.0.0"
LEGACY_VERSION = "0.9.3"
APP_ID = "halocue-local-server-v1"
MIN_PYTHON = (3, 10)
PUBLIC_ARCHIVE_NAME = f"{PRODUCT_NAME}-{VERSION}-windows-x64.zip"
PRIVATE_ARCHIVE_NAME = f"{PRODUCT_NAME}-{VERSION}-private-windows-x64.zip"

# The update manifest is deliberately static and public.  A CDN or a beta
# channel can override it through HALOCUE_UPDATE_MANIFEST_URL during QA.
DEFAULT_UPDATE_MANIFEST_URL = (
    "https://github.com/Suciko/HaloCue/releases/latest/download/update-manifest.json"
)
UPDATE_CHANNEL = "stable"

# Release builds replace this map with the stable Ed25519 public key(s).  It is
# intentionally public material; private signing keys stay in CI/offline
# release infrastructure and are never read by the client.
UPDATE_PUBLIC_KEYS: dict[str, str] = {
    "stable-2026": "iuMmKyOS4p6tDIO0J0bVj2f7OScPxajsCUtQFfxqJrU=",
}
