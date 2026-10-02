"""A browser startup burst must fit while the local gateway starts serving."""

import socket
from halocue_integrated.gateway import create_gateway


def test_gateway_accepts_startup_assets_before_serving(tmp_path):
    server = create_gateway(
        "127.0.0.1",
        0,
        writing_address=("127.0.0.1", 1),
        production_address=("127.0.0.1", 2),
        static_dir=tmp_path,
    )
    clients = []
    failures = []
    try:
        # The page loads more than twenty scripts/styles. Delay accept() to
        # model a busy startup thread without introducing a timing sleep.
        for _ in range(32):
            try:
                clients.append(socket.create_connection(server.server_address, timeout=0.1))
            except OSError as exc:
                failures.append(type(exc).__name__)
        assert not failures, f"{len(failures)} startup connections were refused or delayed"
    finally:
        for client in clients:
            client.close()
        server.server_close()
