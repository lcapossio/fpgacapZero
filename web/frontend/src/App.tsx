import { useEffect, useRef, useState } from "react";
import { DockviewReact } from "dockview-react";
import type { DockviewApi, DockviewReadyEvent, IDockviewPanelProps } from "dockview-react";
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

// Every panel the Tabs menu can restore (component key == panel id).
const PANELS: { id: keyof typeof components; title: string }[] = [
  { id: "connection", title: "Connection" },
  { id: "ela", title: "ELA" },
  { id: "eio", title: "EIO" },
  { id: "axi", title: "AXI" },
  { id: "run", title: "Run" },
  { id: "viewer", title: "Viewer" },
];

function buildDefaultLayout(api: DockviewApi) {
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
  // Run gets its own slim group with a real tab — the tab is the drag handle
  // (dockview can only drag via tab/title bars, so a custom grip can't work).
  api.addPanel({
    id: "run",
    component: "run",
    title: "Run",
    position: { referencePanel: "ela", direction: "below" },
    initialHeight: 88,
  });
  // Select ELA at startup (EIO/AXI were added after it and would otherwise win).
  api.getPanel("ela")?.api.setActive();
}

/** First panel id from `candidates` that is currently open, for anchoring a
 *  restored panel somewhere sensible in whatever layout the user has left. */
function firstOpen(api: DockviewApi, candidates: string[]): string | undefined {
  return candidates.find((id) => api.getPanel(id) !== undefined);
}

/** Re-add one closed panel near where the default layout puts it. */
function restorePanel(api: DockviewApi, id: (typeof PANELS)[number]["id"]) {
  if (api.getPanel(id)) return;
  const title = PANELS.find((p) => p.id === id)?.title;
  if (id === "run") {
    // Run lives in its own slim group under the config tabs.
    const anchor = firstOpen(api, ["ela", "eio", "axi", "connection", "viewer"]);
    api.addPanel({
      id,
      component: id,
      title,
      ...(anchor ? { position: { referencePanel: anchor, direction: "below" as const } } : {}),
      initialHeight: 88,
    });
    return;
  }
  if (id === "viewer") {
    const anchor = firstOpen(api, ["connection", "ela", "eio", "axi", "run"]);
    api.addPanel({
      id,
      component: id,
      title,
      ...(anchor ? { position: { referencePanel: anchor, direction: "below" as const } } : {}),
      initialHeight: 400,
    });
    return;
  }
  if (id === "connection") {
    const anchor = firstOpen(api, ["ela", "eio", "axi", "viewer", "run"]);
    api.addPanel({
      id,
      component: id,
      title,
      ...(anchor ? { position: { referencePanel: anchor, direction: "left" as const } } : {}),
    });
    return;
  }
  // ELA / EIO / AXI: stack with their sibling config tabs when any survive.
  const sibling = firstOpen(api, ["ela", "eio", "axi"]);
  const anchor = sibling ?? firstOpen(api, ["connection", "viewer", "run"]);
  api.addPanel({
    id,
    component: id,
    title,
    ...(anchor
      ? {
          position: {
            referencePanel: anchor,
            direction: sibling ? ("within" as const) : ("right" as const),
          },
        }
      : {}),
  });
}

/** Topbar dropdown: toggle tabs (checked = open, click to close; unchecked =
 *  closed, click to reopen) or rebuild the default layout — no page reload,
 *  so the session survives. */
function TabsMenu({ api }: { api: DockviewApi }) {
  const [open, setOpen] = useState(false);
  const [openIds, setOpenIds] = useState<string[]>(() => api.panels.map((p) => p.id));
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const sync = () => setOpenIds(api.panels.map((p) => p.id));
    const add = api.onDidAddPanel(sync);
    const remove = api.onDidRemovePanel(sync);
    return () => {
      add.dispose();
      remove.dispose();
    };
  }, [api]);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  return (
    <div className="tabs-menu" ref={ref}>
      <button className="secondary" onClick={() => setOpen((o) => !o)}>
        Tabs &#9662;
      </button>
      {open && (
        <div className="tabs-menu-list">
          {PANELS.map((p) => {
            const isOpen = openIds.includes(p.id);
            return (
              <button
                key={p.id}
                className="tabs-menu-item"
                onClick={() => {
                  const panel = api.getPanel(p.id);
                  if (panel) panel.api.close();
                  else restorePanel(api, p.id);
                }}
              >
                <span className="tabs-menu-check">{isOpen ? "✓" : ""}</span>
                {p.title}
              </button>
            );
          })}
          <div className="tabs-menu-sep" />
          <button
            className="tabs-menu-item"
            onClick={() => {
              api.clear();
              buildDefaultLayout(api);
              setOpen(false);
            }}
          >
            <span className="tabs-menu-check" />
            Reset layout
          </button>
        </div>
      )}
    </div>
  );
}

function Dock({ onApi }: { onApi: (api: DockviewApi) => void }) {
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
      onReady={(event: DockviewReadyEvent) => {
        buildDefaultLayout(event.api);
        onApi(event.api);
      }}
      // Keep hidden tabs mounted (just CSS-hidden) so the Surfer iframe — and
      // every panel's state — survives switching to a stacked tab.
      defaultRenderer="always"
    />
  );
}

export function App() {
  const [version, setVersion] = useState("");
  const [dockApi, setDockApi] = useState<DockviewApi | null>(null);
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
          {dockApi && <TabsMenu api={dockApi} />}
        </header>
        <Dock onApi={setDockApi} />
      </div>
    </SessionProvider>
  );
}
