from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZipFile

import UnityPy
from PIL import Image, ImageOps


def normalized(value: str) -> str:
    return value.strip().casefold()


def output_path(root: Path, kind: str, key: str) -> Path:
    token = hashlib.sha256(normalized(key).encode("utf-8")).hexdigest()
    suffix = ".jpg" if kind == "background" else ".png"
    return root / ("backgrounds" if kind == "background" else "avatars") / f"{token}{suffix}"


def fit_background(image: Image.Image) -> Image.Image:
    fitted = ImageOps.fit(
        ImageOps.exif_transpose(image).convert("RGB"),
        (320, 180),
        method=Image.Resampling.LANCZOS,
    )
    return fitted


def fit_avatar(image: Image.Image) -> Image.Image:
    fitted = ImageOps.contain(
        ImageOps.exif_transpose(image).convert("RGBA"),
        (160, 160),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    canvas.alpha_composite(fitted, ((160 - fitted.width) // 2, (160 - fitted.height) // 2))
    return canvas


def save_record(root: Path, records: dict, kind: str, key: str, image: Image.Image, source: str) -> None:
    destination = output_path(root, kind, key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if kind == "background":
        fit_background(image).save(destination, "JPEG", quality=82, optimize=True, progressive=True)
    else:
        fit_avatar(image).quantize(
            colors=256,
            method=Image.Quantize.FASTOCTREE,
            dither=Image.Dither.FLOYDSTEINBERG,
        ).save(destination, "PNG", optimize=True)
    records[(kind, normalized(key))] = {
        "kind": kind,
        "key": key,
        "normalized_key": normalized(key),
        "path": destination.relative_to(root).as_posix(),
        "source_fingerprint": source,
    }


def unity_images(raw: bytes):
    environment = UnityPy.load(raw)
    for obj in environment.objects:
        if obj.type.name not in {"Texture2D", "Sprite"}:
            continue
        try:
            asset = obj.read()
            image = asset.image
        except Exception:
            continue
        key = str(getattr(asset, "m_Name", "") or "")
        if key and image is not None:
            yield obj.type.name, key, image


def add_normal_package(path: Path, root: Path, records: dict) -> None:
    with ZipFile(path) as archive:
        avatar_raw = archive.read("avatars_assets_all.bundle")
        for asset_type, key, image in unity_images(avatar_raw):
            if asset_type == "Texture2D" and key.startswith(("Student_Portrait_", "NPC_Portrait_")):
                save_record(root, records, "avatar", key, image, "normal-package")
        print(f"normal avatars: {sum(kind == 'avatar' for kind, _ in records)}", flush=True)

        bundle_names = [
            name for name in archive.namelist()
            if "/03_scenario/01_background/" in name.casefold()
            and name.casefold().endswith(".bundle")
        ]
        for index, name in enumerate(bundle_names, 1):
            for _, key, image in unity_images(archive.read(name)):
                save_record(root, records, "background", key, image, "normal-package")
                break
            if index % 100 == 0:
                print(f"normal backgrounds: {index}/{len(bundle_names)}", flush=True)


def extract_extra_package(path: Path, password: str, destination: Path) -> Path:
    subprocess.run(
        ["bsdtar", "-xf", str(path), "--passphrase", password, "-C", str(destination)],
        check=True,
    )
    manifests = list(destination.rglob("manifest.json"))
    if not manifests:
        raise FileNotFoundError("extra package manifest.json is missing")
    return manifests[0].parent


def add_extra_directory(package_root: Path, root: Path, records: dict) -> None:
    avatars = list((package_root / "characters").glob("*/*-avatar.png"))
    for source in avatars:
        key = source.name[: -len("-avatar.png")]
        with Image.open(source) as image:
            save_record(root, records, "avatar", key, image, "extra-package")
    print(f"extra avatars: {len(avatars)}", flush=True)

    backgrounds = [
        source for source in (package_root / "bgs").iterdir()
        if source.is_file() and source.suffix.casefold() in {".jpg", ".jpeg", ".png", ".webp"}
    ]
    for index, source in enumerate(backgrounds, 1):
        with Image.open(source) as image:
            save_record(root, records, "background", source.stem, image, "extra-package")
        if index % 100 == 0:
            print(f"extra backgrounds: {index}/{len(backgrounds)}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--normal-zip", type=Path, required=True)
    parser.add_argument("--extra-zip", type=Path)
    parser.add_argument("--extra-root", type=Path)
    parser.add_argument("--password", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if bool(args.extra_zip) == bool(args.extra_root):
        parser.error("pass exactly one of --extra-zip or --extra-root")

    output = args.output.resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    records = {}
    add_normal_package(args.normal_zip.resolve(), output, records)
    if args.extra_root:
        add_extra_directory(args.extra_root.resolve(), output, records)
    else:
        with tempfile.TemporaryDirectory(prefix="halocue-preview-seed-") as temporary:
            package_root = extract_extra_package(args.extra_zip.resolve(), args.password, Path(temporary))
            add_extra_directory(package_root, output, records)

    rows = sorted(records.values(), key=lambda row: (row["kind"], row["normalized_key"]))
    manifest = {
        "schema_version": 1,
        "status": "ready",
        "fingerprint": "bundled-android-previews-v1",
        "counts": {
            "backgrounds": sum(row["kind"] == "background" for row in rows),
            "avatars": sum(row["kind"] == "avatar" for row in rows),
            "failed": 0,
        },
        "records": rows,
        "failures": [],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    total = sum(path.stat().st_size for path in output.rglob("*") if path.is_file())
    print(f"wrote {len(rows)} previews ({total / 1024 / 1024:.1f} MiB) to {output}")


if __name__ == "__main__":
    main()
