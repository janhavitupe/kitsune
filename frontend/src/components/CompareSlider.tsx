import { useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { assetUrl, type Commit } from "../api/client";

/**
 * Before/after slider: a on the left of the divider, b on the right.
 * Works with mouse, pen and touch (pointer events), and with arrow keys on the handle.
 * `overlay` is drawn over the whole image box (it describes b, whose aspect ratio the box uses).
 */
export default function CompareSlider({ a, b, overlay }: { a: Commit; b: Commit; overlay?: ReactNode }) {
  const [pos, setPos] = useState(50);
  const box = useRef<HTMLDivElement>(null);

  const moveTo = (clientX: number) => {
    const r = box.current!.getBoundingClientRect();
    setPos(Math.min(100, Math.max(0, ((clientX - r.left) / r.width) * 100)));
  };

  const onPointerDown = (e: PointerEvent) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    moveTo(e.clientX);
  };
  const onPointerMove = (e: PointerEvent) => {
    if (e.currentTarget.hasPointerCapture(e.pointerId)) moveTo(e.clientX);
  };
  const onKeyDown = (e: KeyboardEvent) => {
    const step = e.shiftKey ? 10 : 2;
    if (e.key === "ArrowLeft") setPos((p) => Math.max(0, p - step));
    if (e.key === "ArrowRight") setPos((p) => Math.min(100, p + step));
  };

  const ratio = b.width / b.height;

  return (
    <div className="flex justify-center rounded-md bg-zinc-900 p-2">
      <div
        ref={box}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        className="relative cursor-ew-resize touch-pan-y select-none"
        style={{ aspectRatio: `${b.width} / ${b.height}`, width: `min(100%, calc(70vh * ${ratio}))` }}
      >
        <img src={assetUrl(a.image_url)} alt={`Version ${a.seq}`} className="absolute inset-0 h-full w-full object-contain" draggable={false} />
        <img
          src={assetUrl(b.image_url)}
          alt={`Version ${b.seq}`}
          className="absolute inset-0 h-full w-full object-contain"
          style={{ clipPath: `inset(0 0 0 ${pos}%)` }}
          draggable={false}
        />
        {overlay}

        <span className="absolute top-2 left-2 rounded bg-black/60 px-2 py-0.5 text-xs">v{a.seq}</span>
        <span className="absolute top-2 right-2 rounded bg-black/60 px-2 py-0.5 text-xs">v{b.seq}</span>

        <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-white/90 shadow" style={{ left: `${pos}%` }}>
          <div
            role="slider"
            tabIndex={0}
            aria-label="Compare position"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(pos)}
            onKeyDown={onKeyDown}
            className="pointer-events-auto absolute top-1/2 left-1/2 flex size-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-white text-sm text-zinc-900 shadow-lg outline-none focus-visible:ring-2 focus-visible:ring-orange-500"
          >
            ⇆
          </div>
        </div>
      </div>
    </div>
  );
}
