import { useState } from "react";
import type { ConnectionParams, Identity } from "./api";
import { ConnectionPanel } from "./components/ConnectionPanel";
import { ElaPanel } from "./components/ElaPanel";
import { EioPanel } from "./components/EioPanel";

export function App() {
  // The params used for the active connection — EIO needs them because
  // `eio_connect` opens its own transport (a separate JTAG session).
  const [conn, setConn] = useState<ConnectionParams | null>(null);
  const [identity, setIdentity] = useState<Identity | null>(null);

  function onConnected(params: ConnectionParams, id: Identity) {
    setConn(params);
    setIdentity(id);
  }
  function onDisconnected() {
    setConn(null);
    setIdentity(null);
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1>fpgacapZero</h1>
        <span className="muted">web</span>
      </header>

      <ConnectionPanel
        identity={identity}
        onConnected={onConnected}
        onDisconnected={onDisconnected}
      />

      {conn && identity && <ElaPanel identity={identity} />}
      {conn && <EioPanel conn={conn} />}
    </div>
  );
}
