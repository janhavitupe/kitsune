import { useEffect, useState, type PointerEvent } from "react";
import { api, assetUrl, type Commit } from "../api/client";
import { cx } from "../lib/format";

interface Props {
  source: Commit; // the older version the area comes from
  target: Commit; // the latest version it goes into
  onClose: () => void;
  onDone: (c: Commit) => void;
}

type Point = [number, number]; // shares of the image's width and height, 0..1

const MIN_STEP = 0.003; // skip pointer moves smaller than this, so an outline stays a few hundred points
const MAX_POINTS = 1500;

const thin = (points: Point[]) => {
  const every = Math.ceil(points.length / MAX_POINTS);
  return points.filter((_, i) => i % every === 0);
};

/** Draw around a part of an older version with mouse, pen or touch, and copy exactly that into the latest one. */
export default function SelectAreaDialog({ source, target, onClose, onDone }: Props) {
  const [points, setPoints] = useState<Point[]>([]);
  const [drawing, setDrawing] = useState(false);
  const [view, setView] = useState<"outline" | "result">("outline");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const at = (e: PointerEvent): Point => {
    const r = e.currentTarget.getBoundingClientRect();
    const share = (v: number) => Math.min(1, Math.max(0, v));
    return [share((e.clientX - r.left) / r.width), share((e.clientY - r.top) / r.height)];
  };

  const start = (e: PointerEvent) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    setDrawing(true);
    setError(null);
    setPoints([at(e)]);
  };
  const move = (e: PointerEvent) => {
    if (!drawing) return;
    const p = at(e);
    setPoints((ps) => {
      const last = ps[ps.length - 1];
      return Math.hypot(p[0] - last[0], p[1] - last[1]) < MIN_STEP ? ps : [...ps, p];
    });
  };
  const end = () => {
    setDrawing(false);
    if (points.length >= 3) setView("result");
  };

  const ready = !drawing && points.length >= 3;
  const svgPoints = points.map(([x, y]) => `${x},${y}`).join(" ");
  const clip = `polygon(${points.map(([x, y]) => `${x * 100}% ${y * 100}%`).join(",")})`;

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await api.copySelection(target.id, source.id, thin(points), name.trim() || undefined));
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/70 p-4" onClick={() => !busy && onClose()}>
      <div
        role="dialog"
        aria-label={`Copy part of v${source.seq}`}
        onClick={(e) => e.stopPropagation()}
        className="max-h-full w-full max-w-3xl overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 p-5"
      >
        <h2 className="text-lg font-semibold">Copy part of v{source.seq} into v{target.seq}</h2>
        <p className="mt-1 text-sm text-zinc-400">
          Draw around the part you want. Exactly what's inside your line is copied, and everything outside it stays as it is
          in v{target.seq}. The result is saved as a new version on {target.branch}.
        </p>

        <div className="mt-3 flex items-center gap-2">
          <div className="flex rounded-md border border-zinc-700 p-0.5 text-sm" role="tablist">
            {(["outline", "result"] as const).map((v) => (
              <button
                key={v}
                role="tab"
                aria-selected={view === v}
                disabled={v === "result" && !ready}
                onClick={() => setView(v)}
                className={cx(
                  "rounded px-3 py-1 disabled:opacity-40",
                  view === v ? "bg-zinc-700" : "text-zinc-400 hover:text-zinc-200",
                )}
              >
                {v === "outline" ? `Draw on v${source.seq}` : "See the result"}
              </button>
            ))}
          </div>
          {points.length > 0 && !drawing && (
            <button
              onClick={() => {
                setPoints([]);
                setView("outline");
              }}
              className="text-sm text-zinc-400 hover:text-zinc-200"
            >
              Start over
            </button>
          )}
        </div>

        <div className="mt-3 flex justify-center rounded-md bg-zinc-950">
          {view === "outline" ? (
            <div
              onPointerDown={start}
              onPointerMove={move}
              onPointerUp={end}
              onPointerCancel={end}
              className="relative cursor-crosshair touch-none select-none"
            >
              <img src={assetUrl(source.image_url)} alt={`Version ${source.seq}`} draggable={false} className="block max-h-[55vh] w-auto" />
              <svg viewBox="0 0 1 1" preserveAspectRatio="none" className="pointer-events-none absolute inset-0 h-full w-full">
                {points.length > 1 && (
                  <polygon
                    points={svgPoints}
                    fill="rgb(249 115 22 / 0.2)"
                    stroke="rgb(249 115 22)"
                    strokeWidth={2}
                    vectorEffect="non-scaling-stroke"
                  />
                )}
              </svg>
            </div>
          ) : (
            <div className="relative">
              <img src={assetUrl(target.image_url)} alt={`Version ${target.seq}`} className="block max-h-[55vh] w-auto" />
              <img
                src={assetUrl(source.image_url)}
                alt={`The selected part of version ${source.seq}`}
                style={{ clipPath: clip }}
                className="absolute inset-0 h-full w-full"
              />
            </div>
          )}
        </div>

        <label className="mt-3 block text-sm text-zinc-400">
          What is it? <span className="text-zinc-500">(optional, used in the version's message)</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={80}
            placeholder="e.g. lantern"
            className="mt-1 w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-sm text-zinc-100 outline-none focus:border-orange-500"
          />
        </label>

        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} disabled={busy} className="rounded-md px-3 py-1.5 text-sm text-zinc-300 hover:bg-zinc-800">
            Cancel
          </button>
          <button
            onClick={confirm}
            disabled={busy || !ready}
            className="rounded-md bg-orange-600 px-4 py-1.5 text-sm font-medium hover:bg-orange-500 disabled:opacity-50"
          >
            {busy ? "Copying…" : "Copy into a new version"}
          </button>
        </div>
      </div>
    </div>
  );
}
