import { useEffect, useRef, useState } from "react";
import { parseIntFlexible, rpc } from "../api";
import type { ConnectionParams } from "../api";

function range(n: number): number[] {
  return Array.from({ length: n }, (_, i) => i);
}

export function EioPanel({ conn }: { conn: ConnectionParams }) {
  // Gowin shares the ELA chain at 0x8000; standalone (Xilinx) is USER3 / base 0.
  const gowin = conn.ir_table === "gowin";
  const [chain, setChain] = useState(gowin ? "1" : "3");
  const [baseAddr, setBaseAddr] = useState(gowin ? "0x8000" : "0x0");
  const [attached, setAttached] = useState(false);
  const [inW, setInW] = useState(0);
  const [outW, setOutW] = useState(0);
  const [inputs, setInputs] = useState(0);
  const [outputs, setOutputs] = useState(0);
  const [poll, setPoll] = useState(true);
  const [error, setError] = useState("");
  const timer = useRef<number | null>(null);

  async function readInputs() {
    try {
      const r = await rpc("eio_read");
      setInputs(r.value as number);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function attach() {
    setError("");
    try {
      const r = await rpc("eio_connect", {
        ...(conn as unknown as Record<string, unknown>),
        chain: Number(chain),
        base_addr: parseIntFlexible(baseAddr),
      });
      setInW(r.in_w as number);
      setOutW(r.out_w as number);
      setAttached(true);
      await readInputs();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function writeOutputs(value: number) {
    try {
      await rpc("eio_write", { value });
      setOutputs(value);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (!attached || !poll) return;
    timer.current = window.setInterval(readInputs, 300);
    return () => {
      if (timer.current !== null) window.clearInterval(timer.current);
    };
  }, [attached, poll]);

  if (!attached) {
    return (
      <section className="panel">
        <h2>EIO</h2>
        <div className="form">
          <label>
            Chain
            <input value={chain} onChange={(e) => setChain(e.target.value)} />
          </label>
          <label>
            Base
            <input value={baseAddr} onChange={(e) => setBaseAddr(e.target.value)} />
          </label>
        </div>
        <button onClick={attach}>Attach EIO</button>
        {error && <p className="err">{error}</p>}
      </section>
    );
  }

  return (
    <section className="panel">
      <h2>EIO</h2>
      <p className="muted">
        in {inW} · out {outW} · chain {chain} · base {baseAddr}
      </p>

      <div className="bits">
        <span className="bitlabel">inputs</span>
        {range(inW).map((i) => (
          <span key={i} className={"bit" + (((inputs >> i) & 1) === 1 ? " on" : "")}>
            {i}
          </span>
        ))}
      </div>

      <div className="bits">
        <span className="bitlabel">outputs</span>
        {range(outW).map((i) => (
          <button
            key={i}
            className={"bit btn" + (((outputs >> i) & 1) === 1 ? " on" : "")}
            onClick={() => writeOutputs(outputs ^ (1 << i))}
          >
            {i}
          </button>
        ))}
      </div>

      <label className="inline">
        <input
          type="checkbox"
          checked={poll}
          onChange={(e) => setPoll(e.target.checked)}
        />{" "}
        poll inputs
      </label>
      {error && <p className="err">{error}</p>}
    </section>
  );
}
