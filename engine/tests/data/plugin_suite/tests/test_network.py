"""The plugin's network guard (REPRO_NET_GUARD=1): loopback only, and fast failures."""

import socket
import threading

import pytest


def test_name_resolution_is_refused():
    with pytest.raises(socket.gaierror, match="name resolution is off"):
        socket.getaddrinfo("example.com", 443)


def test_outside_connection_is_refused():
    # 192.0.2.1 is in TEST-NET-1, reserved for documentation (RFC 5737): nothing should answer
    # there, so an immediate failure is the guard's.
    with pytest.raises(OSError, match="network access is off"):
        socket.create_connection(("192.0.2.1", 9), timeout=30)


def test_localhost_resolves():
    assert socket.getaddrinfo("localhost", 80)


def test_loopback_still_works():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        accepted = []
        thread = threading.Thread(target=lambda: accepted.append(server.accept()[0]))
        thread.start()
        with socket.create_connection(("127.0.0.1", port), timeout=30) as client:
            thread.join(30)
            accepted[0].sendall(b"ping")
            assert client.recv(4) == b"ping"
            accepted[0].close()
