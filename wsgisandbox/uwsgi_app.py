"""WSGI file for uWSGI, which runs as its own program and loads the app from here."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zopeapp import load_app  # noqa: E402

application = load_app(os.environ["SANDBOX_ZOPE_CONF"])
