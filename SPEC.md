# gpu-status — spec

A terminal status monitor for the **Kindi** local LLM server. It emulates the
monitor experience of `kindi-bridge` (from the [kindi](https://github.com/ahtx/kindi)
repo) while remaining a fully independent, from-scratch implementation.

## Why / constraints

- **Emulate, don't copy.** `kindi-bridge` is **AGPL-3.0-only**. gpu-status is
  **MIT**. AGPL and MIT are not compatible in the direction we need, so we must
  **not reuse any kindi/kindi-bridge code**. We reimplement everything from
  scratch.
- **Own expression.** Same data and purpose, but our own layout, labels and
  headers — not a pixel clone of kindi-bridge's panels.
- **Only runtime dependency is the public `/health` API.** We talk to Kindi's
  public endpoint (a de facto protocol, no auth required). We never depend on
  kindi internals or kindi-bridge's state store.
- **Stdlib only.** No pip/venv, no psutil.
- **Independence is documented.** README carries an explicit AGPL note plus
  "tested against kindi 0.6.0" and the exact `/health` fields we depend on.

## Ground truth (verified on a live machine, `ollm`)

**nvidia-smi** (1× Tesla V100-16GB, driver 550.163.01):
```
0, Tesla V100-PCIE-16GB, 10137, 16384, 99, 78, 60.04, [N/A]
```
Fields (kindi-bridge's set): `index, name, memory.used, memory.total,
utilization.gpu, temperature.gpu, power.draw, fan.speed`.
Gotchas: `fan` can be `[N/A]` (V100 has no fan), `power` is a float, `name`
has a leading space.

**Live `/health`** (kindi 0.6.0):
```json
{"ok":true,"kindi":"0.6.0","commit":"179710c5e49d","model":"bonsai2-27b",
 "ctx":120000,"head":"exact","uptime_s":4034,"busy":null,
 "stats":{"requests":16,"prompt_tokens":399218,"cached_tokens":366145,
          "completion_tokens":35157},
 "drafting":{"enabled":false,"method":null,"drafter":null,"last":null},
 "queue":{"chat":0,"background":0,"yields":0},
 "gpu_free_mib":6007,"gpu_total_mib":16144}
```

**`/health` schema** (from `kindi/server.py`, authoritative):
```
ok, kindi, commit, model, ctx, head, uptime_s,
busy: null | {phase, elapsed_s, prompt_tokens, reused,
             prompt_read:"read/total", generated},
stats: {requests, prompt_tokens, cached_tokens, completion_tokens},
drafting: {enabled, method, drafter, last: null |
           {passes, drafted, accepted, acceptance}},
queue: {chat, background, yields},
gpu_free_mib, gpu_total_mib
```

**GPU-memory discrepancy (real):** `/health` reports 6007/16144 MiB; nvidia-smi
reports 10137/16384 MiB. Used matches (10137); **total differs by 240 MiB**
(driver-reserved — `/health` uses CUDA `memGetInfo`, nvidia-smi reports
physical). Hence a deliberate source choice (below).

## Grill log — questions → decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Topic / depth | Grill the single-command install + overall emulation; **full tree**. |
| 2 | Scope of emulation | **(a)** Unified single view: GPU vitals + inference telemetry. |
| 3 | nvidia-smi fields | **(a)** Full set, per-GPU. |
| 4 | Refresh + rendering | **(b)** 1s, clear-screen, no sparklines. |
| 5 | System vitals / deps | **(c)** Skip CPU/RAM/disk/net; GPU + inference only; stdlib only. |
| 6 | Independence / license | **(a)** Runtime = `/health` only; AGPL ⇒ no code reuse, own expression. |
| 7 | Output layout | **(a)** Own design (same data, own layout/labels). |
| 8 | API boundary | **(a)** Calling `/health` is fine (interoperability, not derivative work). |
| 9 | nvidia-smi failure | **(a)** Last known GPU data + `(stale)`. |
| 10 | Inference fields | **(a)** Add observed tok/s + stats. |
| 11 | README wording | **(a)** Explicit AGPL note. |
| 12 | Default mode + CLI | **(a)** Live watch on tty, one-shot when piped; `--once`; keep `--watch`. |
| 13 | Layout mode | **(b)** Variable-height line list (clear-screen each tick). |
| 14 | GPU memory source | **(a)** nvidia-smi only; `/health` as fallback. *(new — from live data)* |
| 15 | Testing | **(c)** Minimal (tok/s + nvidia-smi parsing), **fully automated**. |
| 16 | Server-down behavior | **(c)** Hybrid: stale ~5s, then `server down`. |
| 17 | Drift control | **(a)** Declare "tested against kindi 0.6.0" + field list. |
| 18 | Install / update | **(c)** Dedicated `gpu-status update` subcommand. |

## Final design

### Data
- **Inference** (from `/health`): `model, kindi, commit, ctx, head, uptime_s`;
  `busy {phase, elapsed_s, prompt_read, generated, reused}` + **computed tok/s**;
  `stats {requests, completion_tokens, cached_tokens}`;
  `drafting {enabled, method, last{drafted, accepted}}`;
  `queue {chat, background, yields}`.
- **GPU** (from `nvidia-smi`, per-GPU): `index, name, memory (used/total),
  utilization, temperature, power, fan`.
- **GPU memory bar** = nvidia-smi source; `/health` `gpu_free_mib/total_mib`
  only as fallback (no nvidia-smi / CPU mode).
- **No** system vitals (CPU/RAM/disk/net). **No** per-process table.

### Rendering
- 1s refresh, clear-screen, variable-height line list, no sparklines.
- Order: **inference first**, then GPU(s).
- Color on (disabled by `--no-color` or when not a tty).
- nvidia-smi failure → last GPU data + `(stale)`.
- kindi down → last inference + `(stale)` for ~5s, then `server down`.
- No-GPU → `GPU telemetry unavailable`; CPU mode → `cpu mode (no GPU memory reported)`.

### CLI
- `gpu-status` → live watch (tty) / one-shot (piped).
- `--once` one-shot · `--watch N` cadence · `--json` raw `/health` ·
  `--host`/`--port` · `--no-color` · `--version` · `gpu-status update`.

### License / independence
- MIT, from-scratch, no kindi code (AGPL). `/health` is the only runtime
  dependency (public API, no auth).
- README: explicit AGPL note + "tested against kindi **0.6.0**" + exact
  `/health` field list.

### Testing
- Minimal + fully automated: tok/s computation + nvidia-smi parsing
  (`test_gpu_status.py`, `unittest`/`pytest`).

### Install / update
- `install.sh` (existing) + `gpu-status update` (re-clone `main`, re-copy,
  print old→new).
- README: "re-run `install.sh` to update".

## Assumptions (decided, veto-able)
- `--version` = hardcoded `__version__` in the script.
- `gpu-status update`: hardcoded repo URL (matches `install.sh`), re-clone
  `main`, read new version from `pyproject.toml` (`tomllib`), atomic re-copy
  (temp+rename) only if version changed, print old→new.
- `/health` timeout = 2s (so the 1s loop doesn't stall).
- Stale marker on the section header; grace period = 5s.
- Loop = fetch + render, then sleep to ~1s cadence (effective interval ≥ 1s).
- No line-wrapping (lines stay short).
- Multi-GPU coded for N (can't test live — ollm has 1 GPU).

## Open items / future
- Multi-GPU live verification (need a multi-GPU box).
- Busy-state live capture (was `null` on ollm; schema taken from source).
- Whether `--json` should ever include nvidia-smi / computed fields (currently
  raw `/health` only, for a stable contract).
- `gpu-status update` behavior when installed from a non-canonical source.
