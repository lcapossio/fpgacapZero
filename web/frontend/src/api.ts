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
}

export interface CaptureSample {
  index: number;
  value: number;
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
): Promise<RpcResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch("/api/rpc", {
    method: "POST",
    headers,
    body: JSON.stringify({ cmd, ...params }),
  });
  if (res.status === 401) throw new Error("unauthorized — set the API token");
  const data = (await res.json()) as RpcResponse;
  if (!data.ok) throw new Error(data.error || `command '${cmd}' failed`);
  return data;
}

/** Parse a decimal or 0x-hex string into a number. */
export function parseIntFlexible(text: string): number {
  const t = text.trim();
  return t.toLowerCase().startsWith("0x") ? parseInt(t, 16) : parseInt(t, 10);
}
