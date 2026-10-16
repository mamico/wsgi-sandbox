"""WSGI servers the sandbox can start. Add a server by adding a function here.

Each function runs inside a variant venv, so import the server lazily.
"""


def waitress(app, host, port):
    import waitress

    waitress.serve(app, host=host, port=port, threads=4)


def bjoern(app, host, port):
    import bjoern

    bjoern.run(app, host, port)


def pyruvate(app, host, port):
    import pyruvate

    # max_reuse_count=0, the default, turns keep-alive off. 1.6.1 still closes
    # the connection after every response with it set, see the experiment report.
    pyruvate.serve(app, f"{host}:{port}", 2, max_reuse_count=100)


SERVERS = {
    "waitress": waitress,
    "bjoern": bjoern,
    "pyruvate": pyruvate,
}
