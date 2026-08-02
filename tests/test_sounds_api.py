# -*- coding: utf-8 -*-
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pytest
from webui import search_sounds, get_sound_file


def test_search_sounds():
    results = search_sounds(q="SE")
    assert isinstance(results, list)


def test_get_sound_file_stream(tmp_path):
    # 模拟已知音效文件
    sound_dir = tmp_path / "sounds"
    sound_dir.mkdir(parents=True, exist_ok=True)
    wav_file = sound_dir / "SE_Test_01.wav"
    wav_file.write_bytes(b"RIFF....WAVEfmt ....data....")

    res = get_sound_file("SE_Test_01", sound_dir=str(sound_dir))
    assert res is not None
    assert res["mime"] in ("audio/wav", "audio/x-wav")
    assert res["data"].startswith(b"RIFF")
