# fpgacapZero web frontend (Vite + React + TS)

Browser UI for fpgacapZero. It talks to the backend (`fcapz-web`) using the
**unified JSON-RPC API** — every action is a `POST /api/rpc` with a
`{"cmd": ...}` body (see [`../../host/fcapz/web/README.md`](../../host/fcapz/web/README.md)
and [JSON-RPC chapter](../../docs/11_rpc_server.md)).

## Develop

```bash
# 1) backend (serves /api on :8000)
pip install -e ".[web]" && fcapz-web

# 2) this app (Vite dev server on :5173, proxies /api -> :8000)
cd web/frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Enter your board's connection params (for the
Gowin BRS board: backend `openocd`, port `6666`, TAP `GW1NR-9C.tap`, IR table
`gowin`, chain `1`).

## Build (production)

```bash
npm run build
```

This emits the bundle straight into `host/fcapz/web/static/`, which `fcapz-web`
serves at `/` (and which ships in the Python wheel). After building, just run
`fcapz-web` and open <http://localhost:8000> — no separate dev server.

## Layout

| File | |
|---|---|
| `src/api.ts` | the `rpc(cmd, params)` client + shared types |
| `src/App.tsx` | layout; holds the active connection params + identity |
| `src/components/ConnectionPanel.tsx` | connect / probe / disconnect |
| `src/components/ElaPanel.tsx` | capture form |
| `src/components/Waveform.tsx` | canvas trace of a capture |
| `src/components/EioPanel.tsx` | attach EIO, poll inputs, toggle outputs |

v1 covers the core debug loop (connection + ELA capture + waveform + EIO);
AXI/UART panels reuse the same `axi_*` / `uart_*` commands when added.
