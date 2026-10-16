"""Start a Zope WSGI app with the chosen server. Run with the variant venv python.

    variants/EXP/VARIANT/.venv/bin/python wsgisandbox/serve.py \\
        --server waitress --zope-conf PATH --port 8080
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from servers import SERVERS  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", choices=sorted(SERVERS), required=True)
    parser.add_argument("--zope-conf", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    print(f"serving with {args.server} on {args.host}:{args.port}", flush=True)
    SERVERS[args.server](args.zope_conf, args.host, args.port)


if __name__ == "__main__":
    main()
