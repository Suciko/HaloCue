# HaloCue third-party notices

MIT 许可证只适用于 HaloCue 原创代码。公开版不包含 Spine；个人骨骼、
个人素材和作品在任何版本都不得包含。

The MIT License in `LICENSE` applies only to original HaloCue code. Every
component below remains under its own copyright and license. Package metadata
is included in the Windows bundle and the release builder fails if a shipped
distribution or recognized native runtime component is missing from this file.

## Python packages and bundler

| Component | License |
|---|---|
| `PyInstaller` bootloader | GPL-2.0 with the PyInstaller bootloader exception |
| `anthropic` | MIT |
| `anyio` | MIT |
| `distro` | Apache-2.0 |
| `docstring_parser` | MIT |
| `httpx` | BSD-3-Clause |
| `httpcore` | BSD-3-Clause |
| `h11` | MIT |
| `certifi` | MPL-2.0 |
| `idna` | BSD-3-Clause |
| `jiter` | MIT |
| `pydantic` | MIT |
| `pydantic_core` | MIT |
| `sniffio` | MIT OR Apache-2.0 |
| `typing_extensions` | PSF-2.0 |
| `annotated-types` | MIT |
| `typing-inspection` | MIT |
| `click` | BSD-3-Clause |
| `rich` | MIT |
| `Pygments` | BSD-2-Clause |
| `MarkupSafe` | BSD-3-Clause |
| `tqdm` | MPL-2.0 AND MIT |
| `tzdata` | Apache-2.0 |
| `Pillow` | MIT-CMU (HPND-style) |
| `UnityPy` | MIT |
| `attrs` | MIT |
| `brotli` | MIT |
| `lz4` | BSD-2-Clause |
| `texture2ddecoder` | MIT |
| `etcpak` | MIT |
| `astc-encoder-py` | MIT |
| `fsspec` | BSD-3-Clause |
| `defusedxml` | PSF-2.0 |
| `zstandard` | BSD-3-Clause |
| `pywin32` | PSF-2.0 |

Authoritative package license texts and project links are available in their
shipped `.dist-info` metadata and upstream distributions. PyInstaller's
bootloader terms are documented at <https://pyinstaller.org/en/stable/license.html>.

## Native runtime components

| Component | License/source |
|---|---|
| `CPython` | Python Software Foundation License 2.0 |
| `Microsoft Visual C++ Runtime` | Microsoft Visual C++ Redistributable terms |
| `OpenSSL` | Apache-2.0 |
| `SQLite` | Public domain |
| `zlib` | zlib License |
| `bzip2` | bzip2 License |
| `XZ Utils` | Public domain / component-specific terms |
| `Expat` | MIT |
| `libffi` | MIT |
| `mpdecimal` | BSD-2-Clause |
| `Zstandard` | BSD-3-Clause / GPL-2.0 dual license |

CPython licensing is documented at <https://docs.python.org/3/license.html>.
Microsoft runtime redistribution terms accompany the applicable Microsoft
Visual C++ Redistributable. Other native library notices are provided by their
named upstream projects.

## Product and asset boundaries

AzureArchive and Blue Archive names, software, game data and assets belong to
their respective owners. They are not relicensed by HaloCue's MIT License.

No Spine Editor executable, Spine Runtime, game asset, personal skeleton, raw
local database, local configuration, generated output, cache or secret is
included in the public HaloCue bundle. Spine software and user-provided Spine
files are governed by their own licenses.
