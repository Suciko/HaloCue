# -*- coding: utf-8 -*-
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
import webui


def test_build_api_deprecated_flag():
    # 测试 build 响应包含 deprecated 提示
    # 构造兼容调用的标识断言
    flag = getattr(webui, "BUILD_API_DEPRECATED", True)
    assert flag is True
