import { useMemo, useState } from "react";
import {
  cell,
  filterTransactions,
  headline,
  isFault,
  pairingWarning,
} from "../axiTxn";
import type { KindFilter } from "../axiTxn";
import { useSession } from "../session";

/** AXI Txn tab: the last capture read as AXI4-Lite transactions rather than
 *  as a waveform. The decode comes from the server with the capture (the RPC
 *  layer attaches it whenever the probe map is an AXI monitor's), so this
 *  panel does no work on the bus — it only filters and renders.
 *
 *  This is the view that answers "why is this write corrupt?" directly:
 *  address, data, strobes, response and latency per transaction, with the
 *  faulty ones one checkbox away. */
export function AxiTxnPanel() {
  const { conn, captures } = useSession();
  const [kind, setKind] = useState<KindFilter>("all");
  const [onlyAnomalies, setOnlyAnomalies] = useState(false);

  const decode = conn ? captures[conn.chain]?.axi : undefined;
  const rows = useMemo(
    () => (decode ? filterTransactions(decode.transactions, { kind, onlyAnomalies }) : []),
    [decode, kind, onlyAnomalies],
  );

  if (!conn) {
    return (
      <section className="panel">
        <p className="muted">Connect to a target first.</p>
      </section>
    );
  }
  if (!decode) {
    return (
      <section className="panel">
        <p className="muted">
          No AXI transactions yet. Capture with an AXI monitor probe map — the
          AXI Mon tab applies it in one click — and the decode appears here.
        </p>
      </section>
    );
  }

  const warning = pairingWarning(decode);

  return (
    <section className="panel">
      <p className="muted">{headline(decode)}</p>
      {warning && <p className="axitxn-warn">{warning}</p>}

      <div className="btnrow">
        <label className="inline">
          Show
          <select value={kind} onChange={(e) => setKind(e.target.value as KindFilter)}>
            <option value="all">reads and writes</option>
            <option value="read">reads only</option>
            <option value="write">writes only</option>
          </select>
        </label>
        <label className="inline">
          <input
            type="checkbox"
            checked={onlyAnomalies}
            onChange={(e) => setOnlyAnomalies(e.target.checked)}
          />{" "}
          Faults only
        </label>
        <span className="muted">
          {rows.length} of {decode.transaction_count}
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="muted">No transactions match these filters.</p>
      ) : (
        <div className="axitxn-scroll">
          <table className="trigtable axitxn">
            <thead>
              <tr>
                <th>#</th>
                <th>Kind</th>
                <th>Address</th>
                <th>Data</th>
                <th>STRB</th>
                <th>Resp</th>
                <th>Cycle</th>
                <th>Latency</th>
                <th>Flags</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((txn) => (
                <tr key={txn.index} className={isFault(txn) ? "axitxn-fault" : undefined}>
                  <td>{txn.index}</td>
                  <td>{txn.kind}</td>
                  <td className="mono">{cell(txn.addr)}</td>
                  <td className="mono">{cell(txn.data)}</td>
                  <td className="mono">{cell(txn.strb)}</td>
                  <td>{cell(txn.resp)}</td>
                  <td>{cell(txn.cycles?.addr ?? txn.cycles?.data)}</td>
                  <td>{cell(txn.latency)}</td>
                  <td className="muted">{(txn.flags ?? []).join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
