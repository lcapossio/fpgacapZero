# fpgacapZero web frontend

A browser-based front-end for fpgacapZero — an alternative to the desktop GUI
(`fcapz-gui`) that's reachable from the local machine **or another machine on
the network**. It's a small **FastAPI** backend that wraps the fcapz host stack,
plus a built browser UI it serves as static files.

> Status: **complete and hardware-validated.** The browser UI (Vite + React,
> built into `web/frontend/`) and the FastAPI backend both ship; `fcapz-web`
> serves the built app at `/` alongside the JSON API below. User-facing docs
> are in the manual's [Web interface chapter](../../../docs/18_web_interface.md).

## Install & run

```bash
pip install -e ".[web]"     # adds fastapi + uvicorn
fcapz-web                    # serves on http://127.0.0.1:7373
```

Then open <http://127.0.0.1:7373>. Connection parameters (backend, tap, IR
table, …) are entered in the UI, not on the command line — one server can point
at whatever board you connect to.

### Reaching it from another machine

```bash
fcapz-web --host 0.0.0.0 --port 7373 --token "$(openssl rand -hex 16)"
```

`--host 0.0.0.0` exposes it on the network. **Set `--token`** (or
`FCAPZ_WEB_TOKEN`) when you do — it's required as `Authorization: Bearer <token>`
on every `/api` route and as `?token=` on the WebSocket. There is no TLS; put it
behind a reverse proxy / SSH tunnel if it leaves a trusted network.

## API (v1 — core debug loop)

The web server speaks the **same JSON-RPC `cmd` protocol** as
`python -m fcapz.rpc` (stdin/stdout) — one unified API, two browser transports:

| Transport | Endpoint | Shape |
|---|---|---|
| HTTP | `POST /api/rpc` | body is one request `{"cmd": ...}`; returns the response envelope |
| WebSocket | `/api/ws` | send request objects, receive response objects (lower latency; used for live polling) |

Every command, request field, and response field is exactly the JSON-RPC
contract documented in [chapter 11](../../../docs/11_rpc_server.md): `connect`,
`probe`, `configure`, `arm`, `capture`, `eio_connect` / `eio_read` /
`eio_write`, `axi_*`, `uart_*`. **Errors are in-band** (`{"ok": false, "error":
..., "type": ...}`), so a bad command still returns HTTP 200 — matching the
line-protocol semantics.

```bash
# probe over HTTP (same JSON you'd pipe to `python -m fcapz.rpc`)
curl -s localhost:7373/api/rpc -d '{"cmd":"connect","backend":"openocd","tap":"GW1NR-9C.tap","ir_table":"gowin","chain":1}'
curl -s localhost:7373/api/rpc -d '{"cmd":"probe"}'
```

Gowin example: `connect` with `ir_table:"gowin"`, `tap:"GW1NR-9C.tap"`,
`chain:1`; the shared-chain EIO is `eio_connect` with `chain:1, base_addr:32768`
(`0x8000`).

## Architecture

- The browser uses the **same API as every other fcapz consumer** — there is no
  bespoke web protocol. The server is a thin **gateway** (`RpcGateway`) over one
  `fcapz.rpc.RpcServer` instance.
- One physical board = one serialized session: a re-entrant lock guards the
  single `RpcServer`, so all connected browsers share it safely.
- Blocking JTAG runs in a threadpool so the event loop stays responsive while a
  capture waits for its trigger.
- `ir_table` (Gowin/UltraScale), the ELA `chain`, and the EIO `base_addr` were
  added to `RpcServer` itself, so the whole unified API — CLI-piped RPC and web
  alike — can drive Gowin.

## Frontend dev workflow (Vite + React)

The browser UI source lives in `web/frontend/` (repo-relative). During
development run the Vite dev server and proxy `/api` to the backend:

```bash
cd web/frontend && npm install && npm run dev   # http://localhost:5173
fcapz-web                                        # backend on :7373
```

For a release build, `npm run build` outputs to `host/fcapz/web/static/`, which
`fcapz-web` serves directly (and which ships in the wheel as package data).
