import { useEffect, useState } from "react";
import { DockviewReact } from "dockview-react";
import type { DockviewReadyEvent, IDockviewPanelProps } from "dockview-react";
import "dockview-react/dist/styles/dockview.css";
import { SessionProvider, useSession } from "./session";
import { ConnectionPanel } from "./components/ConnectionPanel";
import { ElaPanel } from "./components/ElaPanel";
import { RunPanel } from "./components/RunPanel";
import { EioPanel } from "./components/EioPanel";
import { AxiPanel } from "./components/AxiPanel";
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
function AxiDock(_: IDockviewPanelProps) {
  const s = useSession();
  return s.conn ? <AxiPanel conn={s.conn} /> : <Empty text="Connect to a target first." />;
}
function ViewerDock(_: IDockviewPanelProps) {
  const s = useSession();
  // Mount Surfer right away so its WASM loads up front; the waveform drops in
  // when the first capture arrives (empty vcd just shows an idle Surfer).
  return <SurferView vcd={s.capture?.vcd ?? ""} />;
}

const components = {
  connection: ConnectionDock,
  ela: ElaDock,
  run: RunDock,
  eio: EioDock,
  axi: AxiDock,
  viewer: ViewerDock,
};

function onReady(event: DockviewReadyEvent) {
  const api = event.api;
  api.addPanel({ id: "connection", component: "connection", title: "Connection" });
  // Viewer spans the full width across the bottom; controls live in the top row.
  api.addPanel({
    id: "viewer",
    component: "viewer",
    title: "Viewer",
    position: { referencePanel: "connection", direction: "below" },
    initialHeight: 400,
  });
  // Top row: Connection on the left, ELA/EIO/AXI tabs (+ slim Run) on the right.
  api.addPanel({
    id: "ela",
    component: "ela",
    title: "ELA",
    position: { referencePanel: "connection", direction: "right" },
  });
  api.addPanel({
    id: "eio",
    component: "eio",
    title: "EIO",
    position: { referencePanel: "ela", direction: "within" },
  });
  api.addPanel({
    id: "axi",
    component: "axi",
    title: "AXI",
    position: { referencePanel: "ela", direction: "within" },
  });
  const runGroup = api.addGroup({
    id: "run-group",
    referencePanel: "ela",
    direction: "below",
    hideHeader: true,
    initialHeight: 58,
  });
  api.addPanel({
    id: "run",
    component: "run",
    position: { referenceGroup: runGroup, direction: "within" },
  });
  // Select ELA at startup (EIO/AXI were added after it and would otherwise win).
  api.getPanel("ela")?.api.setActive();
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
  const [version, setVersion] = useState("");
  useEffect(() => {
    fetch("/api/version")
      .then((r) => r.json())
      .then((d) => setVersion(typeof d.version === "string" ? d.version : ""))
      .catch(() => {});
  }, []);

  return (
    <SessionProvider>
      <div className="app-shell">
        <header className="topbar">
          <img className="logo" src="/fcapz_logo.png" alt="fcapz logo" />
          <h1>fpgacapZero</h1>
          <span className="muted">web{version ? ` · v${version}` : ""}</span>
        </header>
        <Dock />
      </div>
    </SessionProvider>
  );
}
