import { useEffect, useRef, useState } from "react";
import { DockviewReact } from "dockview-react";
import type { DockviewApi, DockviewReadyEvent, IDockviewPanelProps } from "dockview-react";
import "dockview-react/dist/styles/dockview.css";
import type { Core } from "./api";
import { SessionProvider, useSession } from "./session";
import { ConnectionPanel } from "./components/ConnectionPanel";
import { CoresPanel } from "./components/CoresPanel";
import { ElaPanel } from "./components/ElaPanel";
import { TriggerPanel } from "./components/TriggerPanel";
import { RunPanel } from "./components/RunPanel";
import { EioPanel } from "./components/EioPanel";
import { AxiPanel } from "./components/AxiPanel";
import { AxiMonPanel } from "./components/AxiMonPanel";
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
function CoresDock(_: IDockviewPanelProps) {
  return <CoresPanel />;
}
function ElaDock(_: IDockviewPanelProps) {
  const s = useSession();
  return s.conn && s.identity ? <ElaPanel /> : <Empty text="Connect to a target first." />;
}
function TriggerDock(_: IDockviewPanelProps) {
  return <TriggerPanel />;
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
function AxiMonDock(_: IDockviewPanelProps) {
  return <AxiMonPanel />;
}
/** Capture cores (plain ELAs and AXI monitors) in stable tab order. */
function captureCores(cores: Core[]): Core[] {
  return cores
    .filter((c) => c.type === "ela" || c.type === "axi_mon")
    .sort((a, b) => a.chain - b.chain);
}

function viewerTitle(core: Core): string {
  return core.type === "axi_mon" ? "Viewer: AXI Mon" : "Viewer: ELA";
}

function ViewerDock(props: IDockviewPanelProps) {
  const s = useSession();
  // Every capture core gets its own viewer tab pinned to its waveforms: the
  // default "viewer" panel shows the first core, "viewer-<chain>" the others
  // (the id — not params — carries the mapping, so it survives tab restore).
  // Mount Surfer right away so its WASM loads up front; the waveform drops in
  // when that core's first capture arrives.
  const m = /^viewer-(\d+)$/.exec(props.api.id);
  const chain = m ? Number(m[1]) : (captureCores(s.cores)[0]?.chain ?? s.conn?.chain);
  const cap = chain != null ? s.captures[chain] : undefined;
  return <SurferView vcd={cap?.vcd ?? ""} />;
}

/** Keeps the dock's viewer tabs matched to the discovered capture cores:
 *  retitles the default viewer after the first core and adds/removes a
 *  "viewer-<chain>" tab per additional core (stacked with the default one).
 *  Activating a viewer tab also re-binds the session to that tab's core, so
 *  clicking "Viewer: AXI Mon" makes the ELA/Run tabs drive the monitor. */
function ViewerTabsSync({ api }: { api: DockviewApi }) {
  const { cores, conn, chainSwitch } = useSession();
  // Latest session state for the (long-lived) dockview event handler.
  const stateRef = useRef({ cores, conn });
  stateRef.current = { cores, conn };
  const switching = useRef(false);

  useEffect(() => {
    const sync = () => {
      const cc = captureCores(cores);
      const base = api.getPanel("viewer");
      base?.api.setTitle(cc.length ? viewerTitle(cc[0]) : "Viewer");
      const wanted = new Set(cc.slice(1).map((c) => `viewer-${c.chain}`));
      for (const p of [...api.panels]) {
        if (/^viewer-\d+$/.test(p.id) && !wanted.has(p.id)) p.api.close();
      }
      let added = false;
      for (const c of cc.slice(1)) {
        const id = `viewer-${c.chain}`;
        const existing = api.getPanel(id);
        if (existing) existing.api.setTitle(viewerTitle(c));
        else {
          addExtraViewer(api, id, viewerTitle(c));
          added = true;
        }
      }
      // Keep the first core's viewer frontmost — a freshly added tab would win.
      if (added) api.getPanel("viewer")?.api.setActive();
    };
    sync();
    // Re-sync when a tab is restored from the Tabs menu or Reset layout.
    const d = api.onDidAddPanel(sync);
    return () => d.dispose();
  }, [api, cores]);

  useEffect(() => {
    // origin "user" filters out our own setActive/addPanel activations.
    const d = api.onDidActivePanelChange((e) => {
      if (e.origin !== "user" || switching.current) return;
      const id = e.panel?.id;
      if (!id) return;
      const { cores, conn } = stateRef.current;
      if (!conn) return;
      let chain: number | undefined;
      if (id === "viewer") chain = captureCores(cores)[0]?.chain;
      else {
        const m = /^viewer-(\d+)$/.exec(id);
        if (m) chain = Number(m[1]);
      }
      if (chain == null || chain === conn.chain) return;
      const sw = chainSwitch.current;
      if (!sw) return;
      switching.current = true;
      // Errors surface in the Connection panel via the switch itself.
      sw(chain)
        .catch(() => {})
        .finally(() => {
          switching.current = false;
        });
    });
    return () => d.dispose();
  }, [api, chainSwitch]);
  return null;
}

/** Bring the Cores tab forward once a connection lands, so the discovered
 *  cores are the first thing the user sees. */
function FocusCoresOnConnect({ api }: { api: DockviewApi }) {
  const { conn } = useSession();
  const hadConn = useRef(false);
  useEffect(() => {
    if (conn && !hadConn.current) api.getPanel("cores")?.api.setActive();
    hadConn.current = conn !== null;
  }, [api, conn]);
  return null;
}

/** Add a per-core viewer tab, stacked with the default viewer when it exists. */
function addExtraViewer(api: DockviewApi, id: string, title: string) {
  if (api.getPanel(id)) return;
  const anchor = firstOpen(api, ["viewer", "connection", "ela", "trigger", "eio", "axi", "axi_mon"]);
  api.addPanel({
    id,
    component: "viewer",
    title,
    ...(anchor
      ? {
          position: {
            referencePanel: anchor,
            direction: anchor === "viewer" ? ("within" as const) : ("below" as const),
          },
        }
      : {}),
    ...(anchor !== "viewer" ? { initialHeight: 400 } : {}),
  });
}

const components = {
  connection: ConnectionDock,
  cores: CoresDock,
  ela: ElaDock,
  trigger: TriggerDock,
  run: RunDock,
  eio: EioDock,
  axi: AxiDock,
  axi_mon: AxiMonDock,
  viewer: ViewerDock,
};

// Every panel the Tabs menu can restore (component key == panel id).
const PANELS: { id: keyof typeof components; title: string }[] = [
  { id: "connection", title: "Connection" },
  { id: "cores", title: "Cores" },
  { id: "ela", title: "ELA" },
  { id: "trigger", title: "Trigger" },
  { id: "eio", title: "EIO" },
  { id: "axi", title: "AXI" },
  { id: "axi_mon", title: "AXI Mon" },
  { id: "viewer", title: "Viewer" },
];

function buildDefaultLayout(api: DockviewApi) {
  api.addPanel({ id: "connection", component: "connection", title: "Connection" });
  // Cores stacks with Connection; the dock jumps to it once a connect lands.
  api.addPanel({
    id: "cores",
    component: "cores",
    title: "Cores",
    position: { referencePanel: "connection", direction: "within" },
  });
  // Viewer spans the full width across the bottom; controls live in the top row.
  api.addPanel({
    id: "viewer",
    component: "viewer",
    title: "Viewer",
    position: { referencePanel: "connection", direction: "below" },
    initialHeight: 400,
  });
  // Top row: Connection on the left, ELA/EIO/AXI tabs on the right.
  api.addPanel({
    id: "ela",
    component: "ela",
    title: "ELA",
    position: { referencePanel: "connection", direction: "right" },
  });
  api.addPanel({
    id: "trigger",
    component: "trigger",
    title: "Trigger",
    position: { referencePanel: "ela", direction: "within" },
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
  api.addPanel({
    id: "axi_mon",
    component: "axi_mon",
    title: "AXI Mon",
    position: { referencePanel: "ela", direction: "within" },
  });
  // Run sits between the config row and the viewer as a headerless strip.
  addRunStrip(api);
  // Show Connection (not Cores) in its group, and select ELA at startup
  // (panels added later in a group would otherwise win).
  api.getPanel("connection")?.api.setActive();
  api.getPanel("ela")?.api.setActive();
}

// The Run strip's fixed height: one control row, no tab header.
const RUN_STRIP_H = 40;

/** Add the Run controls as a slim strip directly above the viewer: its group
 *  has no tab header, can't be dragged into or resized — a fixed toolbar in
 *  the middle of the dock. */
function addRunStrip(api: DockviewApi) {
  if (api.getPanel("run")) return;
  const anchor = firstOpen(api, ["viewer", "connection", "ela", "trigger", "eio", "axi", "axi_mon"]);
  const panel = api.addPanel({
    id: "run",
    component: "run",
    title: "Run",
    ...(anchor
      ? {
          position: {
            referencePanel: anchor,
            direction: anchor === "viewer" ? ("above" as const) : ("below" as const),
          },
        }
      : {}),
    initialHeight: RUN_STRIP_H,
  });
  panel.group.header.hidden = true;
  panel.group.locked = "no-drop-target";
  panel.group.api.setConstraints({
    minimumHeight: RUN_STRIP_H,
    maximumHeight: RUN_STRIP_H,
  });
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
  if (id === "viewer") {
    const anchor = firstOpen(api, ["connection", "ela", "trigger", "eio", "axi", "axi_mon"]);
    api.addPanel({
      id,
      component: id,
      title,
      ...(anchor ? { position: { referencePanel: anchor, direction: "below" as const } } : {}),
      initialHeight: 400,
    });
    return;
  }
  if (id === "connection" || id === "cores") {
    // Connection and Cores stack together when either survives.
    const sibling = firstOpen(api, id === "connection" ? ["cores"] : ["connection"]);
    const anchor = sibling ?? firstOpen(api, ["ela", "trigger", "eio", "axi", "axi_mon", "viewer"]);
    api.addPanel({
      id,
      component: id,
      title,
      ...(anchor
        ? {
            position: {
              referencePanel: anchor,
              direction: sibling ? ("within" as const) : ("left" as const),
            },
          }
        : {}),
    });
    return;
  }
  // ELA / EIO / AXI / AXI Mon: stack with their sibling config tabs when any survive.
  const sibling = firstOpen(api, ["ela", "trigger", "eio", "axi", "axi_mon"]);
  const anchor = sibling ?? firstOpen(api, ["connection", "viewer"]);
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
  // Per-core viewer tabs come and go with the connection's core list.
  const { cores } = useSession();
  const extraViewers = captureCores(cores).slice(1);

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
          {extraViewers.map((c) => {
            const id = `viewer-${c.chain}`;
            const isOpen = openIds.includes(id);
            return (
              <button
                key={id}
                className="tabs-menu-item"
                onClick={() => {
                  const panel = api.getPanel(id);
                  if (panel) panel.api.close();
                  else addExtraViewer(api, id, viewerTitle(c));
                }}
              >
                <span className="tabs-menu-check">{isOpen ? "✓" : ""}</span>
                {viewerTitle(c)}
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
        {dockApi && <ViewerTabsSync api={dockApi} />}
        {dockApi && <FocusCoresOnConnect api={dockApi} />}
        <Dock onApi={setDockApi} />
      </div>
    </SessionProvider>
  );
}
