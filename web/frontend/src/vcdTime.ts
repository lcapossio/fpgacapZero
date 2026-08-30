// Trigger-time helpers shared by the Run panel and the Surfer view. Two pure
// functions: locate the trigger sample's time inside an exported VCD, and encode
// a time for Surfer's InjectMessage API. Kept out of the components so they can
// be unit-tested directly.

/** VCD time of the `sampleIndex`-th stored sample. Analyzer.export_vcd_text
 *  emits one `#<time>` line per sample, in capture order, so counting those
 *  lines maps a sample index to its time — correct whether the time is the bare
 *  index (no hardware timestamps) or a real per-sample timestamp. Returns
 *  undefined when the index is out of range or unparsable, so the caller just
 *  omits the marker. */
export function vcdTimeAtSample(vcd: string, sampleIndex: number): number | undefined {
  if (!Number.isFinite(sampleIndex) || sampleIndex < 0) return undefined;
  const want = Math.floor(sampleIndex);
  let count = 0;
  for (const line of vcd.split("\n")) {
    if (line.charCodeAt(0) !== 35 /* '#' */) continue;
    if (count === want) {
      const t = Number(line.slice(1).trim());
      return Number.isFinite(t) ? t : undefined;
    }
    count += 1;
  }
  return undefined;
}

/** Encode a non-negative integer as Surfer's `time` field: num-bigint's
 *  `(Sign, BigUint)` tuple, `[sign, [u32 digits little-endian]]`, where Sign is
 *  the i8 -1/0/1. Verified against the vendored WASM. */
export function bigIntTime(n: number): [number, number[]] {
  let v = Math.max(0, Math.floor(n));
  if (v === 0) return [0, []]; // NoSign, no digits
  const digits: number[] = [];
  while (v > 0) {
    digits.push(v >>> 0); // low 32 bits
    v = Math.floor(v / 0x1_0000_0000);
  }
  return [1, digits]; // Plus
}
