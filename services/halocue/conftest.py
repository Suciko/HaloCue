"""Shared service fixtures; also imported by standalone project entrypoints."""

from services.halocue._test_support import (  # noqa: F401
    isolated_bundled_metadata,
    isolated_legacy_root,
    isolated_production_defaults,
    small_bundled_metadata,
)
