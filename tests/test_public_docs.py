from __future__ import annotations

from pathlib import Path

from halocue_meta import PRIVATE_ARCHIVE_NAME, PUBLIC_ARCHIVE_NAME, VERSION
from release_tools.manifest import is_public_source_path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_release_identity_and_install_paths_are_documented():
    readme = _read("README.md")
    quickstart = _read("使用说明-从这里开始.md")
    changelog = _read("CHANGELOG.md")
    combined = "\n".join((readme, quickstart, changelog))

    assert "HaloCue 0.9.2" in combined
    assert VERSION in combined
    assert PUBLIC_ARCHIVE_NAME in combined
    assert PRIVATE_ARCHIVE_NAME in combined
    assert "Windows ZIP 不需要安装 Python" in combined
    assert "Python 3.10–3.13" in combined
    assert "AzureArchive.exe" in quickstart
    assert "工作区" in quickstart
    assert r"%LOCALAPPDATA%\HaloCue" in combined


def test_public_private_and_license_boundaries_are_unambiguous():
    readme = _read("README.md")
    upload = _read("UPLOAD.md")
    notices = _read("THIRD_PARTY_NOTICES.md")
    private = _read("docs/private-release.md")
    combined = "\n".join((readme, upload, notices, private))

    assert "公开源码" in readme
    assert "公开 Windows ZIP" in readme
    assert "私发覆盖包" in readme
    assert "个人骨骼" in combined
    assert "任何版本都不得包含" in combined
    assert "MIT 许可证只适用于 HaloCue 原创代码" in combined
    assert "https://esotericsoftware.com/spine-editor-license" in combined
    assert "书面授权" in combined
    assert "公开版不包含 Spine" in combined


def test_troubleshooting_backup_reset_and_security_are_documented():
    quickstart = _read("使用说明-从这里开始.md")
    security = _read("SECURITY.md")
    combined = "\n".join((quickstart, security))

    for phrase in (
        "找不到 Spine",
        "找不到 AA 工作区",
        "端口冲突",
        "干净地重新配置",
        "备份",
        "重命名",
    ):
        assert phrase in combined
    assert "API Key" in security
    assert "安全漏洞" in security


def test_internal_docs_and_reports_are_not_public_source():
    assert not is_public_source_path(".superpowers/task-9-report.md")
    assert not is_public_source_path("docs/superpowers/release-plan.md")
    assert not is_public_source_path("docs/custom-assets-test-report.md")
