"""A private Unix socket broker for Thunderbird's native messaging connection."""

import fcntl
import json
import os
import selectors
import socket
import sys
import time

from dayline.bridge import CHANGE_SIGNAL, read_message, socket_path, write_message
from dayline.config import Config, cache_directory, write_json
from dayline.errors import DaylineError


def serve() -> None:
    path = socket_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (path.parent / "host.lock").open("a") as lock:
        # A second Thunderbird profile must not replace the active bridge socket.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path.unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX) as server, selectors.DefaultSelector() as selector:
            server.bind(str(path))
            path.chmod(0o600)
            server.listen(8)
            selector.register(server, selectors.EVENT_READ)
            native_input = os.fdopen(sys.stdin.fileno(), "rb", buffering=0, closefd=False)
            selector.register(native_input, selectors.EVENT_READ)
            pending = {}
            serial = 0
            try:
                while True:
                    for key, _ in selector.select(timeout=5):
                        if key.fileobj is server:
                            client, _ = server.accept()
                            client.settimeout(2)
                            stream = client.makefile("rwb", buffering=0)
                            request_id = None
                            try:
                                message = read_message(stream)
                                if message.get("command") in ("item", "create", "update"):
                                    # The socket client cannot grant itself source write permission.
                                    try:
                                        message["selection"] = Config.load().sources
                                    except DaylineError as exc:
                                        write_message(stream, {"error": str(exc)})
                                        stream.close()
                                        client.close()
                                        continue
                                serial += 1
                                request_id = serial
                                message["id"] = serial
                                # Thunderbird limits native-host output to 1 MiB.
                                # Our commands contain IDs/ranges, never full calendar snapshots.
                                if len(json.dumps(message).encode()) > 1024 * 1024:
                                    raise DaylineError("Bridge command is too large.")
                                pending[serial] = (client, stream, time.monotonic())
                                write_message(sys.stdout.buffer, message)
                            except (OSError, ValueError, EOFError, DaylineError):
                                pending.pop(request_id, None)
                                stream.close()
                                client.close()
                        else:
                            message = read_message(native_input)
                            if message.get("event") == "changed":
                                write_json(cache_directory() / CHANGE_SIGNAL, time.time())
                                continue
                            request_id = message.get("id")
                            if request_id in pending:
                                client, stream, _ = pending.pop(request_id)
                                try:
                                    write_message(stream, message)
                                except OSError:
                                    pass
                                finally:
                                    stream.close()
                                    client.close()
                    for request_id, (client, stream, started) in list(pending.items()):
                        if time.monotonic() - started > 30:
                            stream.close()
                            client.close()
                            del pending[request_id]
            finally:
                for client, stream, _ in pending.values():
                    stream.close()
                    client.close()
                path.unlink(missing_ok=True)


def main() -> None:
    try:
        serve()
    except (OSError, EOFError, ValueError, DaylineError) as exc:
        print(f"Dayline bridge stopped: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
