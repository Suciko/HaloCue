"""Verify a release at a physical shallow path and after renaming its folder."""

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_integrated_release import verify  # noqa: E402
from tools.verify_release import _extract_archive, require  # noqa: E402


def verify_portable_release(source, qa_root, *, keep=False):
    source = Path(source).resolve()
    qa_root = Path(qa_root).resolve()
    require(not qa_root.exists(), "QA root already exists; choose a fresh directory")
    require(
        qa_root.parent == Path(qa_root.anchor),
        "QA root must be directly below a drive/filesystem root",
    )
    qa_root.mkdir()
    try:
        if source.is_dir():
            bundle = qa_root / "HaloCue"
            shutil.copytree(source, bundle)
        else:
            bundle = _extract_archive(source, qa_root)
        require(bundle.is_relative_to(qa_root), "bundle escaped the owned QA root")
        require(
            len((bundle / "_internal" / "halocue_production" / "model_capabilities.py").parents)
            < 6,
            "QA location is too deep to exercise the reported frozen-path failure",
        )
        results = [verify(bundle / "HaloCue.exe", fresh_profile=True)]
        renamed = qa_root / "HaloCue 改名 含空格"
        require(
            renamed.is_relative_to(qa_root) and not renamed.exists(), "invalid relocation target"
        )
        bundle.rename(renamed)
        results.append(verify(renamed / "HaloCue.exe", fresh_profile=True))
        return {
            "ok": True,
            "shallow_location": True,
            "renamed_chinese_space_folder": True,
            "launches": sum(result["launches"] for result in results),
            "scenarios": results,
        }
    finally:
        if not keep:
            # This directory was created exclusively above; never remove the source
            # bundle or a pre-existing user-provided directory.
            require(
                qa_root.parent == Path(qa_root.anchor) and not qa_root.is_symlink(),
                "unsafe QA cleanup target",
            )
            shutil.rmtree(qa_root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="release ZIP or assembled HaloCue folder")
    parser.add_argument(
        "--root", type=Path, required=True, help="new QA directory directly below a drive root"
    )
    parser.add_argument(
        "--keep", action="store_true", help="retain this owned QA copy for further inspection"
    )
    args = parser.parse_args()
    print(json.dumps(verify_portable_release(args.source, args.root, keep=args.keep)))
