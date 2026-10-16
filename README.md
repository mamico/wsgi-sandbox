# wsgi-sandbox

Compare WSGI servers in front of Plone/Zope. Each experiment builds one venv and
one Zope instance per *variant* (for example "released" and "patched" versions
of a package), starts every server against each variant and measures what
happens on the wire and inside the server.

## Layout

- `wsgisandbox/` generic code: `envs.py` (venvs, instances), `serve.py` (start Zope with a server), `servers.py` (server registry), `runner.py`, `procstats.py`.
- `experiments/<name>/` one experiment: `experiment.toml`, `setup_site.py`, `scenarios.py`, `run.py`, `REPORT.md`.
- `variants/` generated venvs and instances, not in git.

## Use

    make EXP=namedfile-range venvs instances setup run
    make EXP=namedfile-range run ARGS="--variants pr --servers bjoern --scenarios first-1k"
    uv run python experiments/namedfile-range/run.py --render-only   # rebuild tables.md

Needs `uv`, `libev-dev` (bjoern builds from source) and Python 3.12.

## Add a server

Add a function to `wsgisandbox/servers.py` and list it in `SERVERS`. Install it
through `requirements/servers.txt`, then add its name to `servers` in `experiment.toml`.

## Add an experiment

Copy `experiments/namedfile-range/`, change `experiment.toml` (variants are
package overrides installed from a git URL or any pip spec), `setup_site.py` and `scenarios.py`.

## Server side counters

`serve.py` answers `/__sandbox_stats` itself (WSGI middleware, Zope never sees it)
and wraps `plone.namedfile.utils.filestream_range_iterator` to count the bytes it
returns. Process level counters such as rchar are not reliable: waitress reads its
own overflow buffer file back, so a 64 MiB download shows 2 to 3 GB of rchar.
