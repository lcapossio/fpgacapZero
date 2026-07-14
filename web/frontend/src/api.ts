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

/** One fcapz debug core present on the connected target (from list_cores). */
export interface Core {
  type: string; // "ela" | "eio" | ...
  name: string;
  core_id: number;
  chain: number;
  base_addr: number;
  version_major: number;
  version_minor: number;
  info: Record<string, unknown>; // type-specific: ELA probe dict, or EIO {in_w,out_w}
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

/** In-band RPC failure ({ok:false}); `type` is the server-side exception
 *  class name (e.g. "TimeoutError") so callers can branch on it. */
export class RpcError extends Error {
  type?: string;
  constructor(message: string, type?: string) {
    super(message);
    this.name = "RpcError";
    this.type = type;
  }
}

const TOKEN_KEY = "fcapz_web_token";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(token: string): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

/** Thrown when a caller-supplied signal cancels an in-flight rpc(). */
export class RpcCancelled extends Error {
  constructor(cmd: string) {
    super(`'${cmd}' cancelled`);
    this.name = "RpcCancelled";
  }
}

export async function rpc(
  cmd: string,
  params: Record<string, unknown> = {},
  timeoutMs = 8000,
  signal?: AbortSignal,
): Promise<RpcResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const onCancel = () => controller.abort();
  if (signal?.aborted) onCancel();
  signal?.addEventListener("abort", onCancel);
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
      if (signal?.aborted) throw new RpcCancelled(cmd);
      throw new Error(`'${cmd}' timed out after ${timeoutMs / 1000}s`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onCancel);
  }
  if (res.status === 401) throw new Error("unauthorized — set the API token");
  const data = (await res.json()) as RpcResponse;
  if (!data.ok) throw new RpcError(data.error || `command '${cmd}' failed`, data.type);
  return data;
}

/** Parse a decimal or 0x-hex string into a number. */
export function parseIntFlexible(text: string): number {
  const t = text.trim();
  return t.toLowerCase().startsWith("0x") ? parseInt(t, 16) : parseInt(t, 10);
}

/** Parse a decimal or 0x-hex string into a canonical "0x…" hex string.
 *  The RPC server parses string numeric fields as base-16, so bare decimal
 *  input must be converted before it crosses the wire — otherwise "100"
 *  targets 0x100 while the UI displays 100. BigInt keeps >53-bit values
 *  exact; malformed input throws instead of silently misparsing. */
export function toHexParam(text: string, label: string): string {
  const t = text.trim();
  let v: bigint;
  try {
    if (!t) throw new Error("empty");
    v = BigInt(t);
  } catch {
    throw new Error(`invalid ${label} '${t}' — use decimal or 0x-hex`);
  }
  if (v < 0n) throw new Error(`${label} must be non-negative`);
  return "0x" + v.toString(16).toUpperCase();
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
