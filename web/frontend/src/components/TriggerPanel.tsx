import { useEffect, useMemo, useState } from "react";
import { parseProbesText } from "../api";
import type { Identity, ProbeSpec } from "../api";
import {
  COMPARATOR_BITS,
  composeTrigger,
  describeTerm,
  describeTerms,
  hasDirectionalEdges,
  triggerable,
} from "../signalTrigger";
import type { Combine, SignalCondition, TriggerTerm } from "../signalTrigger";
import { useSession } from "../session";

/** One signal with its click-to-trigger conditions. */
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

/** Per-bit fallback signals so click-to-trigger works with zero setup — the
 *  probe word simply shows up as bit0..bitN until real names are defined. */
function defaultBitProbes(identity: Identity | null): ProbeSpec[] {
  const width = Math.min(identity?.sample_width ?? 0, COMPARATOR_BITS);
  return Array.from({ length: width }, (_, i) => ({ name: `bit${i}`, width: 1, lsb: i }));
}

/** Trigger tab: pick signals and conditions with clicks, combine with AND/OR;
 *  the raw trigger fields below always show (and accept) the result. */
export function TriggerPanel() {
  const { ela, setEla, identity, conn } = useSession();
  const [terms, setTerms] = useState<TriggerTerm[]>([]);
  const [combine, setCombine] = useState<Combine>("and");
  const [applied, setApplied] = useState("");
  const [trigError, setTrigError] = useState("");

  // Named signals from the probe definitions (ELA tab / AXI probe map);
  // a half-edited textarea just hides the list until it parses again.
  const probes = useMemo(() => {
    try {
      return parseProbesText(ela.probesText);
    } catch {
      return [];
    }
  }, [ela.probesText]);
  const signals = probes.length ? probes : defaultBitProbes(identity);

  // Clicking a condition upserts that signal's term (one term per signal);
  // the composed trigger is re-applied on every change below.
  function addTerm(p: ProbeSpec, cond: SignalCondition, value?: string) {
    setTerms((ts) => [
      ...ts.filter((x) => x.probe.name !== p.name),
      { probe: p, cond, value },
    ]);
  }

  function removeTerm(name: string) {
    setTerms((ts) => ts.filter((x) => x.probe.name !== name));
  }

  // Terms referring to signals that were edited away drop out silently.
  useEffect(() => {
    setTerms((ts) =>
      ts.filter((x) =>
        signals.some(
          (p) => p.name === x.probe.name && p.lsb === x.probe.lsb && p.width === x.probe.width,
        ),
      ),
    );
    // signals derives from probes+identity; comparing by content is enough here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ela.probesText, identity]);

  // Re-compose the trigger whenever the terms or the combine rule change.
  useEffect(() => {
    if (terms.length === 0) {
      setApplied("");
      setTrigError("");
      return;
    }
    try {
      setEla(composeTrigger(terms, combine, identity));
      setApplied(`trigger: ${describeTerms(terms, combine)}`);
      setTrigError("");
    } catch (e) {
      setTrigError(e instanceof Error ? e.message : String(e));
    }
    // setEla is stable; identity only changes with the connection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [terms, combine, identity]);

  if (!conn || !identity) {
    return (
      <section className="panel">
        <h2>Trigger</h2>
        <p className="muted">Connect to a target first.</p>
      </section>
    );
  }

  return (
    <section className="panel">
      <h2>Trigger</h2>
      <p className="muted">
        Click a condition to add a signal to the trigger: ↑ rising, ↓ falling,
        1/0 level, ⇅ any change, = value.
        {probes.length === 0 &&
          " Signals are the raw probe bits — name them in the ELA tab's probe definitions."}
      </p>
      <div className="sigtrig">
        {signals.map((p) => (
          <SignalRow
            key={`${p.name}-${p.lsb}`}
            probe={p}
            identity={identity}
            onApply={(cond, v) => addTerm(p, cond, v)}
          />
        ))}
      </div>
      {terms.length > 0 && (
        <div className="trigterms">
          {terms.length > 1 && (
            <select
              value={combine}
              onChange={(e) => setCombine(e.target.value as Combine)}
              title="How the conditions combine"
            >
              <option value="and">ALL of (AND)</option>
              <option value="or">ANY of (OR)</option>
            </select>
          )}
          {terms.map((t) => (
            <span className="trigterm" key={t.probe.name}>
              {describeTerm(t)}
              <button
                className="trigterm-x"
                title="Remove from trigger"
                onClick={() => removeTerm(t.probe.name)}
              >
                ×
              </button>
            </span>
          ))}
          <button className="secondary" onClick={() => setTerms([])}>
            Clear
          </button>
        </div>
      )}
      {applied && !trigError && <p className="ok">{applied} — arm from the Run tab.</p>}
      {trigError && <p className="err">{trigError}</p>}

      <h3>Trigger fields</h3>
      <div className="form">
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
            checked={ela.useSequencer}
            onChange={(e) => setEla({ useSequencer: e.target.checked })}
          />
          Use trigger sequencer
        </label>
      </div>
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
      <p className="muted">Arm from the Run tab.</p>
    </section>
  );
}
