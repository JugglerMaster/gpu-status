# gpu-status

A terminal status monitor for the **Kindi** local LLM server. It queries the
Kindi server's `/health` endpoint and renders a compact live view: model,
context, uptime, GPU memory, busy state, queue and speculative drafting.

It is an **independent** implementation — it talks to Kindi's public
`/health` API and does not reuse Kindi or Kindi Bridge source code.

## License

Released under the **MIT License** (see [LICENSE](LICENSE)).

## Quick start

```sh
# one-shot against the default Kindi server (127.0.0.1:8093)
python3 gpu_status.py

# refresh every 2 seconds
python3 gpu_status.py --watch 2

# a remote Kindi server
python3 gpu_status.py --host 0.0.0.0 --port 8093

# raw /health JSON
python3 gpu_status.py --json
```

Or install it as a command:

```sh
pip install .
gpu-status --watch 2
```

## Options

| Option | Description |
|---|---|
| `--host`, `-h` | Kindi server host (default `127.0.0.1`) |
| `--port` | Kindi server port (default `8093`) |
| `--watch`, `-w N` | refresh every N seconds |
| `--json` | dump the raw `/health` JSON and exit |
| `--no-color`, `-n` | disable ANSI colors |

## What it shows

- **model / context / head / uptime** — from `/health`
- **GPU memory** — `gpu_free_mib` / `gpu_total_mib` with a usage bar
- **busy** — phase, elapsed time, tokens read/generated, cached
- **queue** — pending request counts
- **drafting** — speculative drafting on/off and acceptance

## Notes

- Uses only the Python standard library (no dependencies).
- Kindi's default port is `8093` on `127.0.0.1`; change with `--host`/`--port`.
- `/health` does not require an API key, so no credentials are needed.
