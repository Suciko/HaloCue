from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]


def test_beta_release_has_unique_version_and_private_signing_config():
    build = (PROJECT_ROOT / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    ignored = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert 'versionCode = 6' in build
    assert 'versionName = "0.4.0-beta.1"' in build
    assert 'signingConfig = signingConfigs.getByName("betaRelease")' in build
    assert 'rootProject.file("local.properties")' in build
    assert "local.properties" in ignored
    assert "betaStorePassword=" not in build


def test_device_beta_can_be_installed_without_removing_existing_debug_data():
    build = (PROJECT_ROOT / "app" / "build.gradle.kts").read_text(encoding="utf-8")

    assert 'create("deviceBeta")' in build
    assert 'applicationIdSuffix = ".devicebeta"' in build
    assert 'initWith(getByName("release"))' in build
    assert 'testBuildType = "deviceBeta"' not in build
