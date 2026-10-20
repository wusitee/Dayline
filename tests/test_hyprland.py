import socket
import threading

from dayline.hyprland import cursor_position


def serve(path, reply: bytes, requests: list) -> threading.Thread:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)

    def answer():
        with server, server.accept()[0] as client:
            requests.append(client.recv(4096))
            client.sendall(reply)

    thread = threading.Thread(target=answer)
    thread.start()
    return thread


def test_cursor_position_reads_hyprland_ipc_and_tolerates_failures(tmp_path, monkeypatch):
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert cursor_position() is None
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "instance")
    assert cursor_position() is None  # No socket.
    directory = tmp_path / "hypr" / "instance"
    directory.mkdir(parents=True)
    requests = []
    for reply, expected in (
        (b'\n{\n    "x": 1096,\n    "y": 642\n}\n', (1096.0, 642.0)),
        (b"ok", None),
    ):
        thread = serve(directory / ".socket.sock", reply, requests)
        assert cursor_position() == expected
        thread.join()
        (directory / ".socket.sock").unlink()
    assert requests == [b"j/cursorpos", b"j/cursorpos"]
