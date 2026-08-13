import socket
import urllib.request

from webui import LocalWebServer


def test_local_web_server_serves_the_app_and_releases_its_port():
    server = LocalWebServer(port=0)

    url = server.start()
    with urllib.request.urlopen(url + "/", timeout=3) as response:
        assert response.status == 200
        assert 'id="appShell"' in response.read().decode("utf-8")

    port = server.port
    server.stop()

    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", port))
    finally:
        probe.close()
