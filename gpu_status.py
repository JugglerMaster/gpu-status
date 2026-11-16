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
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = "8093"
TIMEOUT = 5.0


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
    if os.isatty(sys.stdout):
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
# Rendering
# ---------------------------------------------------------------------------
def render(data: dict, c: C, host: str, port: str) -> str:
    lines = [
        c.bold("  kindi   gpu-status"),
        c.dim(f"  server  {host}:{port}  ") + (
            c.green("ok") if data.get("ok") else c.red("unavailable")
        ),
        "",
    ]

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

    # GPU memory
    free = data.get("gpu_free_mib", 0)
    total = data.get("gpu_total_mib", 0)
    lines.append("")
    if total and total > 0:
        used = total - free
        pct = used / total
        color = c.green if pct < 0.8 else (c.yellow if pct < 0.95 else c.red)
        lines.append(f"  GPU      {fmt_num(used)} MiB / {fmt_num(total)} MiB   {pct * 100:5.0f}%")
        lines.append(f"           {color(bar(pct))}")
    else:
        lines.append("  GPU      cpu mode (no GPU memory reported)")

    # Busy state
    busy = data.get("busy")
    lines.append("")
    if busy:
        phase = busy.get("phase", "busy")
        elapsed = fmt_dur(busy.get("elapsed_s", 0))
        lines.append(c.yellow(f"  busy     {phase}  ({elapsed})"))
        parts = []
        if busy.get("prompt_read"):
            parts.append(f"read {busy['prompt_read']}")
        if busy.get("generated") is not None:
            parts.append(f"generated {fmt_num(busy['generated'])}")
        if busy.get("reused") is not None:
            parts.append(f"cached {fmt_num(busy['reused'])}")
        if parts:
            lines.append("           " + "  ".join(parts))
    else:
        lines.append(c.green("  busy     idle"))

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

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Terminal status monitor for the Kindi local LLM server."
    )
    p.add_argument("--host", default=DEFAULT_HOST, help=f"Kindi server host (default {DEFAULT_HOST})")
    p.add_argument("--port", default=DEFAULT_PORT, help=f"Kindi server port (default {DEFAULT_PORT})")
    p.add_argument("--watch", "-w", type=float, metavar="SECONDS",
                   help="refresh every N seconds (e.g. 2) instead of a single read")
    p.add_argument("--json", action="store_true", help="dump the raw /health JSON and exit")
    p.add_argument("--no-color", "-n", action="store_true", help="disable ANSI colors")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    c = C(enabled=sys.stdout.isatty() and not args.no_color)

    if args.json:
        try:
            data = fetch_health(args.host, args.port)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"ok": False, "error": str(e)}, indent=2))
            return 1
        print(json.dumps(data, indent=2))
        return 0

    def run_once() -> None:
        try:
            data = fetch_health(args.host, args.port)
            print(render(data, c, args.host, args.port))
        except (urllib.error.URLError, urllib.error.HTTPError, ConnectionError,
                json.JSONDecodeError, ValueError) as e:
            print(c.red(f"  server {args.host}:{args.port} unreachable: {e}"))
            sys.stdout.write(c.dim("  is a Kindi server running on that host/port?\n"))
            return 1
        return 0

    if args.watch:
        interval = max(0.1, args.watch)
        try:
            while True:
                clear_screen()
                rc = run_once()
                if rc == 1:
                    time.sleep(interval)
                else:
                    time.sleep(interval)
        except KeyboardInterrupt:
            clear_screen()
            print("\033[0m")  # reset any leftover color
            print(c.dim("  stopped"))
        return 0

    return run_once()


if __name__ == "__main__":
    raise SystemExit(main())
