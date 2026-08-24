# Development toolchain

The repository pins the primary development versions used for 1.x work:

| Tool | Version | Source of truth |
| --- | --- | --- |
| Python | 3.13.12 | `.python-version` |
| Node.js | 22.19.0 | `.nvmrc` |
| Rust | 1.97.1 | `rust-toolchain.toml` |
| FFmpeg | 7 or newer | Runtime capability detection |

The 0.9 package metadata continues to support Python 3.10 through 3.13. The
pinned Python version is for maintainer development and release verification,
not a reduction of the supported range.

FFmpeg is not bundled by default. Runtime code must detect it, expose the path
and parsed version, and produce a user-facing unavailable state. Tests may use a
fixture executable or a CI-installed FFmpeg.

Model and TTS runtimes are optional capabilities. Their versions belong in the
adapter package that ships them; large model files stay outside Git.
