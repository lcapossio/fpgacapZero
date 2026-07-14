import type { Core, Identity } from "../api";
import { useSession } from "../session";

// Friendly names for core identities, so the user sees "Logic Analyzer",
// not the raw ASCII-packed magic (0x4C41 = "LA").
const CORE_NAMES: Record<number, string> = {
  0x4c41: "Embedded Logic Analyzer (ELA)",
  0x494f: "Embedded I/O (EIO)",
};

function coreName(id: number): string {
  return CORE_NAMES[id] ?? `core 0x${id.toString(16).toUpperCase()}`;
}

/** Human-readable list of the ELA's optional capabilities. */
function elaFeatures(id: Identity): string[] {
  const f: string[] = [];
  if (id.trig_stages && id.trig_stages > 1) f.push(`${id.trig_stages} trigger stages`);
  if (id.has_ext_trigger) f.push("external trigger");
  if (id.has_storage_qualification) f.push("storage qualification");
  if (id.has_decimation) f.push("decimation");
  if (id.has_timestamp)
    f.push(`timestamps${id.timestamp_width ? ` (${id.timestamp_width}-bit)` : ""}`);
  if (id.has_dual_compare) f.push("dual compare");
  return f;
}

/** Synthesize the ELA core entry from the probe identity, for the brief window
 *  before list_cores returns (or if it fails). */
function elaCoreFromIdentity(id: Identity, chain: number): Core {
  return {
    type: "ela",
    name: coreName(id.core_id),
    core_id: id.core_id,
    chain,
    base_addr: 0,
    version_major: id.version_major,
    version_minor: id.version_minor,
    info: id as unknown as Record<string, unknown>,
  };
}

/** One core rendered as a labeled card with type-specific detail. The core the
 *  session is bound to is marked "in use"; others get a one-click switch. */
function CoreCard({
  core,
  active,
  onUse,
  busy,
}: {
  core: Core;
  active?: boolean;
  onUse?: () => void;
  busy?: boolean;
}) {
  // Display component: info is a type-specific bag, read loosely.
  const info = core.info as any;
  const feats = core.type === "ela" ? elaFeatures(core.info as unknown as Identity) : [];
  return (
    <div className="core">
      <div className="core-title">
        {core.type === "ela" || core.type === "eio" || core.type === "axi_mon"
          ? core.name
          : coreName(core.core_id)}{" "}
        <span className="muted">
          v{core.version_major}.{core.version_minor} · 0x
          {core.core_id.toString(16).toUpperCase()}
        </span>
        {active && <span className="ok"> · in use</span>}
      </div>
      <dl className="idinfo">
        {core.type === "ela" && (
          <>
            <dt>Sample width</dt>
            <dd>{Number(info.sample_width)} bits</dd>
            <dt>Depth</dt>
            <dd>{Number(info.depth).toLocaleString()} samples</dd>
            <dt>Channels</dt>
            <dd>{Number(info.num_channels)}</dd>
            {Number(info.num_segments) > 1 ? (
              <>
                <dt>Segments</dt>
                <dd>{Number(info.num_segments)}</dd>
              </>
            ) : null}
            {feats.length > 0 && (
              <>
                <dt>Features</dt>
                <dd>{feats.join(", ")}</dd>
              </>
            )}
          </>
        )}
        {core.type === "eio" && (
          <>
            <dt>Inputs</dt>
            <dd>{Number(info.in_w)}</dd>
            <dt>Outputs</dt>
            <dd>{Number(info.out_w)}</dd>
          </>
        )}
        {core.type === "axi_mon" && (
          <>
            <dt>Protocol</dt>
            <dd>{String(info.proto)}</dd>
            <dt>Bus</dt>
            <dd>
              addr {Number(info.addr_w)} · data {Number(info.data_w)}
            </dd>
            <dt>Decode layer</dt>
            <dd>{info.decode ? "on (event triggers)" : "off"}</dd>
            <dt>Sample width</dt>
            <dd>{Number(info.sample_width)} bits</dd>
          </>
        )}
        {core.base_addr ? (
          <>
            <dt>Address</dt>
            <dd>0x{core.base_addr.toString(16)}</dd>
          </>
        ) : null}
      </dl>
      {onUse && (
        <div className="btnrow">
          <button onClick={onUse} disabled={busy}>
            Use this core
          </button>
        </div>
      )}
    </div>
  );
}

/** Cores tab: every debug core discovered on the connected target. The core
 *  the session is bound to is marked "in use"; other capture cores re-bind
 *  the session with one click (chains stay invisible). */
export function CoresPanel() {
  const { cores, conn, identity, chainSwitch, switching } = useSession();
  if (!conn || !identity) {
    return (
      <section className="panel">
        <h2>Cores</h2>
        <p className="muted">Connect to a target first.</p>
      </section>
    );
  }
  const activeChain = conn.chain;
  const shown = cores.length ? cores : [elaCoreFromIdentity(identity, activeChain)];
  return (
    <section className="panel">
      <h2>Cores ({shown.length})</h2>
      {shown.map((core, i) => {
        const switchable =
          (core.type === "ela" || core.type === "axi_mon") && core.chain !== activeChain;
        return (
          <CoreCard
            key={`${core.type}-${core.chain}-${core.base_addr}-${i}`}
            core={core}
            active={core.chain === activeChain && core.type !== "eio"}
            busy={switching}
            onUse={
              switchable
                ? () => {
                    // errors surface in the Connection panel via the switch
                    chainSwitch.current?.(core.chain).catch(() => {});
                  }
                : undefined
            }
          />
        );
      })}
    </section>
  );
}
