import { useEffect, useRef } from "react";

/** Minimal canvas trace of an N-sample, W-bit capture. */
export function Waveform({
  samples,
  sampleWidth,
}: {
  samples: number[];
  sampleWidth: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const w = canvas.width;
    const h = canvas.height;
    const pad = 6;
    ctx.fillStyle = "#0b0e14";
    ctx.fillRect(0, 0, w, h);

    if (samples.length === 0) return;
    const maxVal = (1 << sampleWidth) - 1 || 1;
    const n = samples.length;
    const dx = n > 1 ? (w - 2 * pad) / (n - 1) : 0;

    // baseline
    ctx.strokeStyle = "#222b39";
    ctx.beginPath();
    ctx.moveTo(pad, h - pad);
    ctx.lineTo(w - pad, h - pad);
    ctx.stroke();

    // trace
    ctx.strokeStyle = "#4ad0ff";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    samples.forEach((v, i) => {
      const x = pad + i * dx;
      const y = h - pad - (v / maxVal) * (h - 2 * pad);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }, [samples, sampleWidth]);

  return (
    <div className="waveform">
      <canvas ref={canvasRef} width={820} height={200} />
      <p className="muted">
        {samples.length} samples · {sampleWidth}-bit
      </p>
    </div>
  );
}
