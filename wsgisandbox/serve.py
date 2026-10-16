"""Start a Zope WSGI app with the chosen server. Run with the variant venv python.

    variants/EXP/VARIANT/.venv/bin/python wsgisandbox/serve.py \\
        --server waitress --zope-conf PATH --port 8080
"""

import argparse
import json
import os
import sys
from urllib.parse import parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from servers import SERVERS  # noqa: E402


STATS = {"iterator_bytes": 0, "iterator_calls": 0, "max_chunk": 0}


def count_iterator_output():
    """Count what plone.namedfile's range iterator hands to the server.

    Process level counters (rchar) are no use: waitress reads its own overflow
    buffer file back, which hides what the iterator does.
    """
    from plone.namedfile.utils import filestream_range_iterator as cls

    orig_read, orig_next = cls.read, cls.__next__

    def record(data):
        STATS["iterator_bytes"] += len(data)
        STATS["iterator_calls"] += 1
        STATS["max_chunk"] = max(STATS["max_chunk"], len(data))
        return data

    cls.read = lambda self, size=-1: record(orig_read(self, size))
    cls.__next__ = lambda self: record(orig_next(self))
    cls.next = cls.__next__


def stats_middleware(app):
    """Answer /__sandbox_stats (?reset=1 clears the counters) before Zope sees it."""

    def wrapper(environ, start_response):
        if environ.get("PATH_INFO") != "/__sandbox_stats":
            return app(environ, start_response)
        body = json.dumps(STATS).encode()
        if parse_qs(environ.get("QUERY_STRING", "")).get("reset"):
            for key in STATS:
                STATS[key] = 0
        start_response("200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
        return [body]

    return wrapper


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", choices=sorted(SERVERS), required=True)
    parser.add_argument("--zope-conf", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    from Zope2.Startup.run import make_wsgi_app

    app = make_wsgi_app({}, args.zope_conf)
    count_iterator_output()
    app = stats_middleware(app)
    print(f"serving with {args.server} on {args.host}:{args.port}", flush=True)
    SERVERS[args.server](app, args.host, args.port)


if __name__ == "__main__":
    main()
