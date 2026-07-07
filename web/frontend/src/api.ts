// Client for the fcapz unified JSON-RPC API (POST /api/rpc).
// Every call sends {cmd, ...params}; errors arrive in-band as {ok:false,...}.

export interface RpcResponse {
  ok: boolean;
  error?: string;
  type?: string;
  [key: string]: unknown;
}

export interface ConnectionParams {
  backend: string;
  host: string;
  port: number;
  tap: string;
  ir_table: string;
  chain: number;
}

export interface Identity {
  version_major: number;
  version_minor: number;
  core_id: number;
  sample_width: number;
  depth: number;
  num_channels: number;
  num_segments?: number;
  // Optional ELA capability flags (present on current servers).
  trig_stages?: number;
  has_storage_qualification?: boolean;
  has_decimation?: boolean;
  has_ext_trigger?: boolean;
  has_timestamp?: boolean;
  timestamp_width?: number;
  has_dual_compare?: boolean;
}

/** A discovered fpgacapZero-compatible board (one OpenOCD tap that probed as an ELA). */
export interface Board {
  backend: string;
  host: string;
  port: number;
  tap: string;
  ir_table: string;
  identity: Identity;
  label: string;
}

export interface CaptureSample {
  index: number;
  value: number;
}

export interface ProbeSpec {
  name: string;
  width: number;
  lsb: number;
}

const TOKEN_KEY = "fcapz_web_token";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(token: string): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function rpc(
  cmd: string,
  params: Record<string, unknown> = {},
  timeoutMs = 8000,
): Promise<RpcResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch("/api/rpc", {
      method: "POST",
      headers,
      body: JSON.stringify({ cmd, ...params }),
      signal: controller.signal,
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error(`'${cmd}' timed out after ${timeoutMs / 1000}s`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
  if (res.status === 401) throw new Error("unauthorized — set the API token");
  const data = (await res.json()) as RpcResponse;
  if (!data.ok) throw new Error(data.error || `command '${cmd}' failed`);
  return data;
}

/** Guess the IR table from a tap/target name. */
export function inferIrTable(tap: string): string {
  const t = tap.toLowerCase();
  if (t.startsWith("gw")) return "gowin";
  if (t.startsWith("xcku") || t.startsWith("xcvu") || t.startsWith("xcau"))
    return "ultrascale";
  return "xilinx7";
}

/** Parse a decimal or 0x-hex string into a number. */
export function parseIntFlexible(text: string): number {
  const t = text.trim();
  return t.toLowerCase().startsWith("0x") ? parseInt(t, 16) : parseInt(t, 10);
}

export function parseProbesText(text: string): ProbeSpec[] {
  const trimmed = text.trim();
  if (!trimmed) return [];
  if (trimmed.startsWith("{")) {
    const data = JSON.parse(trimmed) as { probes?: ProbeSpec[] };
    if (!Array.isArray(data.probes)) throw new Error(".prob JSON must contain a probes array");
    return data.probes.map((p) => ({
      name: String(p.name),
      width: Number(p.width),
      lsb: Number(p.lsb ?? 0),
    }));
  }
  return trimmed
    .split(/\r?\n|,/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((line) => {
      const [name, width, lsb = "0"] = line.split(":");
      if (!name || !width) throw new Error(`invalid probe '${line}', expected name:width:lsb`);
      return { name, width: Number(width), lsb: Number(lsb) };
    });
}

export function downloadText(filename: string, text: string, type = "text/plain"): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
