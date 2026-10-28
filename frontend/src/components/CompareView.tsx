import { useState } from "react";
import type { Commit } from "../api/client";
import { commitTitle, cx } from "../lib/format";
import CompareSlider from "./CompareSlider";
import SideBySide from "./SideBySide";

type Mode = "slider" | "side";

/** a is the older version, b the newer one. */
export default function CompareView({ a, b, onClose }: { a: Commit; b: Commit; onClose: () => void }) {
  const [mode, setMode] = useState<Mode>("slider");

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h2 className="font-medium">
          v{a.seq} <span className="text-zinc-500">→</span> v{b.seq}
        </h2>
        <span className="truncate text-sm text-zinc-400">{commitTitle(b)}</span>
        <div className="ml-auto flex items-center gap-2">
          <div className="flex rounded-md border border-zinc-700 p-0.5 text-sm" role="tablist">
            {(["slider", "side"] as const).map((m) => (
              <button
                key={m}
                role="tab"
                aria-selected={mode === m}
                onClick={() => setMode(m)}
                className={cx("rounded px-3 py-1", mode === m ? "bg-zinc-700" : "text-zinc-400 hover:text-zinc-200")}
              >
                {m === "slider" ? "Slider" : "Side by side"}
              </button>
            ))}
          </div>
          <button onClick={onClose} className="rounded-md px-2 py-1 text-sm text-zinc-400 hover:bg-zinc-800" title="Close compare">
            ✕
          </button>
        </div>
      </div>

      {mode === "slider" ? <CompareSlider a={a} b={b} /> : <SideBySide a={a} b={b} />}
    </div>
  );
}
