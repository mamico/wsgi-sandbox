"""Run every scenario for every variant and server of the experiment.

    uv run python experiments/namedfile-range/run.py [--variants a,b] [--servers x,y] [--scenarios n,m]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
sys.path.insert(0, str(HERE))

import scenarios as sc  # noqa: E402
from wsgisandbox.envs import load_experiment, venv_python  # noqa: E402
from wsgisandbox.runner import ServerProcess  # noqa: E402

EXPERIMENT = HERE.name
PACKAGES = ["plone.namedfile", "Zope", "Products.CMFPlone", "waitress", "bjoern", "pyruvate"]


def versions(variant):
    code = (
        "import importlib.metadata as m, json, sys;"
        f"print(json.dumps({{'python': sys.version.split()[0], **{{p: m.version(p) for p in {PACKAGES!r}}}}}))"
    )
    out = subprocess.run([venv_python(EXPERIMENT, variant), "-c", code], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def human(n):
    for unit, size in (("MiB", 1 << 20), ("KiB", 1 << 10)):
        if abs(n) >= size:
            return f"{n / size:.1f} {unit}"
    return f"{n} B"


def table(results, scenario_name):
    rows = [
        "| server | variant | status | body ok | extra bytes | next request ok | iterator bytes | largest chunk | peak RSS + |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r["scenario"] != scenario_name:
            continue
        if "error" in r:
            rows.append(f"| {r['server']} | {r['variant']} | error: {r['error']} | | | | | | |")
            continue
        second = r.get("second_ok")
        rows.append(
            f"| {r['server']} | {r['variant']} | {r['status']} | {r['body_ok']} | {r['extra_bytes']} "
            f"| {'' if second is None else second} | {human(r['iterator_bytes'])} | {human(r['max_chunk'])} | {human(r['peak_rss_delta'])} |"
        )
    return "\n".join(rows)


def main():
    cfg = load_experiment(EXPERIMENT)
    parser = argparse.ArgumentParser()
    parser.add_argument("--variants", default=",".join(cfg["variants"]))
    parser.add_argument("--servers", default=",".join(cfg["servers"]))
    parser.add_argument("--scenarios", help="comma separated names, default all")
    parser.add_argument("--size", type=int, default=cfg["file_size"])
    parser.add_argument("--render-only", action="store_true", help="rebuild tables.md from results.json")
    args = parser.parse_args()

    data = sc.expected_data(args.size)
    wanted = args.scenarios.split(",") if args.scenarios else None
    chosen = [s for s in sc.scenarios(args.size) if wanted is None or s.name in wanted]
    results_dir = HERE / "results"
    results_dir.mkdir(exist_ok=True)

    results = []
    meta = {}
    if args.render_only:
        saved = json.loads((results_dir / "results.json").read_text())
        results, meta, args.size = saved["results"], saved["meta"], saved["size"]
    for variant in [] if args.render_only else args.variants.split(","):
        meta[variant] = versions(variant)
        for server in args.servers.split(","):
            print(f"== {variant} / {server}", flush=True)
            with ServerProcess(EXPERIMENT, variant, server, results_dir / "logs") as proc:
                sc.warm_up(proc.port)
                for scenario in chosen:
                    r = sc.run_scenario(scenario, proc.port, proc.pid, data)
                    r.update(variant=variant, server=server, scenario=scenario.name)
                    results.append(r)
                    print("  ", {k: v for k, v in r.items() if k not in ("variant", "server", "scenario")}, flush=True)

    saved_path = results_dir / "results.json"
    if not args.render_only and saved_path.exists():
        # keep earlier runs of variants and servers this run did not cover
        saved = json.loads(saved_path.read_text())
        ran = {(r["variant"], r["server"]) for r in results}
        results = [r for r in saved["results"] if (r["variant"], r["server"]) not in ran] + results
        meta = {**saved["meta"], **meta}
    if not args.render_only:
        (results_dir / "results.json").write_text(json.dumps({"meta": meta, "size": args.size, "results": results}, indent=2))
    out = ["# Results", "", f"File size: {args.size} bytes", "", "```json", json.dumps(meta, indent=2), "```", ""]
    for scenario in chosen:
        out += [f"## {scenario.name}", "", scenario.description or (scenario.range_header or ""), "", table(results, scenario.name), ""]
    (results_dir / "tables.md").write_text("\n".join(out))
    print("wrote", results_dir / "tables.md")


if __name__ == "__main__":
    main()
