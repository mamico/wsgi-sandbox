"""Build one venv and one Zope instance per variant of an experiment.

Usage: python -m wsgisandbox.envs {venvs,instances,setup} EXPERIMENT [--variants a,b]
"""

import argparse
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ZOPE_CONF = """\
%define INSTANCE {instance}
instancehome $INSTANCE
<zodb_db main>
    mount-point /
    cache-size 30000
    <filestorage>
      path $INSTANCE/var/Data.fs
      blob-dir $INSTANCE/var/blobstorage
    </filestorage>
</zodb_db>
"""


def load_experiment(name):
    path = ROOT / "experiments" / name / "experiment.toml"
    return tomllib.loads(path.read_text())


def variant_dir(experiment, variant):
    return ROOT / "variants" / experiment / variant


def venv_python(experiment, variant):
    return variant_dir(experiment, variant) / ".venv" / "bin" / "python"


def zope_conf(experiment, variant):
    return variant_dir(experiment, variant) / "instance" / "etc" / "zope.conf"


def run(*cmd, **kwargs):
    cmd = [str(c) for c in cmd]
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kwargs)


def make_venv(experiment, cfg, variant):
    venv = variant_dir(experiment, variant) / ".venv"
    py = venv / "bin" / "python"
    run("uv", "venv", "--python", cfg["python"], "--allow-existing", venv)
    requirements = []
    for req in cfg["requirements"]:
        requirements += ["-r", ROOT / req]
    run("uv", "pip", "install", "--python", py, *requirements, "-c", cfg["constraints"])
    # Constraints pin the released packages; install the variants on top of that.
    for package, spec in cfg["variants"][variant].get("overrides", {}).items():
        run("uv", "pip", "install", "--python", py, "--no-deps", "--reinstall", f"{package} @ {spec}")
    # Patches apply to the installed packages, for variants that have no commit.
    for patch in cfg["variants"][variant].get("patches", []):
        site_packages = subprocess.run(
            [py, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()  # fmt: skip
        patch_file = ROOT / "experiments" / experiment / patch
        run("patch", "-p1", "-d", site_packages, "-i", patch_file)


def make_instance(experiment, variant):
    instance = variant_dir(experiment, variant) / "instance"
    (instance / "etc").mkdir(parents=True, exist_ok=True)
    (instance / "var").mkdir(exist_ok=True)
    conf = zope_conf(experiment, variant)
    conf.write_text(ZOPE_CONF.format(instance=instance))
    print("wrote", conf)


def run_setup(experiment, cfg, variant):
    """Run the experiment's setup_site.py inside the variant, with a fresh Data.fs."""
    var = variant_dir(experiment, variant) / "instance" / "var"
    for leftover in list(var.glob("Data.fs*")):
        leftover.unlink()
    zconsole = venv_python(experiment, variant).parent / "zconsole"
    script = ROOT / "experiments" / experiment / "setup_site.py"
    run(
        zconsole,
        "run",
        zope_conf(experiment, variant),
        script,
        "--size",
        cfg["file_size"],
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["venvs", "instances", "setup"])
    parser.add_argument("experiment")
    parser.add_argument("--variants", help="comma separated, default all")
    args = parser.parse_args()
    cfg = load_experiment(args.experiment)
    variants = args.variants.split(",") if args.variants else list(cfg["variants"])
    for variant in variants:
        if args.step == "venvs":
            make_venv(args.experiment, cfg, variant)
        elif args.step == "instances":
            make_instance(args.experiment, variant)
        else:
            run_setup(args.experiment, cfg, variant)


if __name__ == "__main__":
    main()
