from halocue_meta import (
    APP_ID,
    DISPLAY_NAME,
    PRIVATE_ARCHIVE_NAME,
    PUBLIC_ARCHIVE_NAME,
    VERSION,
)


def test_release_identity_is_exact():
    assert APP_ID == "halocue-local-server-v1"
    assert DISPLAY_NAME == "HaloCue 0.9 Beta"
    assert VERSION == "0.9.0-beta.1"
    assert PUBLIC_ARCHIVE_NAME == "HaloCue-0.9.0-beta.1-windows.zip"
    assert PRIVATE_ARCHIVE_NAME == "HaloCue-0.9.0-beta.1-private-windows.zip"
