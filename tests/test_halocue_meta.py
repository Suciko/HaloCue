from halocue_meta import (
    APP_ID,
    DISPLAY_NAME,
    PRIVATE_ARCHIVE_NAME,
    PUBLIC_ARCHIVE_NAME,
    VERSION,
)


def test_release_identity_is_exact():
    assert APP_ID == "halocue-local-server-v1"
    assert DISPLAY_NAME == "HaloCue 0.95"
    assert VERSION == "0.95"
    assert PUBLIC_ARCHIVE_NAME == "HaloCue-0.95-windows-x64.zip"
    assert PRIVATE_ARCHIVE_NAME == "HaloCue-0.95-private-windows-x64.zip"
