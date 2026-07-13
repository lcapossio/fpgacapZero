import { useState } from "react";
import { axiEventProbes, axiEventTrigger, axiWriteAddrTrigger, probesToText } from "../axiMon";
import { useSession } from "../session";

/** AXI monitor tab: geometry readout, one-click probe map, and an AXI-aware
 *  trigger builder. The monitor *is* the connected ELA, so applying anything
 *  here just fills the shared ELA config — arming stays in the Run tab. */
export function AxiMonPanel() {
  const { axiMon, axiMonChains, ela, setEla, conn, chainSwitch } = useSession();
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
        {axiMonChains.length > 0 ? (
          <>
            <p className="warn">
              An AXI monitor was found on another debug core of this target.
            </p>
            <div className="btnrow">
              <button
                disabled={switching}
                onClick={async () => {
                  setSwitching(true);
                  try {
                    await chainSwitch.current?.(axiMonChains[0]);
                  } finally {
                    setSwitching(false);
                  }
                }}
              >
                {switching ? "Switching…" : "Switch to AXI monitor"}
              </button>
            </div>
          </>
        ) : (
          <p className="muted">
            No AXI monitor on this target — the connected ELA reports no
            AXI_MON identity. See the manual&apos;s AXI monitor chapter for how
            to instantiate one.
          </p>
        )}
      </section>
    );
  }

  const events = axiEventProbes(axiMon);
  const probeText = probesToText(axiMon.probes);
  const probesApplied = ela.probesText.trim() === probeText;

  function toggleEvent(name: string) {
    setSelected((s) => (s.includes(name) ? s.filter((n) => n !== name) : [...s, name]));
  }

  function applyProbes() {
    setEla({ probesText: probeText });
    setApplied("probe map applied - captures decode to named AXI fields");
    setError("");
  }

  function applyEventTrigger() {
    if (!axiMon) return;
    try {
      const t = axiEventTrigger(axiMon, selected);
      setEla({ triggerMode: "value_match", triggerValue: t.value, triggerMask: t.mask });
      setApplied(`trigger set: ${selected.join(" AND ")} (value=mask=${t.mask})`);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function applyAddrTrigger() {
    if (!axiMon) return;
    try {
      const t = axiWriteAddrTrigger(axiMon, addr);
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
        <button onClick={applyProbes} disabled={probesApplied}>
          {probesApplied ? "Probe map applied" : "Apply AXI probe map"}
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
            <button onClick={applyEventTrigger}>Apply event trigger</button>
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
            <button onClick={applyAddrTrigger}>Apply address trigger</button>
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
