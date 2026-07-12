# fpgacapZero web frontend (Vite + React + TS)

Browser UI for fpgacapZero. It talks to the backend (`fcapz-web`) using the
**unified JSON-RPC API** — every action is a `POST /api/rpc` with a
`{"cmd": ...}` body (see [`../../host/fcapz/web/README.md`](../../host/fcapz/web/README.md)
and [JSON-RPC chapter](../../docs/11_rpc_server.md)).

## Develop

```bash
# 1) backend (serves /api on :7373)
pip install -e ".[web]" && fcapz-web

# 2) this app (Vite dev server on :5173, proxies /api and /surfer -> :7373)
cd web/frontend
npm install
npm run dev
```

Open <http://localhost:5173> and press **Connect** — compatible boards are
discovered automatically (the IR table is inferred server-side from the tap
name). Host/port/tap can be overridden in the Connection panel when needed.

## Test

```bash
npm test          # vitest unit tests (api.ts parsing + rpc error contract)
```

CI runs these in the `frontend-build` job before rebuilding the bundle.

## Build (production)

```bash
npm run build
```

This emits the bundle straight into `host/fcapz/web/static/`, which `fcapz-web`
serves at `/` (and which ships in the Python wheel). After building, just run
`fcapz-web` and open <http://localhost:7373> — no separate dev server.

The built bundle **is committed to git**, so `fcapz-web` works from a fresh
checkout (and the wheel) without Node. When you change anything under `src/`,
re-run `npm run build` and commit the updated `host/fcapz/web/static/`.

## Layout

| File | |
|---|---|
| `src/api.ts` | the `rpc(cmd, params)` client + shared types |
| `src/App.tsx` | dockable tab layout + Tabs menu (toggle panels, reset layout) |
| `src/session.tsx` | shared session state (ELA config, last capture) |
| `src/components/ConnectionPanel.tsx` | discover / connect / cores list / disconnect |
| `src/components/ElaPanel.tsx` | capture configuration (trigger, probes, advanced) |
| `src/components/RunPanel.tsx` | Arm / Trigger Immediate / Auto re-arm / downloads |
| `src/components/SurferView.tsx` | embedded Surfer waveform viewer (iframe at `/surfer`) |
| `src/components/EioPanel.tsx` | attach EIO, poll inputs, toggle outputs |
| `src/components/AxiPanel.tsx` | JTAG-AXI bridge: read/write/dump |
