import { useEffect } from "react";
import { DockviewReact } from "dockview-react";
import type { DockviewReadyEvent, IDockviewPanelProps } from "dockview-react";
import "dockview-react/dist/styles/dockview.css";
import { SessionProvider, useSession } from "./session";
import { ConnectionPanel } from "./components/ConnectionPanel";
import { ElaPanel } from "./components/ElaPanel";
import { RunPanel } from "./components/RunPanel";
import { EioPanel } from "./components/EioPanel";
import { SurferView } from "./components/SurferView";

function Empty({ text }: { text: string }) {
  return <div className="dock-empty muted">{text}</div>;
}

// Dock panels. Each reads the shared session; dockview-react keeps React
// context, so these stay in sync as the connection/capture changes.
function ConnectionDock(_: IDockviewPanelProps) {
  const s = useSession();
  return (
    <ConnectionPanel
      identity={s.identity}
      onConnected={s.onConnected}
      onDisconnected={s.onDisconnected}
    />
  );
}
function ElaDock(_: IDockviewPanelProps) {
  const s = useSession();
  return s.conn && s.identity ? <ElaPanel /> : <Empty text="Connect to a target first." />;
}
function RunDock(_: IDockviewPanelProps) {
  const s = useSession();
  return s.conn && s.identity ? (
    <RunPanel identity={s.identity} />
  ) : (
    <Empty text="Connect to a target first." />
  );
}
function EioDock(_: IDockviewPanelProps) {
  const s = useSession();
  return s.conn ? <EioPanel conn={s.conn} /> : <Empty text="Connect to a target first." />;
}
function ViewerDock(_: IDockviewPanelProps) {
  const s = useSession();
  return s.capture ? (
    <SurferView vcd={s.capture.vcd} />
  ) : (
    <Empty text="Run an ELA capture to see the waveform here." />
  );
}

const components = {
  connection: ConnectionDock,
  ela: ElaDock,
  run: RunDock,
  eio: EioDock,
  viewer: ViewerDock,
};

function onReady(event: DockviewReadyEvent) {
  const api = event.api;
  api.addPanel({ id: "connection", component: "connection", title: "Connection" });
  api.addPanel({
    id: "viewer",
    component: "viewer",
    title: "Viewer",
    position: { referencePanel: "connection", direction: "right" },
  });
  api.addPanel({
    id: "ela",
    component: "ela",
    title: "ELA",
    position: { referencePanel: "connection", direction: "below" },
  });
  api.addPanel({
    id: "eio",
    component: "eio",
    title: "EIO",
    position: { referencePanel: "ela", direction: "within" },
  });
  // Run is a slim toolbar in its own short group beneath ELA/EIO.
  api.addPanel({
    id: "run",
    component: "run",
    title: "Run",
    position: { referencePanel: "ela", direction: "below" },
    initialHeight: 80,
  });
}

function Dock() {
  // While a tab is being dragged, stop the Surfer iframe from swallowing the
  // pointer so drops land on the dock, not inside the waveform.
  useEffect(() => {
    const on = () => document.body.classList.add("dv-dragging-tabs");
    const off = () => document.body.classList.remove("dv-dragging-tabs");
    document.addEventListener("dragstart", on, true);
    document.addEventListener("dragend", off, true);
    document.addEventListener("drop", off, true);
    return () => {
      document.removeEventListener("dragstart", on, true);
      document.removeEventListener("dragend", off, true);
      document.removeEventListener("drop", off, true);
    };
  }, []);

  return (
    <DockviewReact
      className="dockview-theme-abyss dock"
      components={components}
      onReady={onReady}
      // Keep hidden tabs mounted (just CSS-hidden) so the Surfer iframe — and
      // every panel's state — survives switching to a stacked tab.
      defaultRenderer="always"
    />
  );
}

export function App() {
  return (
    <SessionProvider>
      <div className="app-shell">
        <header className="topbar">
          <h1>fpgacapZero</h1>
          <span className="muted">web</span>
        </header>
        <Dock />
      </div>
    </SessionProvider>
  );
}
