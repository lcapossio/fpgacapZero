import { useEffect, useRef, useState } from "react";
import { parseIntFlexible, rpc } from "../api";
import type { ConnectionParams, RpcResponse } from "../api";

function range(n: number): number[] {
  return Array.from({ length: n }, (_, i) => i);
}

const POLL_PRESETS = [25, 50, 100, 250, 500, 1000];

export function EioPanel({ conn }: { conn: ConnectionParams }) {
  const gowin = conn.ir_table === "gowin";
  const [phase, setPhase] = useState<"discovering" | "attached" | "manual">(
    "discovering",
  );
  const [chain, setChain] = useState(gowin ? "1" : "3");
  const [base, setBase] = useState(gowin ? "0x8000" : "0x0");
  const [inW, setInW] = useState(0);
  const [outW, setOutW] = useState(0);
  // JS bitwise operators are 32-bit; EIO can be multiword, so track bits as BigInt.
  const [inputs, setInputs] = useState(0n);
  const [outputs, setOutputs] = useState(0n);
  const [poll, setPoll] = useState(true);
  const [pollMs, setPollMs] = useState(250);
  const [error, setError] = useState("");
  const timer = useRef<number | null>(null);
  // At most one eio_read outstanding: the server serializes commands behind a
  // lock, so unguarded ticks pile up (and time out) whenever a capture holds
  // the lock for seconds. Skipped ticks just wait for the next interval.
  const reading = useRef(false);

  async function readInputs() {
    if (reading.current) return;
    reading.current = true;
    try {
      const r = await rpc("eio_read");
      // Prefer value_hex (full width) over the JS-lossy numeric value.
      setInputs(BigInt(((r.value_hex ?? r.value) as string | number)));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      reading.current = false;
    }
  }

  function applyAttached(r: RpcResponse) {
    setInW(r.in_w as number);
    setOutW(r.out_w as number);
    setChain(String(r.chain));
    setBase("0x" + (r.base_addr as number).toString(16));
    setPhase("attached");
  }

  // Auto-discover EIO once, right after connect.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await rpc(
          "eio_discover",
          { ...(conn as unknown as Record<string, unknown>) },
          8000,
        );
        if (cancelled) return;
        applyAttached(r);
        readInputs();
      } catch {
        if (!cancelled) setPhase("manual"); // none found / unsupported
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function attachManual() {
    setError("");
    try {
      const r = await rpc("eio_connect", {
        ...(conn as unknown as Record<string, unknown>),
        chain: Number(chain),
        base_addr: parseIntFlexible(base),
      });
      applyAttached(r);
      readInputs();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function writeOutputs(value: bigint) {
    try {
      // Hex string so wide (>53-bit) output words survive JSON transport.
      await rpc("eio_write", { value: "0x" + value.toString(16) });
      setOutputs(value);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (phase !== "attached" || !poll) return;
    timer.current = window.setInterval(readInputs, pollMs);
    return () => {
      if (timer.current !== null) window.clearInterval(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, poll, pollMs]);

  if (phase === "discovering") {
    return (
      <section className="panel">
        <h2>EIO</h2>
        <p className="muted">discovering…</p>
      </section>
    );
  }

  if (phase === "manual") {
    return (
      <section className="panel">
        <h2>EIO</h2>
        <p className="muted">no EIO auto-detected — attach manually:</p>
        <div className="form">
          <label>
            Chain
            <input value={chain} onChange={(e) => setChain(e.target.value)} />
          </label>
          <label>
            Base
            <input value={base} onChange={(e) => setBase(e.target.value)} />
          </label>
        </div>
        <button onClick={attachManual}>Attach EIO</button>
        {error && <p className="err">{error}</p>}
      </section>
    );
  }

  return (
    <section className="panel">
      <h2>EIO</h2>
      <p className="muted">
        in {inW} · out {outW} · chain {chain} · base {base}
      </p>

      <div className="bits">
        <span className="bitlabel">inputs</span>
        {range(inW).map((i) => (
          <span
            key={i}
            className={"bit" + (((inputs >> BigInt(i)) & 1n) === 1n ? " on" : "")}
          >
            {i}
          </span>
        ))}
      </div>

      <div className="bits">
        <span className="bitlabel">outputs</span>
        {range(outW).map((i) => (
          <button
            key={i}
            className={"bit btn" + (((outputs >> BigInt(i)) & 1n) === 1n ? " on" : "")}
            onClick={() => writeOutputs(outputs ^ (1n << BigInt(i)))}
          >
            {i}
          </button>
        ))}
      </div>

      <div className="btnrow">
        <label className="inline">
          <input
            type="checkbox"
            checked={poll}
            onChange={(e) => setPoll(e.target.checked)}
          />{" "}
          poll inputs
        </label>
        <select
          value={pollMs}
          onChange={(e) => setPollMs(Number(e.target.value))}
          disabled={!poll}
          title="input poll interval"
        >
          {POLL_PRESETS.map((ms) => (
            <option key={ms} value={ms}>
              {ms} ms
            </option>
          ))}
        </select>
      </div>
      {error && <p className="err">{error}</p>}
    </section>
  );
}
