"""Range request scenarios, sent over a raw socket so we see every byte.

HTTP libraries hide what we want to look at: bytes after Content-Length, and a
response that no longer starts with a status line on a reused connection.
"""

import json
import random
import socket
import time
from dataclasses import dataclass, field

from wsgisandbox import procstats

PATH = "/plone/big-file/@@download/file"
MIB = 1 << 20


def expected_data(size):
    return random.Random(42).randbytes(size)


@dataclass
class Scenario:
    name: str
    range_header: str | None
    # slice of the file the answer must contain
    start: int
    end: int
    status: int
    second_range: tuple[str, int, int] | None = None  # (header, start, end)
    description: str = ""


def scenarios(size):
    mid = size // 2
    return [
        Scenario("full", None, 0, size, 200, description="GET without Range"),
        Scenario("first-1k", "bytes=0-1023", 0, 1024, 206),
        Scenario("middle-1m", f"bytes={mid}-{mid + MIB - 1}", mid, mid + MIB, 206),
        Scenario("open-ended", f"bytes={size - 1024}-", size - 1024, size, 206),
        Scenario("suffix", "bytes=-1024", size - 1024, size, 206),
        Scenario(
            "keepalive-next",
            "bytes=0-1023",
            0,
            1024,
            206,
            second_range=("bytes=100-109", 100, 110),
            description="two range requests on one connection",
        ),
    ]


class Connection:
    def __init__(self, port, timeout=30):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self.buf = b""

    def close(self):
        self.sock.close()

    def _recv(self):
        chunk = self.sock.recv(1 << 20)
        if not chunk:
            raise ConnectionError("connection closed by server")
        self.buf += chunk

    def request(self, range_header):
        self.request_path(PATH, range_header)
        return self.response()

    def request_path(self, path, range_header=None):
        lines = [f"GET {path} HTTP/1.1", "Host: localhost", "Connection: keep-alive"]
        if range_header:
            lines.append(f"Range: {range_header}")
        self.sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())

    def response(self):
        while b"\r\n\r\n" not in self.buf:
            self._recv()
        head, _, self.buf = self.buf.partition(b"\r\n\r\n")
        status_line, *header_lines = head.decode("latin-1").split("\r\n")
        if not status_line.startswith("HTTP/1."):
            raise ValueError(f"not a status line: {status_line[:40]!r}")
        headers = {}
        for line in header_lines:
            key, _, value = line.partition(":")
            headers[key.strip().lower()] = value.strip()
        length = int(headers["content-length"])
        while len(self.buf) < length:
            self._recv()
        body, self.buf = self.buf[:length], self.buf[length:]
        return int(status_line.split()[1]), headers, body

    def drain(self, quiet=0.3, limit=512 * MIB):
        """Count bytes the server sends after the body, until it is quiet."""
        extra = len(self.buf)
        self.buf = b""
        self.sock.settimeout(quiet)
        try:
            while extra < limit:
                chunk = self.sock.recv(1 << 20)
                if not chunk:
                    break
                extra += len(chunk)
        except TimeoutError:
            pass
        return extra


def server_stats(port, reset=False):
    conn = Connection(port)
    try:
        conn.request_path("/__sandbox_stats" + ("?reset=1" if reset else ""))
        _, _, body = conn.response()
        return json.loads(body)
    finally:
        conn.close()


def run_scenario(scenario, port, pid, data):
    result = {"name": scenario.name}
    server_stats(port, reset=True)
    procstats.reset_peak(pid)
    rss_before = procstats.rss(pid)
    read_before = procstats.read_chars(pid)
    conn = Connection(port)
    try:
        status, headers, body = conn.request(scenario.range_header)
        result["status"] = status
        result["content_length"] = int(headers["content-length"])
        result["content_range"] = headers.get("content-range")
        result["body_ok"] = status == scenario.status and body == data[scenario.start : scenario.end]
        if scenario.second_range:
            # no drain: a server that sent too much corrupts this answer
            header, start, end = scenario.second_range
            try:
                status2, _, body2 = conn.request(header)
                result["second_ok"] = status2 == 206 and body2 == data[start:end]
            except ConnectionError as exc:
                # the server does not keep the connection open, nothing to desync
                result["second_ok"] = "closed"
                result["second_error"] = f"{type(exc).__name__}: {exc}"
            except (ValueError, KeyError, OSError) as exc:
                result["second_ok"] = False
                result["second_error"] = f"{type(exc).__name__}: {exc}"
        result["extra_bytes"] = conn.drain()
    except (ValueError, KeyError, ConnectionError, TimeoutError, OSError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        conn.close()
    time.sleep(0.3)
    stats = server_stats(port)
    result["iterator_bytes"] = stats["iterator_bytes"]
    result["iterator_calls"] = stats["iterator_calls"]
    result["max_chunk"] = stats["max_chunk"]
    # rchar of the whole process: noisy, waitress reads its overflow buffer back
    result["server_rchar"] = procstats.read_chars(pid) - read_before
    result["peak_rss_delta"] = procstats.peak_rss(pid) - rss_before
    return result


def warm_up(port):
    conn = Connection(port)
    try:
        conn.request("bytes=0-9")
        conn.drain()
    finally:
        conn.close()
