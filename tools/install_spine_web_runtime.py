# -*- coding: utf-8 -*-
"""Install the pinned official Spine 4.2 WebGL runtime from npm.

The runtime is intentionally not committed to the public repository.  Users
must review and comply with the Spine Runtimes License included in the npm
package and have any license required for their use case.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path


VERSION = "4.2.119"
PACKAGE_URL = (
    "https://registry.npmjs.org/@esotericsoftware/spine-webgl/-/"
    f"spine-webgl-{VERSION}.tgz"
)
PACKAGE_SHA1 = "eb911be2f478edbbf4b02cfe2b8b0af13943b430"
HERE = Path(__file__).resolve().parent
DESTINATION = HERE / "spine_web_runtime"
RUNTIME_MEMBER = "package/dist/iife/spine-webgl.min.js"
LICENSE_MEMBER = "package/LICENSE"


def install() -> tuple[Path, Path]:
    print(f"正在从官方 npm 包下载 Spine WebGL {VERSION}……")
    request = urllib.request.Request(
        PACKAGE_URL,
        headers={"User-Agent": "HaloCue-Spine-Runtime-Installer/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        archive = response.read()
    actual = hashlib.sha1(archive).hexdigest()
    if actual != PACKAGE_SHA1:
        raise RuntimeError(
            f"Spine npm 包校验失败：expected {PACKAGE_SHA1}, got {actual}"
        )
    DESTINATION.mkdir(parents=True, exist_ok=True)
    runtime = DESTINATION / f"spine-webgl-{VERSION}.min.js"
    license_path = DESTINATION / "SPINE-RUNTIMES-LICENSE.txt"
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
        runtime_file = package.extractfile(RUNTIME_MEMBER)
        license_file = package.extractfile(LICENSE_MEMBER)
        if runtime_file is None or license_file is None:
            raise RuntimeError("官方 npm 包缺少运行时或许可证文件")
        with tempfile.NamedTemporaryFile(delete=False, dir=DESTINATION) as pending:
            shutil.copyfileobj(runtime_file, pending)
            pending_runtime = Path(pending.name)
        with tempfile.NamedTemporaryFile(delete=False, dir=DESTINATION) as pending:
            shutil.copyfileobj(license_file, pending)
            pending_license = Path(pending.name)
    pending_runtime.replace(runtime)
    pending_license.replace(license_path)
    return runtime, license_path


if __name__ == "__main__":
    installed_runtime, installed_license = install()
    print(f"已安装：{installed_runtime}")
    print(f"许可证：{installed_license}")
    print("使用前请阅读许可证，并确认你具备相应的 Spine 使用权。")
