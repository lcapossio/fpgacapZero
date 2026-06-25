import { createContext, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { ConnectionParams, Identity } from "./api";

/** The latest ELA capture, shared from the ELA panel to the Viewer panel. */
export interface CaptureState {
  vcd: string;
  seq: number; // bumps each capture so the viewer reloads even if panels are detached
}

interface Session {
  identity: Identity | null;
  conn: ConnectionParams | null;
  capture: CaptureState | null;
  onConnected: (params: ConnectionParams, id: Identity) => void;
  onDisconnected: () => void;
  pushCapture: (vcd: string) => void;
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

  const value = useMemo<Session>(
    () => ({
      identity,
      conn,
      capture,
      onConnected: (params, id) => {
        setConn(params);
        setIdentity(id);
      },
      onDisconnected: () => {
        setConn(null);
        setIdentity(null);
        setCapture(null);
      },
      pushCapture: (vcd) =>
        setCapture((prev) => ({ vcd, seq: (prev?.seq ?? 0) + 1 })),
    }),
    [identity, conn, capture],
  );

  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>;
}
