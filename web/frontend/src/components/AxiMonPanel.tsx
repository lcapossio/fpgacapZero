import { useState } from "react";
import { axiEventProbes, axiEventTrigger, axiWriteAddrTrigger, probesToText } from "../axiMon";
import { useSession } from "../session";

/** AXI monitor tab: geometry readout, one-click probe map, and an AXI-aware
 *  trigger builder. The monitor is an ELA core, so applying anything here
 *  fills the shared ELA config — arming stays in the Run tab. When the
 *  monitor lives on a different core than the session is bound to, applying
 *  switches to it transparently (via the Connection panel's registered
 *  switch) — the user never deals with chains. */
export function AxiMonPanel() {
  const { axiMon, ela, setEla, conn, chainSwitch } = useSession();
  const [selected, setSelected] = useState<string[]>(["any_err"]);
  const [addr, setAddr] = useState("0x0");
  const [applied, setApplied] = useState("");
  const [error, setError] = useState("");
  const [switching, setSwitching] = useState(false);

  if (!conn) {
    return (
      <section className="panel">
        <h2>AXI Monitor</h2>
        <p className="muted">Connect to a target first.</p>
      </section>
    );
  }
  if (!axiMon) {
    return (
      <section className="panel">
        <h2>AXI Monitor</h2>
        <p className="muted">
          No AXI monitor on this target. See the manual&apos;s AXI monitor
          chapter for how to instantiate one.
        </p>
      </section>
    );
  }

  const bound = axiMon.chain === conn.chain;
  const events = axiEventProbes(axiMon);
  const probeText = probesToText(axiMon.probes);
  const probesApplied = bound && ela.probesText.trim() === probeText;

  /** Make the monitor the session's core (no-op when it already is). */
  async function ensureMonitor(): Promise<boolean> {
    if (bound) return true;
    const sw = chainSwitch.current;
    if (!sw || !axiMon) return false;
    setSwitching(true);
    try {
      await sw(axiMon.chain);
      return true;
    } catch {
      setError("could not switch to the AXI monitor — see the Connection panel");
      return false;
    } finally {
      setSwitching(false);
    }
  }

  function toggleEvent(name: string) {
    setSelected((s) => (s.includes(name) ? s.filter((n) => n !== name) : [...s, name]));
  }

  async function applyProbes() {
    if (!(await ensureMonitor())) return;
    setEla({ probesText: probeText });
    setApplied("probe map applied - captures decode to named AXI fields");
    setError("");
  }

  async function applyEventTrigger() {
    if (!axiMon) return;
    try {
      const t = axiEventTrigger(axiMon, selected); // validate before switching
      if (!(await ensureMonitor())) return;
      setEla({ triggerMode: "value_match", triggerValue: t.value, triggerMask: t.mask });
      setApplied(`trigger set: ${selected.join(" AND ")} (value=mask=${t.mask})`);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function applyAddrTrigger() {
    if (!axiMon) return;
    try {
      const t = axiWriteAddrTrigger(axiMon, addr); // validate before switching
      if (!(await ensureMonitor())) return;
      setEla({ triggerMode: "value_match", triggerValue: t.value, triggerMask: t.mask });
      setApplied(`trigger set: awaddr == ${addr.trim()}`);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <section className="panel">
      <h2>AXI Monitor</h2>
      <p className="muted">
        {axiMon.proto} · addr {axiMon.addr_w} · data {axiMon.data_w} · decode{" "}
        {axiMon.decode ? "on" : "off"} · {axiMon.sample_width}-bit samples
      </p>

      <h3>Probe map</h3>
      <div className="btnrow">
        <button onClick={applyProbes} disabled={probesApplied || switching}>
          {switching
            ? "Working…"
            : probesApplied
              ? "Probe map applied"
              : "Apply AXI probe map"}
        </button>
      </div>
      <p className="muted">
        Fills the ELA tab&apos;s named signals so captures and the Viewer show
        AXI fields (awaddr, wdata, bresp, …) instead of one raw sample word.
      </p>

      <h3>Trigger on</h3>
      {events.length > 0 ? (
        <>
          <div className="bits">
            {events.map((p) => (
              <label className="inline" key={p.name}>
                <input
                  type="checkbox"
                  checked={selected.includes(p.name)}
                  onChange={() => toggleEvent(p.name)}
                />{" "}
                {p.name}
              </label>
            ))}
          </div>
          <div className="btnrow">
            <button onClick={applyEventTrigger} disabled={switching}>
              {switching ? "Working…" : "Apply event trigger"}
            </button>
          </div>
          <p className="muted">
            Fires when all selected events assert in the same cycle — use
            any_err alone for &quot;any error response&quot;.
          </p>
        </>
      ) : (
        <>
          <div className="form">
            <label>
              Write address (awaddr)
              <input value={addr} onChange={(e) => setAddr(e.target.value)} />
            </label>
          </div>
          <div className="btnrow">
            <button onClick={applyAddrTrigger} disabled={switching}>
              {switching ? "Working…" : "Apply address trigger"}
            </button>
          </div>
          <p className="muted">
            Fires on a write to this address. Event triggers (handshakes,
            error responses) need a DECODE_EN=1 monitor build.
          </p>
        </>
      )}

      {applied && !error && <p className="ok">{applied} — arm from the Run tab.</p>}
      {error && <p className="err">{error}</p>}
    </section>
  );
}
