import { createContext, useContext, useMemo, useRef, useState } from "react";
import type { MutableRefObject, ReactNode } from "react";
import type { ConnectionParams, Identity } from "./api";
import type { AxiMonInfo } from "./axiMon";

/** The latest ELA capture, shared from the Run panel to the Viewer panel. */
export interface CaptureState {
  vcd: string;
  csv?: string;
  json?: unknown;
  sampleCount?: number | string;
  seq: number; // bumps each capture so the viewer reloads even if panels are detached
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
  triggerMask: "0xFF",
  extTriggerMode: "0",
  useSequencer: false,
  sequenceJson: "",
  segmented: false,
  probesText: "",
};

interface Session {
  identity: Identity | null;
  conn: ConnectionParams | null;
  capture: CaptureState | null;
  ela: ElaConfig;
  /** AXI monitor found anywhere on the target (axi_mon_probe), or null.
   *  Its `chain` may differ from the session's — switching is transparent. */
  axiMon: AxiMonInfo | null;
  /** Registered by the Connection panel: re-bind the session to another core
   *  (its BSCAN chain) so other panels can switch seamlessly. */
  chainSwitch: MutableRefObject<((chain: number) => Promise<void>) | null>;
  setEla: (patch: Partial<ElaConfig>) => void;
  setAxiMon: (info: AxiMonInfo | null) => void;
  onConnected: (params: ConnectionParams, id: Identity) => void;
  onDisconnected: () => void;
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
  const [capture, setCapture] = useState<CaptureState | null>(null);
  const [ela, setElaState] = useState<ElaConfig>(DEFAULT_ELA);
  const [axiMon, setAxiMonState] = useState<AxiMonInfo | null>(null);
  const chainSwitch = useRef<((chain: number) => Promise<void>) | null>(null);

  const value = useMemo<Session>(
    () => ({
      identity,
      conn,
      capture,
      ela,
      axiMon,
      chainSwitch,
      setEla: (patch) => setElaState((p) => ({ ...p, ...patch })),
      setAxiMon: setAxiMonState,
      onConnected: (params, id) => {
        setConn(params);
        setIdentity(id);
      },
      onDisconnected: () => {
        setConn(null);
        setIdentity(null);
        setCapture(null);
        setAxiMonState(null);
      },
      pushCapture: (next) =>
        setCapture((prev) => ({ ...next, seq: (prev?.seq ?? 0) + 1 })),
    }),
    [identity, conn, capture, ela, axiMon],
  );

  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>;
}
