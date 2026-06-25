import { useState } from "react";
import { parseIntFlexible, rpc } from "../api";
import type { Identity } from "../api";

/** ELA capture controls. The waveform itself renders in the Viewer (Surfer) tab;
 *  a successful capture is pushed up via onCaptured as VCD text. */
export function ElaPanel({
  identity,
  onCaptured,
}: {
  identity: Identity;
  onCaptured: (vcd: string) => void;
}) {
  const [channel, setChannel] = useState("0");
  const [pretrigger, setPre] = useState("8");
  const [posttrigger, setPost] = useState("16");
  const [triggerMode, setTriggerMode] = useState("value_match");
  const [triggerValue, setTriggerValue] = useState("0x00");
  const [triggerMask, setTriggerMask] = useState("0xFF");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [overflow, setOverflow] = useState(false);

  async function capture() {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const r = await rpc("capture", {
        channel: Number(channel),
        pretrigger: Number(pretrigger),
        posttrigger: Number(posttrigger),
        trigger_mode: triggerMode,
        trigger_value: parseIntFlexible(triggerValue),
        trigger_mask: parseIntFlexible(triggerMask),
        sample_width: identity.sample_width,
        depth: identity.depth,
        timeout: 10.0,
        include_vcd: true, // the Viewer tab loads this into Surfer
      });
      setOverflow(Boolean(r.overflow));
      setStatus(`captured ${r.sample_count ?? "?"} samples — see the Viewer tab`);
      if (typeof r.vcd === "string") onCaptured(r.vcd);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>ELA capture</h2>
      <div className="form">
        <label>
          Channel
          <input value={channel} onChange={(e) => setChannel(e.target.value)} />
        </label>
        <label>
          Pre
          <input value={pretrigger} onChange={(e) => setPre(e.target.value)} />
        </label>
        <label>
          Post
          <input value={posttrigger} onChange={(e) => setPost(e.target.value)} />
        </label>
        <label>
          Mode
          <select
            value={triggerMode}
            onChange={(e) => setTriggerMode(e.target.value)}
          >
            <option value="value_match">value_match</option>
            <option value="edge_detect">edge_detect</option>
            <option value="both">both</option>
          </select>
        </label>
        <label>
          Trigger value
          <input
            value={triggerValue}
            onChange={(e) => setTriggerValue(e.target.value)}
          />
        </label>
        <label>
          Trigger mask
          <input
            value={triggerMask}
            onChange={(e) => setTriggerMask(e.target.value)}
          />
        </label>
      </div>
      <button onClick={capture} disabled={busy}>
        {busy ? "Capturing…" : "Capture"}
      </button>
      {overflow && <p className="warn">overflow</p>}
      {status && <p className="muted">{status}</p>}
      {error && <p className="err">{error}</p>}
    </section>
  );
}
