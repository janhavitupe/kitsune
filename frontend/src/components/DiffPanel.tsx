import type { ChangedRegion, Diff } from "../api/client";
import { cx } from "../lib/format";
import type { OverlayMode } from "./RegionOverlay";

interface Props {
  diff: Diff | null;
  error: string | null;
  message: string | null; // the AI commit message, when comparing a version with its parent
  mode: OverlayMode;
  onMode: (m: OverlayMode) => void;
  focus: number | null;
  onFocus: (i: number | null) => void;
}

const MODES: [OverlayMode, string][] = [
  ["regions", "Regions"],
  ["mask", "Pixels"],
  ["off", "Off"],
];

const pct = (x: number) => (x > 0 && x < 0.01 ? "<1%" : `${Math.round(x * 100)}%`);

function stat(r: ChangedRegion): string {
  // A named region reports how much of it changed; a change area is all change, so report its size.
  return r.source === "change" ? `${pct(r.image_share)} of canvas` : `${pct(r.changed_ratio)} changed`;
}

export default function DiffPanel({ diff, error, message, mode, onMode, focus, onFocus }: Props) {
  return (
    <aside className="space-y-4" aria-label="What changed">
      <div className="flex rounded-md border border-zinc-700 p-0.5 text-sm" role="radiogroup" aria-label="Overlay">
        {MODES.map(([m, label]) => (
          <button
            key={m}
            role="radio"
            aria-checked={mode === m}
            onClick={() => onMode(m)}
            className={cx("flex-1 rounded px-2 py-1", mode === m ? "bg-zinc-700" : "text-zinc-400 hover:text-zinc-200")}
          >
            {label}
          </button>
        ))}
      </div>

      {error ? (
        <p className="text-sm text-red-400">{error}</p>
      ) : !diff ? (
        <p className="animate-pulse text-sm text-zinc-400">Analyzing changes…</p>
      ) : (
        <>
          <div>
            <h3 className="text-xs font-medium tracking-wide text-zinc-500 uppercase">What changed</h3>
            <p className="mt-1 text-base leading-snug">{message ?? diff.summary}</p>
          </div>

          {diff.regions.length > 0 && (
            <ul className="space-y-1" onMouseLeave={() => onFocus(null)}>
              {diff.regions.map((r, i) => (
                <li key={`${r.label}-${i}`}>
                  <button
                    onMouseEnter={() => onFocus(i)}
                    onFocus={() => onFocus(i)}
                    onClick={() => onFocus(focus === i ? null : i)}
                    className={cx(
                      "w-full rounded-md border px-3 py-2 text-left transition-colors",
                      focus === i ? "border-orange-500 bg-orange-500/10" : "border-zinc-800 hover:border-zinc-600",
                    )}
                  >
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="font-medium first-letter:uppercase">{r.label}</span>
                      <span className="shrink-0 text-xs text-zinc-400">{stat(r)}</span>
                    </span>
                    <span className="mt-1 flex flex-wrap gap-1">
                      {r.hints.map((h) => (
                        <span key={h} className="rounded bg-zinc-800 px-1.5 py-0.5 text-[11px] text-zinc-300">
                          {h}
                        </span>
                      ))}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="space-y-1 text-xs text-zinc-500">
            <p>{pct(diff.changed_fraction)} of the canvas changed.</p>
            {!diff.segmented && diff.regions.length > 0 && <p>Areas are named by position until segmentation runs.</p>}
            {diff.resized && <p>The versions have different sizes; the older one was scaled to match.</p>}
          </div>
        </>
      )}
    </aside>
  );
}
