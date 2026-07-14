import { useMemo, useState } from "react";
import { parseProbesText } from "../api";
import type { Identity, ProbeSpec } from "../api";
import {
  describeCondition,
  hasDirectionalEdges,
  signalTrigger,
  triggerable,
} from "../signalTrigger";
import type { SignalCondition } from "../signalTrigger";
import { useSession } from "../session";

/** One named signal with its click-to-trigger conditions. */
function SignalRow({
  probe,
  identity,
  onApply,
}: {
  probe: ProbeSpec;
  identity: Identity | null;
  onApply: (cond: SignalCondition, equalsText?: string) => void;
}) {
  const [value, setValue] = useState("0x0");
  const usable = triggerable(probe);
  const edges = hasDirectionalEdges(identity);
  const edgeTitle = edges
    ? undefined
    : `directional edges need a TRIG_STAGES ≥ 2 bitstream (this build: ${identity?.trig_stages ?? "?"})`;
  return (
    <div className="sigrow">
      <span
        className="signame"
        title={`bits [${probe.lsb + probe.width - 1}:${probe.lsb}]`}
      >
        {probe.name}
        {probe.width > 1 && <span className="muted"> [{probe.width}]</span>}
      </span>
      {!usable ? (
        <span className="muted" title="the trigger comparator reaches bits 31:0 only">
          above bit 31
        </span>
      ) : probe.width === 1 ? (
        <>
          <button className="secondary" title={edgeTitle ?? "Rising edge"}
            disabled={!edges} onClick={() => onApply("rising")}>
            ↑
          </button>
          <button className="secondary" title={edgeTitle ?? "Falling edge"}
            disabled={!edges} onClick={() => onApply("falling")}>
            ↓
          </button>
          <button className="secondary" title="High (== 1)" onClick={() => onApply("high")}>
            1
          </button>
          <button className="secondary" title="Low (== 0)" onClick={() => onApply("low")}>
            0
          </button>
          <button className="secondary" title="Any toggle" onClick={() => onApply("change")}>
            ⇅
          </button>
        </>
      ) : (
        <>
          <input
            className="sigval"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            title="decimal or 0x-hex"
          />
          <button className="secondary" title="Equals this value"
            onClick={() => onApply("equals", value)}>
            =
          </button>
          <button className="secondary" title="Any change of this field"
            onClick={() => onApply("change")}>
            ⇅
          </button>
        </>
      )}
    </div>
  );
}

/** ELA trigger/capture configuration. Run controls (Arm / Trigger Immediate /
 *  Auto re-arm / Stop) live in the Run tab and read this shared config. */
export function ElaPanel() {
  const { ela, setEla, identity } = useSession();
  const [applied, setApplied] = useState("");
  const [trigError, setTrigError] = useState("");

  // Signals parsed from the probe definitions; a half-edited textarea just
  // hides the click-to-trigger list until it parses again.
  const probes = useMemo(() => {
    try {
      return parseProbesText(ela.probesText);
    } catch {
      return [];
    }
  }, [ela.probesText]);

  function applySignalTrigger(p: ProbeSpec, cond: SignalCondition, equalsText?: string) {
    try {
      setEla(signalTrigger(p, cond, equalsText));
      setApplied(`trigger: ${describeCondition(p, cond, equalsText)}`);
      setTrigError("");
    } catch (e) {
      setTrigError(e instanceof Error ? e.message : String(e));
    }
  }

  async function loadProbeFile(file: File | undefined) {
    if (!file) return;
    setEla({ probesText: await file.text() });
  }

  return (
    <section className="panel">
      <h2>ELA config</h2>
      <div className="form">
        <label>
          Channel
          <input
            value={ela.channel}
            onChange={(e) => setEla({ channel: e.target.value })}
          />
        </label>
        <label>
          Pre
          <input
            value={ela.pretrigger}
            onChange={(e) => setEla({ pretrigger: e.target.value })}
          />
        </label>
        <label>
          Post
          <input
            value={ela.posttrigger}
            onChange={(e) => setEla({ posttrigger: e.target.value })}
          />
        </label>
        <label>
          Mode
          <select
            value={ela.triggerMode}
            onChange={(e) => setEla({ triggerMode: e.target.value })}
          >
            <option value="value_match">value_match</option>
            <option value="edge_detect">edge_detect</option>
            <option value="both">both</option>
          </select>
        </label>
        <label>
          Trigger value
          <input
            value={ela.triggerValue}
            onChange={(e) => setEla({ triggerValue: e.target.value })}
          />
        </label>
        <label>
          Trigger mask
          <input
            value={ela.triggerMask}
            onChange={(e) => setEla({ triggerMask: e.target.value })}
          />
        </label>
      </div>

      <h3>Probe definitions</h3>
      <div className="btnrow">
        <label className="filepick">
          Load .prob
          <input
            type="file"
            accept=".prob,.json,text/plain"
            onChange={(e) => loadProbeFile(e.target.files?.[0])}
          />
        </label>
        <button className="secondary" onClick={() => setEla({ probesText: "" })}>
          Clear probes
        </button>
      </div>
      <label>
        Named signals
        <textarea
          value={ela.probesText}
          onChange={(e) => setEla({ probesText: e.target.value })}
          placeholder="valid:1:0&#10;state:7:1"
          spellCheck={false}
        />
      </label>

      {probes.length > 0 && (
        <>
          <h3>Signal triggers</h3>
          <p className="muted">
            Click a condition to trigger on that signal: ↑ rising, ↓ falling,
            1/0 level, ⇅ any change, = value.
          </p>
          <div className="sigtrig">
            {probes.map((p) => (
              <SignalRow
                key={`${p.name}-${p.lsb}`}
                probe={p}
                identity={identity}
                onApply={(cond, v) => applySignalTrigger(p, cond, v)}
              />
            ))}
          </div>
          {applied && !trigError && <p className="ok">{applied} — arm from the Run tab.</p>}
          {trigError && <p className="err">{trigError}</p>}
        </>
      )}

      <h3>Advanced triggering</h3>
      <div className="form">
        <label>
          External trigger
          <select
            value={ela.extTriggerMode}
            onChange={(e) => setEla({ extTriggerMode: e.target.value })}
          >
            <option value="0">disabled</option>
            <option value="1">OR</option>
            <option value="2">AND</option>
          </select>
        </label>
        <label className="inline">
          <input
            type="checkbox"
            checked={ela.segmented}
            onChange={(e) => setEla({ segmented: e.target.checked })}
          />
          Read all segments
        </label>
        <label className="inline">
          <input
            type="checkbox"
            checked={ela.useSequencer}
            onChange={(e) => setEla({ useSequencer: e.target.checked })}
          />
          Use trigger sequencer
        </label>
      </div>
      {identity?.num_segments ? (
        <p className="muted">Hardware segments: {identity.num_segments}</p>
      ) : null}
      {ela.useSequencer ? (
        <label>
          Trigger sequence JSON
          <textarea
            value={ela.sequenceJson}
            onChange={(e) => setEla({ sequenceJson: e.target.value })}
            placeholder='[{"cmp_mode_a":0,"value_a":0,"mask_a":255,"is_final":true}]'
            spellCheck={false}
          />
        </label>
      ) : null}
      <p className="muted">Run captures from the Run tab.</p>
    </section>
  );
}
