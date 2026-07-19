import { useEffect, useMemo, useState } from "react";
import { parseProbesText } from "../api";
import type { Identity, ProbeSpec } from "../api";
import {
  COMPARATOR_BITS,
  composeTrigger,
  defaultTerm,
  describeTerms,
  groupTerms,
  hasDirectionalEdges,
  termName,
  termWidth,
  triggerable,
} from "../signalTrigger";
import type { Combine, TriggerOp, TriggerRadix, TriggerTerm } from "../signalTrigger";
import { useSession } from "../session";

/** Per-bit fallback signals so triggering works with zero setup — the probe
 *  word simply shows up as bit0..bitN until real names are defined. */
function defaultBitProbes(identity: Identity | null): ProbeSpec[] {
  const width = Math.min(identity?.sample_width ?? 0, COMPARATOR_BITS);
  return Array.from({ length: width }, (_, i) => ({ name: `bit${i}`, width: 1, lsb: i }));
}

function valueHint(t: TriggerTerm, edges: boolean): string {
  const width = termWidth(t);
  const singleBit = t.probes.length === 1 && t.probes[0].width === 1;
  if (t.radix === "B")
    return singleBit
      ? `0, 1, X${edges ? ", R (rise), F (fall), B (both)" : ""}`
      : `${width} binary digits; X = don't care`;
  if (t.radix === "H") return "hex digits; X = don't care nibble";
  return "unsigned decimal";
}

/** Trigger tab, laid out like Vivado ILA's Trigger Setup: add probes as rows
 *  (Name | Operator | Radix | Value), pick a global AND/OR condition. Values
 *  take X don't-cares (binary/hex) and R/F/B edges on 1-bit probes. The raw
 *  trigger fields stay available under Advanced. */
export function TriggerPanel() {
  const { ela, setEla, identity, conn } = useSession();
  const [terms, setTerms] = useState<TriggerTerm[]>([]);
  const [combine, setCombine] = useState<Combine>("and");
  const [picking, setPicking] = useState("");
  const [applied, setApplied] = useState("");
  const [trigError, setTrigError] = useState("");
  // Row indices checked for grouping. Cleared on any structural edit so it can
  // never point at a shifted/removed row.
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // Named signals from the probe definitions (ELA tab / AXI probe map);
  // a half-edited textarea just hides the list until it parses again.
  const probes = useMemo(() => {
    try {
      return parseProbesText(ela.probesText);
    } catch {
      return [];
    }
  }, [ela.probesText]);
  const signals = (probes.length ? probes : defaultBitProbes(identity)).filter(triggerable);
  const edges = hasDirectionalEdges(identity);
  const available = signals.filter(
    (p) => !terms.some((t) => t.probes.some((mp) => mp.name === p.name)),
  );

  function addRow(name: string) {
    const p = signals.find((s) => s.name === name);
    if (!p) return;
    setTerms((ts) => [...ts, defaultTerm(p)]);
  }

  function patchRow(i: number, patch: Partial<TriggerTerm>) {
    setTerms((ts) => ts.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  }

  function removeRow(i: number) {
    setTerms((ts) => ts.filter((_, j) => j !== i));
    setSelected(new Set());
  }

  function toggleSel(i: number) {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  // Concatenate the checked rows into one field, in table order (top = MSB).
  // The merged row lands where the first selected row was.
  function groupSelected() {
    setTerms((ts) => {
      const idxs = [...selected].filter((i) => i < ts.length).sort((a, b) => a - b);
      if (idxs.length < 2) return ts;
      const merged = groupTerms(idxs.map((i) => ts[i]));
      const rest = new Set(idxs.slice(1));
      return ts.flatMap((t, i) => (i === idxs[0] ? [merged] : rest.has(i) ? [] : [t]));
    });
    setSelected(new Set());
  }

  // Split a group back into one default row per member probe.
  function ungroup(i: number) {
    setTerms((ts) =>
      ts.flatMap((t, j) =>
        j === i && t.probes.length > 1 ? t.probes.map((p) => defaultTerm(p)) : [t],
      ),
    );
    setSelected(new Set());
  }

  // Reorder a row (sets which probe is the MSB within a group).
  function moveRow(i: number, dir: -1 | 1) {
    setTerms((ts) => {
      const j = i + dir;
      if (j < 0 || j >= ts.length) return ts;
      const copy = [...ts];
      [copy[i], copy[j]] = [copy[j], copy[i]];
      return copy;
    });
    setSelected(new Set());
  }

  // Rows whose probes were edited away drop out silently; a group survives only
  // while every one of its members still exists.
  useEffect(() => {
    setTerms((ts) =>
      ts.filter((x) =>
        x.probes.every((mp) =>
          signals.some((p) => p.name === mp.name && p.lsb === mp.lsb && p.width === mp.width),
        ),
      ),
    );
    setSelected(new Set());
    // signals derives from probes+identity; comparing by content is enough here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ela.probesText, identity]);

  // Re-compose the trigger whenever the table changes.
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
      <div className="trigsetup-head">
        <h2>Trigger Setup</h2>
        <label className="trigcond">
          Trigger condition{" "}
          <select value={combine} onChange={(e) => setCombine(e.target.value as Combine)}>
            <option value="and">Global AND</option>
            <option value="or">Global OR</option>
          </select>
        </label>
      </div>

      <div className="btnrow">
        <select
          value={picking}
          onChange={(e) => {
            addRow(e.target.value);
            setPicking("");
          }}
          disabled={available.length === 0}
          title="Add a probe to the trigger"
        >
          <option value="" disabled hidden>
            + Add probe…
          </option>
          {available.map((p) => (
            <option key={`${p.name}-${p.lsb}`} value={p.name}>
              {p.name}
              {p.width > 1 ? ` [${p.width - 1}:0]` : ""}
            </option>
          ))}
        </select>
        <button
          className="secondary"
          onClick={groupSelected}
          disabled={selected.size < 2}
          title="Concatenate the checked rows into one field (top row = MSB)"
        >
          Group selected
        </button>
        {terms.length > 0 && (
          <button
            className="secondary"
            onClick={() => {
              setTerms([]);
              setSelected(new Set());
            }}
          >
            Clear all
          </button>
        )}
      </div>
      {probes.length === 0 && (
        <p className="muted">
          Probes are the raw sample bits — name them in the ELA tab&apos;s probe
          definitions to trigger on named fields.
        </p>
      )}

      {terms.length > 0 && (
        <table className="trigtable">
          <thead>
            <tr>
              <th />
              <th>Name</th>
              <th>Operator</th>
              <th>Radix</th>
              <th>Value</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {terms.map((t, i) => {
              const width = termWidth(t);
              const grouped = t.probes.length > 1;
              const bitsTitle = t.probes
                .map((p) => `${p.name} [${p.lsb + p.width - 1}:${p.lsb}]`)
                .join(grouped ? " · " : "");
              return (
                <tr key={`${termName(t)}-${t.probes[0].lsb}`}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(i)}
                      onChange={() => toggleSel(i)}
                      title="Select rows to group into one field"
                    />
                  </td>
                  <td className="signame" title={bitsTitle}>
                    {termName(t)}
                    {width > 1 && <span className="muted"> [{width - 1}:0]</span>}
                  </td>
                  <td>
                    <select
                      value={t.op}
                      onChange={(e) => patchRow(i, { op: e.target.value as TriggerOp })}
                    >
                      <option value="==">==</option>
                      <option value="!=">!=</option>
                    </select>
                  </td>
                  <td>
                    <select
                      value={t.radix}
                      onChange={(e) => patchRow(i, { radix: e.target.value as TriggerRadix })}
                      title="B binary · H hex · U unsigned"
                    >
                      <option value="B">[B]</option>
                      <option value="H">[H]</option>
                      <option value="U">[U]</option>
                    </select>
                  </td>
                  <td>
                    <input
                      className="trigvalue"
                      value={t.value}
                      onChange={(e) => patchRow(i, { value: e.target.value })}
                      title={valueHint(t, edges)}
                      spellCheck={false}
                    />
                  </td>
                  <td className="trigrow-actions">
                    <button
                      className="trigterm-move"
                      title="Move up (toward MSB)"
                      onClick={() => moveRow(i, -1)}
                      disabled={i === 0}
                    >
                      ▲
                    </button>
                    <button
                      className="trigterm-move"
                      title="Move down (toward LSB)"
                      onClick={() => moveRow(i, 1)}
                      disabled={i === terms.length - 1}
                    >
                      ▼
                    </button>
                    {grouped && (
                      <button
                        className="secondary trigterm-ungroup"
                        title="Split back into separate probe rows"
                        onClick={() => ungroup(i)}
                      >
                        Ungroup
                      </button>
                    )}
                    <button
                      className="trigterm-x"
                      title="Remove row"
                      onClick={() => removeRow(i)}
                    >
                      ×
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {applied && !trigError && <p className="ok">{applied} — arm from the Run bar.</p>}
      {trigError && <p className="err">{trigError}</p>}
      {terms.length === 0 && !trigError && (
        <p className="muted">
          No rows — the armed trigger uses the fields under Advanced as-is.
        </p>
      )}

      <details className="trigadv">
        <summary>Advanced (raw trigger fields)</summary>
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
      </details>
    </section>
  );
}
