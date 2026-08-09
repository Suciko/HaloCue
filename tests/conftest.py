from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest


FIXTURES = Path(__file__).resolve().parent / "fixtures"
_TEST_USER_DATA = Path(tempfile.mkdtemp(prefix="halocue-pytest-user-data-"))
os.environ["HALOCUE_USER_DATA_DIR"] = str(_TEST_USER_DATA)


@pytest.fixture(scope="session", autouse=True)
def isolated_user_data():
    import assetdb

    connection = assetdb.connect(_TEST_USER_DATA / "aa_assets.db")
    connection.close()
    shutil.copy2(
        FIXTURES / "aa_resources.min.json",
        _TEST_USER_DATA / "aa_resources.json",
    )
    try:
        yield _TEST_USER_DATA
    finally:
        shutil.rmtree(_TEST_USER_DATA, ignore_errors=True)


@pytest.fixture(scope="session")
def aa_resource_index_path():
    return FIXTURES / "aa_resources.min.json"


@pytest.fixture(scope="session")
def empty_llm_config_path():
    return FIXTURES / "llm.empty.json"


@pytest.fixture
def seed_draft_resources(aa_resource_index_path):
    def seed(store, token):
        target = store.get_draft_path(token) / "resources.json"
        shutil.copy2(aa_resource_index_path, target)
        return target

    return seed


@pytest.fixture
def synthetic_cast_path(tmp_path):
    path = tmp_path / "cast.json"
    path.write_text(
        json.dumps(
            {
                "cast": {
                    "旁白": {"narrator": True},
                    "凯伊": {
                        "id": "1516544",
                        "name": "凯伊",
                        "club": "特殊现象调查部",
                        "portrait": True,
                    },
                    "桃井": {"id": "모모이", "portrait": True},
                    "绿": {"id": "미도리", "portrait": True},
                    "柚子": {"id": "유즈", "portrait": True},
                    "爱丽丝": {"id": "아리스N", "portrait": True},
                },
                "alias": {"Kei": "凯伊"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def annotated_script_path(tmp_path):
    path = tmp_path / "sample.annotated.txt"
    path.write_text(
        "## 夜晚的活动室\n"
        "@bg BG_GameDevRoom\n"
        "凯伊: 已经准备好了。\n"
        "旁白: 灯光慢慢亮起。\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture(scope="session")
def browser():
    install = (
        "Install browser test support with: python -m pip install playwright && "
        "python -m playwright install chromium"
    )
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        if exc.name == "playwright":
            pytest.skip(install)
        raise
    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch(headless=True)
        except PlaywrightError as exc:
            message = str(exc)
            if "Executable doesn't exist" in message or "playwright install" in message:
                pytest.skip(install)
            raise
        try:
            yield instance
        finally:
            instance.close()
