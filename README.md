# gpu-status

A terminal status monitor for the **Kindi** local LLM server. It queries the
Kindi server's `/health` endpoint and local `nvidia-smi`, and renders a compact
live view: model, context, uptime, per-GPU memory/utilization/temperature/power,
busy state with observed **tok/s**, request stats, queue and speculative
drafting.

It is an **independent** implementation. It talks to Kindi's public `/health`
API (a de facto protocol, no auth required) and does **not** reuse Kindi or
[Kindi Bridge](https://github.com/ahtx/kindi) source code.

## License

Released under the **MIT License** (see [LICENSE](LICENSE)).

> **Independence note.** [Kindi](https://github.com/ahtx/kindi) and
> [Kindi Bridge](https://github.com/ahtx/kindi-bridge) are released under the
> **AGPL-3.0-only** license, which is not compatible with this project's MIT
> license. This project is written from scratch and depends on Kindi's public
> `/health` endpoint at runtime only. It is not a derivative work of Kindi or
> Kindi Bridge code.

## Tested against

- **Kindi `0.6.0`** — the `/health` fields used below are the exact shape
  Kindi 0.6.0 emits. If you run a different Kindi version, some fields may
  differ.

The `/health` fields this tool depends on:
`ok, kindi, commit, model, ctx, head, uptime_s,
busy{phase, elapsed_s, prompt_read, generated, reused},
stats{requests, prompt_tokens, cached_tokens, completion_tokens},
drafting{enabled, method, drafter, last{passes, drafted, accepted, acceptance}},
queue{chat, background, yields}, gpu_free_mib, gpu_total_mib`.

## Install (single command)

The script is stdlib-only (no dependencies), so the installer just drops an
executable `gpu-status` into your `~/.local/bin`. Run it from the repo:

```sh
git clone https://github.com/JugglerMaster/gpu-status.git
cd gpu-status
./install.sh
```

Or as a single line (it clones itself):

```sh
curl -fsSL https://raw.githubusercontent.com/JugglerMaster/gpu-status/main/install.sh | bash
```

After that, `gpu-status` is on your PATH.

## Usage

```sh
# live monitor (default in a terminal; one-shot when piped)
gpu-status

# single read and exit
gpu-status --once

# refresh every 2 seconds
gpu-status --watch 2

# a remote Kindi server
gpu-status --host 0.0.0.0 --port 8093

# raw /health JSON
gpu-status --json
```

You can also run the script directly without installing:

```sh
python3 gpu_status.py --watch 2
```

## Options

| Option | Description |
|---|---|
| `--host` | Kindi server host (default `127.0.0.1`) |
| `--port` | Kindi server port (default `8093`) |
| `--watch`, `-w N` | refresh every N seconds (default `1.0`) |
| `--once` | single read and exit (default when stdout is not a tty) |
| `--json` | dump the raw `/health` JSON and exit |
| `--no-color`, `-n` | disable ANSI colors |
| `--version` | print version and exit |

Subcommands:

| Command | Description |
|---|---|
| `gpu-status update` | re-clone the repo and re-copy the script if a newer version exists |

## What it shows

- **model / kindi / commit / context / head / uptime** — from `/health`
- **GPU** — per-GPU memory, utilization, temperature, power, fan from
  `nvidia-smi`. The `/health` `gpu_free_mib`/`gpu_total_mib` values are used
  only as a fallback when `nvidia-smi` is unavailable.
- **busy** — phase, elapsed time, tokens read/generated, cached, and observed
  **tok/s**
- **stats** — total requests, generated, and cached tokens
- **queue** — pending request counts
- **drafting** — speculative drafting on/off and acceptance

## Notes

- Uses only the Python standard library (no dependencies).
- Kindi's default port is `8093` on `127.0.0.1`; change with `--host`/`--port`.
- `/health` does not require an API key, so no credentials are needed.
- GPU memory comes from `nvidia-smi` (physical, includes driver-reserved
  memory); `/health` reports the CUDA-visible amount, so the two totals can
  differ by a couple hundred MiB.
- When Kindi is down, the last inference view is kept for ~5 s (marked
  `stale`) before switching to `server down`. A failed `nvidia-smi` keeps the
  last GPU view, marked `(stale)`.
