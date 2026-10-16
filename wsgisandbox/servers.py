"""WSGI servers the sandbox can start. Add a server by adding a function here.

Each function runs inside a variant venv, so import the server lazily. It gets
the zope.conf path and loads the app with zopeapp.load_app in the process that
handles the requests, because the counters live there.
"""

import os
import sys

from zopeapp import load_app


def waitress(zope_conf, host, port):
    import waitress

    waitress.serve(load_app(zope_conf), host=host, port=port, threads=4)


def bjoern(zope_conf, host, port):
    import bjoern

    bjoern.run(load_app(zope_conf), host, port)


def pyruvate(zope_conf, host, port):
    import pyruvate

    # max_reuse_count=0, the default, turns keep-alive off. 1.6.1 still closes
    # the connection after every response with it set, see the experiment report.
    pyruvate.serve(load_app(zope_conf), f"{host}:{port}", 2, max_reuse_count=100)


def gunicorn(zope_conf, host, port):
    from gunicorn.app.base import BaseApplication

    class Application(BaseApplication):
        def load_config(self):
            # gthread keeps connections alive, the sync worker does not.
            # The app loads in the worker, timeout covers the Zope startup.
            options = {"bind": f"{host}:{port}", "workers": 1, "worker_class": "gthread", "threads": 4, "timeout": 180}
            for key, value in options.items():
                self.cfg.set(key, value)

        def load(self):
            return load_app(zope_conf)

    Application().run()


def uwsgi(zope_conf, host, port):
    # uWSGI is a program of its own, it loads the app from uwsgi_app.py
    binary = os.path.join(sys.prefix, "bin", "uwsgi")
    here = os.path.dirname(os.path.abspath(__file__))
    args = [
        "--http11-socket", f"{host}:{port}",  # http-socket is HTTP/1.0 only, no keep-alive
        "--wsgi-file", os.path.join(here, "uwsgi_app.py"),
        "--home", sys.prefix,
        "--env", f"SANDBOX_ZOPE_CONF={zope_conf}",
        "--master", "--processes", "1", "--threads", "4",
        "--need-app", "--die-on-term",
    ]  # fmt: skip
    os.execv(binary, [binary, *args])


def cheroot(zope_conf, host, port):
    from cheroot import wsgi

    wsgi.Server((host, port), load_app(zope_conf), numthreads=4).safe_start()


SERVERS = {
    "waitress": waitress,
    "bjoern": bjoern,
    "pyruvate": pyruvate,
    "gunicorn": gunicorn,
    "uwsgi": uwsgi,
    "cheroot": cheroot,
}
