import { useSession } from "../session";

/** ELA capture configuration: window geometry and probe naming. Trigger
 *  conditions live in the Trigger tab; run controls in the Run tab. */
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
        <label className="inline">
          <input
            type="checkbox"
            checked={ela.segmented}
            onChange={(e) => setEla({ segmented: e.target.checked })}
          />
          Read all segments
        </label>
      </div>
      {identity?.num_segments ? (
        <p className="muted">Hardware segments: {identity.num_segments}</p>
      ) : null}

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
      <p className="muted">
        Set the trigger in the Trigger tab; run captures from the Run tab.
      </p>
    </section>
  );
}
