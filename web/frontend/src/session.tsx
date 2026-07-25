import { createContext, useContext, useMemo, useRef, useState } from "react";
import type { MutableRefObject, ReactNode } from "react";
import type { ConnectionParams, Core, Identity } from "./api";
import type { AxiMonInfo } from "./axiMon";

/** The latest ELA capture, shared from the Run panel to the Viewer panels. */
export interface CaptureState {
  vcd: string;
  csv?: string;
  json?: unknown;
  sampleCount?: number | string;
  seq: number; // bumps each capture so the viewer reloads even if panels are detached
}

/** EJTAG-AXI bridge auto-detected on the target (ejtag_axi_probe), or null.
 *  `chain` is the USER chain it lives on so the AXI tab can attach without the
 *  user guessing it. */
export interface EjtagAxiInfo {
  chain: number;
  coreId: number;
  versionMajor: number;
  versionMinor: number;
  addrW: number;
  dataW: number;
  fifoDepth: number;
  legacy: boolean;
}

/** ELA trigger/capture config — edited in the ELA tab, consumed by the Run tab. */
export interface ElaConfig {
  channel: string;
  pretrigger: string;
  posttrigger: string;
  triggerMode: string;
  triggerValue: string;
  triggerMask: string;
  extTriggerMode: string;
  useSequencer: boolean;
  sequenceJson: string;
  segmented: boolean;
  probesText: string;
}

export const DEFAULT_ELA: ElaConfig = {
  channel: "0",
  pretrigger: "8",
  posttrigger: "16",
  triggerMode: "value_match",
  triggerValue: "0x00",
  // mask 0 = match anything: a freshly connected core triggers on the next
  // sample (Arm behaves like "capture now") until a real trigger is set in the
  // Trigger tab. mask 0xFF would instead wait for the low byte to read 0.
  triggerMask: "0x00",
  extTriggerMode: "0",
  useSequencer: false,
  sequenceJson: "",
  segmented: false,
  probesText: "",
};

/** Default ELA config for a core of the given buffer geometry: keep 8
 *  pre-trigger samples and let the rest of one capture window be post-trigger,
 *  so a capture fills the usable buffer instead of the tiny fixed 25-sample
 *  default. A single capture must fit in one segment, so the usable window is
 *  `depth / num_segments` (equals depth on a non-segmented core). Falls back to
 *  DEFAULT_ELA when the geometry is unknown. */
export function defaultElaForDepth(depth?: number, segments?: number): ElaConfig {
  const d = Number(depth) || 0;
  const seg = Math.max(1, Number(segments) || 1);
  const usable = Math.floor(d / seg);
  const pre = 8;
  const post = usable > pre + 1 ? usable - pre - 1 : Number(DEFAULT_ELA.posttrigger);
  return { ...DEFAULT_ELA, pretrigger: String(pre), posttrigger: String(post) };
}

interface Session {
  identity: Identity | null;
  conn: ConnectionParams | null;
  /** Cores discovered on the connected target (list_cores). */
  cores: Core[];
  /** Last capture per core, keyed by the core's BSCAN chain — every capture
   *  core gets its own Viewer tab showing its own waveform. */
  captures: Record<number, CaptureState>;
  ela: ElaConfig;
  /** AXI monitor found anywhere on the target (axi_mon_probe), or null.
   *  Its `chain` may differ from the session's — switching is transparent. */
  axiMon: AxiMonInfo | null;
  /** EJTAG-AXI bridge auto-detected on the target (ejtag_axi_probe), or null. */
  ejtagAxi: EjtagAxiInfo | null;
  /** Registered by the Connection panel: re-bind the session to another core
   *  (its BSCAN chain) so other panels can switch seamlessly. */
  chainSwitch: MutableRefObject<((chain: number) => Promise<void>) | null>;
  /** True while a core switch is in flight — capture controls must hold off
   *  (an arm built for one core would hit the other's geometry). */
  switching: boolean;
  setSwitching: (b: boolean) => void;
  setEla: (patch: Partial<ElaConfig>) => void;
  setAxiMon: (info: AxiMonInfo | null) => void;
  setEjtagAxi: (info: EjtagAxiInfo | null) => void;
  setCores: (cores: Core[]) => void;
  onConnected: (params: ConnectionParams, id: Identity) => void;
  onDisconnected: () => void;
  /** Store a capture under the core the session is bound to. */
  pushCapture: (capture: Omit<CaptureState, "seq">) => void;
}

const SessionCtx = createContext<Session | null>(null);

/** Read the shared session. Panels live inside Dockview but still see this
 *  context because dockview-react renders panels within the React tree. */
export function useSession(): Session {
  const v = useContext(SessionCtx);
  if (!v) throw new Error("useSession used outside <SessionProvider>");
  return v;
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [conn, setConn] = useState<ConnectionParams | null>(null);
  const [cores, setCores] = useState<Core[]>([]);
  const [captures, setCaptures] = useState<Record<number, CaptureState>>({});
  const [ela, setElaState] = useState<ElaConfig>(DEFAULT_ELA);
  const [axiMon, setAxiMonState] = useState<AxiMonInfo | null>(null);
  const [ejtagAxi, setEjtagAxiState] = useState<EjtagAxiInfo | null>(null);
  const [switching, setSwitching] = useState(false);
  const chainSwitch = useRef<((chain: number) => Promise<void>) | null>(null);

  const value = useMemo<Session>(
    () => ({
      identity,
      conn,
      cores,
      captures,
      ela,
      axiMon,
      ejtagAxi,
      chainSwitch,
      switching,
      setSwitching,
      setEla: (patch) => setElaState((p) => ({ ...p, ...patch })),
      setAxiMon: setAxiMonState,
      setEjtagAxi: setEjtagAxiState,
      setCores,
      onConnected: (params, id) => {
        setConn(params);
        setIdentity(id);
      },
      onDisconnected: () => {
        setConn(null);
        setIdentity(null);
        setCores([]);
        setCaptures({});
        setAxiMonState(null);
        setEjtagAxiState(null);
        // Reset the ELA config too: probes/trigger belong to the board we were
        // on. Without this, an AXI-monitor probe map (e.g. awaddr at bit 8,
        // width 32) carried over to the next board's plain 8-bit ELA and every
        // capture failed with "probe 'awaddr' exceeds sample width 8".
        setElaState(DEFAULT_ELA);
      },
      pushCapture: (next) => {
        const chain = conn?.chain;
        if (chain == null) return;
        setCaptures((prev) => ({
          ...prev,
          [chain]: { ...next, seq: (prev[chain]?.seq ?? 0) + 1 },
        }));
      },
    }),
    [identity, conn, cores, captures, ela, axiMon, ejtagAxi, switching],
  );

  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>;
}
