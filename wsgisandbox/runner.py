"""Start and stop one server process for one variant."""

import socket
import subprocess
import time
from pathlib import Path

from wsgisandbox.envs import ROOT, venv_python, zope_conf


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerProcess:
    def __init__(self, experiment, variant, server, log_dir, startup_timeout=180):
        self.port = free_port()
        self.startup_timeout = startup_timeout
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log = open(log_dir / f"{variant}-{server}.log", "wb")
        self.cmd = [
            str(venv_python(experiment, variant)),
            str(ROOT / "wsgisandbox" / "serve.py"),
            "--server", server,
            "--zope-conf", str(zope_conf(experiment, variant)),
            "--port", str(self.port),
        ]  # fmt: skip

    def __enter__(self):
        self.proc = subprocess.Popen(self.cmd, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited with {self.proc.returncode}, see {self.log.name}")
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
                return self
            except OSError:
                time.sleep(0.5)
        self.proc.kill()
        raise RuntimeError(f"server did not listen within {self.startup_timeout}s, see {self.log.name}")

    def __exit__(self, *exc):
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        self.log.close()

    @property
    def pid(self):
        return self.proc.pid
