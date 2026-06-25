# Vendored Surfer waveform viewer (WASM)

This directory contains a **prebuilt, unmodified** copy of the
[Surfer](https://gitlab.com/surfer-project/surfer) waveform viewer, compiled to
WebAssembly, embedded by fpgacapZero's web frontend to render ELA captures.

It lives under `web/vendor/` (not `web/static/`) on purpose: `static/` is the
Vite build output and gets emptied on every `npm run build`, which would delete
this bundle. The server mounts this dir separately at `/surfer`.

- **Upstream:** https://gitlab.com/surfer-project/surfer
- **Vendored from:** https://app.surfer-project.org/ on 2026-06-25
- **Closest released version:** v0.7.0
- **License:** EUPL-1.2 (see `LICENSE.EUPL-1.2.txt`) — © the Surfer project
  contributors. Surfer is bundled here as a **separate aggregated application**
  (its own files, loaded in an iframe); it is not linked into or derived from
  fpgacapZero's Apache-2.0 source.

## Files

| File | Origin |
|------|--------|
| `surfer_bg.wasm` | Surfer, verbatim (SRI `sha384-DRshTXKEreJf7GewBQjhPy/fUuq/DRBnaAwLUNGZoeKmVXpxKVoECkqGF8sxl2I9`) |
| `surfer.js` | Surfer wasm-bindgen loader, verbatim (SRI `sha384-Kc5ZVkDQDk7t3Zkgls2HjZa6/RXuuuARTkkR5WyevFHvZQkaqAFVbdpXJTrePLUk`) |
| `integration.js` | Surfer iframe `postMessage` bridge, verbatim |
| `manifest.json` | Surfer PWA manifest, verbatim |
| `index.html` | Surfer page — **only change:** the service-worker registration is removed (we serve offline, no PWA cache) |
| `LICENSE.EUPL-1.2.txt` | Canonical EUPL-1.2 text (SPDX) |

## How it's driven

The frontend embeds `index.html` in an iframe and loads a capture with:

```js
iframe.contentWindow.postMessage({ command: "LoadUrl", url: "<vcd blob url>" }, "*")
```

The VCD comes from the unified RPC `capture` command (`include_vcd: true`),
produced by `Analyzer.export_vcd_text` — the same exporter the desktop GUI and
CLI use.

## Updating

Re-download the five upstream files from app.surfer-project.org, re-strip the
service-worker `<script>` from `index.html`, and refresh the SRI hashes above.
