#!/usr/bin/env python3
"""gpu-status: a terminal monitor for the Kindi local LLM server.

Queries the Kindi server's /health endpoint and renders a compact status
view: model, context, uptime, GPU memory, busy state, queue and drafting.

No external dependencies — standard library only.

Usage:
    gpu-status                          # one-shot against 127.0.0.1:8093
    gpu-status --host 0.0.0.0 --port 8093
    gpu-status --watch 2                # refresh every 2 seconds
    gpu-status --json                   # dump the raw /health JSON
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

__version__ = "0.2.1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = "8093"
TIMEOUT = 2.0
STALE_GRACE = 5.0
REPO_URL = "https://github.com/JugglerMaster/gpu-status.git"
BRANCH = "main"


# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
class C:
    """ANSI colors; no-ops when disabled (not a tty or --no-color)."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _fg(self, code: str) -> str:
        return f"\033[{code}m" if self.enabled else ""

    def reset(self) -> str:
        return "\033[0m" if self.enabled else ""

    def bold(self, s: str) -> str:
        return self._fg("1") + s + self.reset()

    def green(self, s: str) -> str:
        return self._fg("32") + s + self.reset()

    def yellow(self, s: str) -> str:
        return self._fg("33") + s + self.reset()

    def red(self, s: str) -> str:
        return self._fg("31") + s + self.reset()

    def dim(self, s: str) -> str:
        return self._fg("90") + s + self.reset()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def fmt_num(n) -> str:
    """Commas for big integers; leave None/floats alone."""
    if n is None:
        return ""
    if isinstance(n, float):
        return f"{n:,.0f}"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def fmt_dur(seconds) -> str:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "?"
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    if h:
        return f"{h}h {m:02d}m {sec:02d}s"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


def bar(pct: float, width: int = 24) -> str:
    pct = max(0.0, min(1.0, pct))
    filled = int(round(pct * width))
    return "#" * filled + "-" * (width - filled)


def clear_screen() -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def fetch_health(host: str, port: str, timeout: float = TIMEOUT) -> dict:
    url = f"http://{host}:{port}/health"
    req = urllib.request.Request(url, headers={"User-Agent": "gpu-status/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# nvidia-smi
# ---------------------------------------------------------------------------
NVSMI_FIELDS = [
    "index", "name", "memory.used", "memory.total",
    "utilization.gpu", "temperature.gpu", "power.draw", "fan.speed",
]
NVSMI_TIMEOUT = 3.0


def _num(v):
    """Coerce an nvidia-smi CSV field to int/float; None for [N/A]/blank/odd."""
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "[N/A]", "N/A", "n/a", "-"):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def parse_nvidia_csv(text: str) -> list:
    """Parse `nvidia-smi --format=csv,noheader,nounits` output into per-GPU dicts.

    Returns a list of dicts keyed by NVSMI_FIELDS. Malformed/short rows are
    skipped. Numeric fields are coerced (int when whole); [N/A] -> None.
    """
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        fields = next(csv.reader([line]), [])
        if len(fields) != len(NVSMI_FIELDS):
            continue
        d = dict(zip(NVSMI_FIELDS, fields))
        d["index"] = _num(d["index"])
        d["name"] = (d.get("name") or "").strip()
        for k in ("memory.used", "memory.total", "utilization.gpu",
                  "temperature.gpu", "power.draw", "fan.speed"):
            d[k] = _num(d[k])
        rows.append(d)
    return rows


def fetch_nvidia_smi() -> list:
    """Query the local GPUs. Returns per-GPU dicts; [] if nvidia-smi is absent
    or errors (no GPU, CPU-only box, driver hiccup)."""
    try:
        p = subprocess.run(
            ["nvidia-smi", "--query-gpu=" + ",".join(NVSMI_FIELDS),
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=NVSMI_TIMEOUT,
        )
        if p.returncode != 0:
            return []
        return parse_nvidia_csv(p.stdout)
    except (OSError, FileNotFoundError, subprocess.TimeoutExpired):
        return []


# ---------------------------------------------------------------------------
# Observed generation rate (tok/s)
# ---------------------------------------------------------------------------
class TokenRate:
    """Feed /health samples; yield observed tok/s for the active request.

    Rate = (generated_now - generated_prev) / dt, only when the same request
    is still in flight (prompt_tokens unchanged), generation advanced, and at
    least min_window seconds elapsed since the previous sample. Returns None
    when there's no rate to show (idle, prompt-read, first sample).
    """

    def __init__(self, min_window: float = 0.4):
        self.min_window = min_window
        self._last = None  # (prompt_tokens, generated, t)

    def update(self, busy, now):
        if not busy:
            self._last = None
            return None
        generated = busy.get("generated") or 0
        prompt_tokens = busy.get("prompt_tokens")
        rate = None
        if self._last is not None:
            last_prompt, last_generated, last_t = self._last
            if prompt_tokens == last_prompt:
                dt = now - last_t
                if dt >= self.min_window and generated > last_generated:
                    rate = (generated - last_generated) / dt
        self._last = (prompt_tokens, generated, now)
        return rate if rate is not None and rate > 0 else None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def render(data, c, host, port, gpu, gpu_stale, tok_s,
           server_down, infer_stale) -> str:
    lines = [c.bold("  kindi   gpu-status")]

    if server_down:
        if data is None:
            lines.append(c.red(f"  server  {host}:{port}  down"))
        else:
            lines.append(c.red(f"  server  {host}:{port}  down") +
                         c.dim("   (stale data below)"))
    elif infer_stale:
        lines.append(c.dim(f"  server  {host}:{port}  ") + c.yellow("ok (stale)"))
    else:
        lines.append(c.dim(f"  server  {host}:{port}  ") + (
            c.green("ok") if (data and data.get("ok")) else c.red("unavailable")
        ))
    lines.append("")

    # ---- inference (from /health) ----
    if data:
        model = data.get("model", "?")
        kindi_ver = data.get("kindi", "?")
        commit = data.get("commit", "")
        ctx = data.get("ctx", "?")
        head = data.get("head", "?")
        uptime = data.get("uptime_s", 0)

        lines.append(f"  model    {model}")
        commit_part = f"  ({commit[:7]})" if commit else ""
        lines.append(f"  kindi    {kindi_ver}{commit_part}")
        lines.append(f"  context  {fmt_num(ctx)} tokens")
        lines.append(f"  head     {head}      uptime {fmt_dur(uptime)}")

        # Busy state + tok/s
        busy = data.get("busy")
        lines.append("")
        if busy:
            phase = busy.get("phase", "busy")
            elapsed = fmt_dur(busy.get("elapsed_s", 0))
            rate_str = f"  {tok_s:5.1f} tok/s" if tok_s is not None else "  -- tok/s"
            lines.append(c.yellow(f"  busy     {phase}  ({elapsed})"))
            parts = []
            if busy.get("prompt_read"):
                parts.append(f"read {busy['prompt_read']}")
            if busy.get("generated") is not None:
                parts.append(f"generated {fmt_num(busy['generated'])}")
            if busy.get("reused") is not None:
                parts.append(f"cached {fmt_num(busy['reused'])}")
            if parts:
                lines.append("           " + "  ".join(parts) + rate_str)
            else:
                lines.append(f"           {rate_str}")
        else:
            lines.append(c.green("  busy     idle"))

        # Stats
        stats = data.get("stats") or {}
        if isinstance(stats, dict) and stats:
            lines.append(f"  stats    req {fmt_num(stats.get('requests'))}  "
                         f"gen {fmt_num(stats.get('completion_tokens'))}  "
                         f"cache {fmt_num(stats.get('cached_tokens'))}")

        # Queue + drafting
        queue = data.get("queue") or {}
        drafting = data.get("drafting") or {}
        if isinstance(queue, dict) and queue:
            qparts = [f"{k}={v}" for k, v in queue.items()]
            lines.append("  queue    " + "  ".join(qparts))
        if drafting.get("enabled"):
            last = drafting.get("last") or {}
            extra = ""
            if last:
                extra = f"  last {fmt_num(last.get('accepted'))}/{fmt_num(last.get('drafted'))} accepted"
            lines.append(f"  drafting {drafting.get('method') or '?'}{extra}")
    else:
        lines.append(c.dim("  (no inference data yet)"))

    # ---- GPU (from nvidia-smi) ----
    lines.append("")
    if not gpu:
        lines.append("  GPU      telemetry unavailable (no nvidia-smi / no GPU)")
    else:
        stale = c.dim("  (stale)") if gpu_stale else ""
        for g in gpu:
            idx = g.get("index", "?")
            name = g.get("name", "?")
            used = g.get("memory.used")
            total = g.get("memory.total")
            util = g.get("utilization.gpu")
            temp = g.get("temperature.gpu")
            power = g.get("power.draw")
            fan = g.get("fan.speed")

            lines.append(f"  GPU {idx}  {name}{stale}")
            if used is not None and total:
                pct = used / total
                color = c.green if pct < 0.8 else (c.yellow if pct < 0.95 else c.red)
                lines.append(f"    mem   {fmt_num(used)} / {fmt_num(total)} MiB   {pct * 100:5.0f}%")
                lines.append(f"          {color(bar(pct))}")
            else:
                lines.append(f"    mem   {fmt_num(used) if used is not None else '?'} / "
                             f"{fmt_num(total or '?')} MiB")
            vitals = []
            if util is not None:
                vitals.append(f"util {util}%")
            if temp is not None:
                vitals.append(f"temp {temp}\u00b0C")
            if power is not None:
                vitals.append(f"power {power}W")
            if fan is not None:
                vitals.append(f"fan {fan}%")
            if vitals:
                lines.append(f"    {'  '.join(vitals)}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Terminal status monitor for the Kindi local LLM server.",
        prog="gpu-status",
    )
    p.add_argument("--host", default=DEFAULT_HOST,
                   help=f"Kindi server host (default {DEFAULT_HOST})")
    p.add_argument("--port", default=DEFAULT_PORT,
                   help=f"Kindi server port (default {DEFAULT_PORT})")
    p.add_argument("--watch", "-w", type=float, metavar="SECONDS",
                   help="refresh every N seconds (default 1.0)")
    p.add_argument("--once", action="store_true",
                   help="single read and exit (default when stdout is not a tty)")
    p.add_argument("--json", action="store_true",
                   help="dump the raw /health JSON and exit")
    p.add_argument("--no-color", "-n", action="store_true",
                   help="disable ANSI colors")
    p.add_argument("--version", action="store_true",
                   help="print version and exit")
    return p


def do_update() -> int:
    """Re-clone the repo; re-copy gpu_status.py if a newer version exists."""
    import re
    import tempfile

    def _read_version(path):
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        return m.group(1) if m else None

    def _ver_tuple(v):
        return tuple(int(x) for x in str(v).split(".") if x.isdigit())

    bin_dir = os.path.expanduser("~/.local/bin")
    bin_path = os.path.join(bin_dir, "gpu-status")
    cur_ver = __version__
    try:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", BRANCH, REPO_URL, tmp],
                check=True,
            )
            new_ver = _read_version(os.path.join(tmp, "pyproject.toml"))
            if new_ver and _ver_tuple(new_ver) <= _ver_tuple(cur_ver):
                print(f"already up to date ({cur_ver})")
                return 0
            with tempfile.NamedTemporaryFile("w", dir=bin_dir, delete=False) as tf:
                with open(os.path.join(tmp, "gpu_status.py"), "r",
                          encoding="utf-8") as sf:
                    tf.write(sf.read())
                tmp_path = tf.name
            os.replace(tmp_path, bin_path)
            os.chmod(bin_path, 0o755)
            print(f"updated {cur_ver} -> {new_ver}")
            return 0
    except Exception as e:  # noqa: BLE001
        print(f"update failed: {e}")
        return 1


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "update":
        return do_update()

    args = build_parser().parse_args(argv)
    c = C(enabled=sys.stdout.isatty() and not args.no_color)

    if args.version:
        print(f"gpu-status {__version__}")
        return 0

    if args.json:
        try:
            data = fetch_health(args.host, args.port)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": str(e)}, indent=2))
            return 1
        print(json.dumps(data, indent=2))
        return 0

    is_tty = sys.stdout.isatty()
    watch = (not args.once) and (args.watch is not None or is_tty)
    interval = max(0.1, args.watch or 1.0)

    rate = TokenRate()
    last_infer = None
    last_infer_t = None
    last_gpu = None

    def frame() -> None:
        nonlocal last_infer, last_infer_t, last_gpu
        now = time.monotonic()

        data = None
        try:
            data = fetch_health(args.host, args.port)
        except Exception:  # noqa: BLE001
            data = None
        fetch_ok = bool(data.get("ok")) if data else False
        if fetch_ok:
            last_infer = data
            last_infer_t = now

        gpu = fetch_nvidia_smi()
        gpu_ok = bool(gpu)
        if gpu_ok:
            last_gpu = gpu

        tok_s = rate.update(data.get("busy") if data else None, now)

        infer_stale = (not fetch_ok) and (last_infer is not None) \
            and (now - last_infer_t <= STALE_GRACE)
        server_down = (last_infer is None) or \
            (not fetch_ok and (now - last_infer_t) > STALE_GRACE)
        gpu_stale = (not gpu_ok) and (last_gpu is not None)

        if is_tty:
            clear_screen()
        print(render(last_infer, c, args.host, args.port,
                     last_gpu, gpu_stale, tok_s, server_down, infer_stale))
        sys.stdout.flush()

    if not watch:
        frame()
        return 0

    try:
        while True:
            frame()
            time.sleep(interval)
    except KeyboardInterrupt:
        if is_tty:
            clear_screen()
        print("\033[0m")
        print(c.dim("  stopped"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
