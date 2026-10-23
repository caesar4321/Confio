/** A member's return over time, as the server sends it. */
export type ReturnPoint = { at: string; pct: string };

/**
 * SVG path ("M x y L x y ...") for the returns line, x by time and y by the
 * cumulative percent, padded so the stroke never clips. Null when there is
 * nothing to draw (fewer than two readable points or no width yet).
 */
export const returnsPath = (points: ReturnPoint[], width: number, height: number, pad = 4): string | null => {
  const parsed = points
    .map((p) => ({ t: Date.parse(p.at), v: Number(p.pct) }))
    .filter((p) => Number.isFinite(p.t) && Number.isFinite(p.v));
  if (parsed.length < 2 || width <= 0 || height <= 0) return null;
  const t0 = parsed[0].t;
  const t1 = parsed[parsed.length - 1].t;
  const lo = Math.min(...parsed.map((p) => p.v));
  const hi = Math.max(...parsed.map((p) => p.v));
  const spanT = t1 - t0 || 1;
  // A flat line sits in the middle instead of on an edge.
  const spanV = hi - lo || 1;
  const offset = hi === lo ? 0.5 : 0;
  return parsed
    .map((p, i) => {
      const x = pad + ((p.t - t0) / spanT) * (width - pad * 2);
      const y = pad + (1 - ((p.v - lo) / spanV + offset)) * (height - pad * 2);
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');
};

export const RETURN_RANGES = [
  { key: '24h', label: '24 h' },
  { key: '7d', label: '7 d' },
  { key: '30d', label: '30 d' },
] as const;

export type ReturnRange = (typeof RETURN_RANGES)[number]['key'];
