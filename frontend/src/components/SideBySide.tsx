import { useEffect, useRef, useState, type PointerEvent } from "react";
import { assetUrl, type Commit } from "../api/client";

interface View {
  scale: number;
  x: number;
  y: number;
}

const RESET: View = { scale: 1, x: 0, y: 0 };
const MAX_SCALE = 8;

const clampScale = (s: number) => Math.min(MAX_SCALE, Math.max(1, s));

/** Two versions side by side (stacked on narrow screens) sharing one zoom and pan. */
export default function SideBySide({ a, b }: { a: Commit; b: Commit }) {
  const [view, setView] = useState<View>(RESET);
  const zoom = (factor: number) =>
    setView((v) => {
      const scale = clampScale(v.scale * factor);
      return scale === 1 ? RESET : { ...v, scale };
    });

  return (
    <div>
      <div className="grid gap-2 md:grid-cols-2">
        <Pane commit={a} view={view} setView={setView} />
        <Pane commit={b} view={view} setView={setView} />
      </div>
      <div className="mt-2 flex items-center justify-center gap-2 text-sm">
        <button onClick={() => zoom(1 / 1.5)} className="rounded-md border border-zinc-700 px-3 py-1 hover:bg-zinc-900" aria-label="Zoom out">
          −
        </button>
        <span className="w-14 text-center text-zinc-400">{Math.round(view.scale * 100)}%</span>
        <button onClick={() => zoom(1.5)} className="rounded-md border border-zinc-700 px-3 py-1 hover:bg-zinc-900" aria-label="Zoom in">
          +
        </button>
        <button onClick={() => setView(RESET)} className="rounded-md border border-zinc-700 px-3 py-1 hover:bg-zinc-900">
          Reset
        </button>
        <span className="hidden text-xs text-zinc-500 md:inline">Scroll to zoom, drag to pan</span>
      </div>
    </div>
  );
}

function Pane({ commit, view, setView }: { commit: Commit; view: View; setView: (f: (v: View) => View) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const last = useRef<{ x: number; y: number } | null>(null);

  // React's onWheel is passive, so it can't stop the page from scrolling; attach it by hand.
  useEffect(() => {
    const el = ref.current!;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      setView((v) => {
        const scale = clampScale(v.scale * Math.exp(-e.deltaY * 0.0015));
        return scale === 1 ? RESET : { ...v, scale };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [setView]);

  const onPointerDown = (e: PointerEvent) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    last.current = { x: e.clientX, y: e.clientY };
  };
  const onPointerMove = (e: PointerEvent) => {
    if (!last.current) return;
    const dx = e.clientX - last.current.x;
    const dy = e.clientY - last.current.y;
    last.current = { x: e.clientX, y: e.clientY };
    setView((v) => (v.scale === 1 ? v : { ...v, x: v.x + dx, y: v.y + dy }));
  };
  const onPointerUp = () => {
    last.current = null;
  };

  return (
    <div
      ref={ref}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      className="relative overflow-hidden rounded-md bg-zinc-900 select-none"
      style={{ aspectRatio: `${commit.width} / ${commit.height}`, maxHeight: "70vh", cursor: view.scale > 1 ? "grab" : "default" }}
    >
      <img
        src={assetUrl(commit.image_url)}
        alt={`Version ${commit.seq}`}
        className="h-full w-full object-contain"
        style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}
        draggable={false}
      />
      <span className="absolute top-2 left-2 rounded bg-black/60 px-2 py-0.5 text-xs">v{commit.seq}</span>
    </div>
  );
}
