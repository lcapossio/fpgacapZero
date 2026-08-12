import type { DockviewApi } from "dockview-react";

/** A serialized dockview layout (whatever DockviewApi.toJSON produces). Typed
 *  off the API so we never import dockview-core's internal type directly. */
export type DockLayout = ReturnType<DockviewApi["toJSON"]>;

// Last layout, auto-saved on change and restored on load.
const CURRENT_KEY = "fcapz_dock_layout";
// User-named layouts: { name: layout }.
const NAMED_KEY = "fcapz_dock_layouts";

export function saveCurrentLayout(data: DockLayout): void {
  try {
    localStorage.setItem(CURRENT_KEY, JSON.stringify(data));
  } catch {
    /* storage full/disabled — layout just won't persist */
  }
}

export function loadCurrentLayout(): DockLayout | null {
  try {
    const s = localStorage.getItem(CURRENT_KEY);
    return s ? (JSON.parse(s) as DockLayout) : null;
  } catch {
    return null;
  }
}

function readNamed(): Record<string, DockLayout> {
  try {
    return JSON.parse(localStorage.getItem(NAMED_KEY) || "{}") as Record<string, DockLayout>;
  } catch {
    return {};
  }
}

function writeNamed(map: Record<string, DockLayout>): void {
  try {
    localStorage.setItem(NAMED_KEY, JSON.stringify(map));
  } catch {
    /* ignore */
  }
}

export function listNamedLayouts(): string[] {
  return Object.keys(readNamed()).sort((a, b) => a.localeCompare(b));
}

export function saveNamedLayout(name: string, data: DockLayout): void {
  const map = readNamed();
  map[name] = data;
  writeNamed(map);
}

export function loadNamedLayout(name: string): DockLayout | null {
  return readNamed()[name] ?? null;
}

export function deleteNamedLayout(name: string): void {
  const map = readNamed();
  delete map[name];
  writeNamed(map);
}
