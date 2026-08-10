"""Import-compatible Android replacement for the Windows AA installer."""

from android_runtime_guard import unavailable


class AARunningError(RuntimeError):
    pass


class AACorruptBundleError(ValueError):
    pass


class AAInstallTargetExistsError(FileExistsError):
    pass


class InstallManager:
    def __init__(self, *args, **kwargs):
        pass

    def install_options(self, *args, **kwargs):
        unavailable("direct_aa_install")

    def install_build(self, *args, **kwargs):
        unavailable("direct_aa_install")
