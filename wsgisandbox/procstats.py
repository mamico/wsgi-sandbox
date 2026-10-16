"""Per-process-tree counters read from /proc: bytes read and peak RSS."""

import psutil


def tree(pid):
    proc = psutil.Process(pid)
    return [proc, *proc.children(recursive=True)]


def read_chars(pid):
    """Total bytes the process tree asked read() for (the rchar counter)."""
    return sum(p.io_counters().read_chars for p in tree(pid))


def _status_kb(pid, field):
    with open(f"/proc/{pid}/status") as f:
        for line in f:
            if line.startswith(field + ":"):
                return int(line.split()[1])
    return 0


def rss(pid):
    return sum(_status_kb(p.pid, "VmRSS") for p in tree(pid)) * 1024


def reset_peak(pid):
    """Reset VmHWM, the peak RSS, of every process in the tree."""
    for p in tree(pid):
        with open(f"/proc/{p.pid}/clear_refs", "w") as f:
            f.write("5")


def peak_rss(pid):
    return sum(_status_kb(p.pid, "VmHWM") for p in tree(pid)) * 1024
