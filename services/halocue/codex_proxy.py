"""Child-only Windows static proxy fallback; explicit process settings win."""

from __future__ import annotations


def windows_system_proxy() -> dict[str, str]:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        ) as key:
            if not winreg.QueryValueEx(key, "ProxyEnable")[0]:
                return {}
            server = str(winreg.QueryValueEx(key, "ProxyServer")[0]).strip()
            try:
                bypass = str(winreg.QueryValueEx(key, "ProxyOverride")[0])
            except OSError:
                bypass = ""
    except (ImportError, OSError):
        return {}
    return parse_windows_proxy(server, bypass)


def parse_windows_proxy(server: str, bypass: str = "") -> dict[str, str]:
    def address(value, scheme="http"):
        return value if "://" in value else f"{scheme}://{value}"

    proxies = {}
    if "=" not in server:
        if server:
            proxies = dict.fromkeys(("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"), address(server))
    else:
        for entry in server.split(";"):
            name, separator, value = entry.partition("=")
            name, value = name.strip().lower(), value.strip()
            if separator and value and name in {"http", "https", "socks"}:
                proxies[
                    {"http": "HTTP_PROXY", "https": "HTTPS_PROXY", "socks": "ALL_PROXY"}[name]
                ] = address(value, "socks5" if name == "socks" else "http")
    exclusions = []
    for value in bypass.split(";"):
        value = value.strip()
        if value.lower() == "<local>":
            exclusions.extend(("localhost", "127.0.0.1", "::1"))
        elif value:
            exclusions.append(value[1:] if value.startswith("*.") else value)
    if exclusions:
        proxies["NO_PROXY"] = ",".join(dict.fromkeys(exclusions))
    return proxies


def apply_child_proxy(env: dict[str, str], *, windows: bool):
    names = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
    explicit = any(env.get(name) or env.get(name.lower()) for name in names)
    if windows and not explicit:
        for name, value in windows_system_proxy().items():
            if name == "NO_PROXY" and (name in env or name.lower() in env):
                continue
            env[name] = value
    for name in (*names, "NO_PROXY"):
        if name in env:
            env.setdefault(name.lower(), env[name])
        elif name.lower() in env:
            env[name] = env[name.lower()]
