import { useSession } from "../session";

/** ELA trigger/capture configuration. Run controls (Arm / Trigger Immediate /
 *  Auto re-arm / Stop) live in the Run tab and read this shared config. */
export function ElaPanel() {
  const { ela, setEla, identity } = useSession();

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
