import { useEffect, useState } from "react";
import { api, type Commit, type Diff } from "../api/client";
import { commitTitle, cx } from "../lib/format";
import CherryPickDialog from "./CherryPickDialog";
import CompareSlider from "./CompareSlider";
import DiffPanel from "./DiffPanel";
import RegionOverlay, { type OverlayMode } from "./RegionOverlay";
import SelectAreaDialog from "./SelectAreaDialog";
import SideBySide from "./SideBySide";

type Mode = "slider" | "side";

interface Props {
  a: Commit; // the older version
  b: Commit; // the newer version
  aIsHead: boolean; // a is its branch's latest version, so part of b can be copied into it
  bIsHead: boolean; // b is its branch's latest version, so regions can be brought back into it
  onClose: () => void;
  onCommitted: (c: Commit) => void;
}

export default function CompareView({ a, b, aIsHead, bIsHead, onClose, onCommitted }: Props) {
  const [mode, setMode] = useState<Mode>("slider");
  const [overlay, setOverlay] = useState<OverlayMode>("regions");
  const [diff, setDiff] = useState<Diff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [focus, setFocus] = useState<number | null>(null);
  const [picking, setPicking] = useState<string | null>(null);
  const [selecting, setSelecting] = useState<{ source: Commit; target: Commit } | null>(null);

  useEffect(() => {
    let live = true;
    setDiff(null);
    setError(null);
    setFocus(null);
    api.getDiff(a.id, b.id).then(
      (d) => live && setDiff(d),
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [a.id, b.id]);

  // The AI message describes a version against its parent, so only show it for that pair.
  const message = b.parent_id === a.id ? b.auto_message : null;
  const layer = <RegionOverlay diff={diff} mode={overlay} focus={focus} />;

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

      <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
        <div className="min-w-0">
          {mode === "slider" ? <CompareSlider a={a} b={b} overlay={layer} /> : <SideBySide a={a} b={b} overlay={layer} />}
        </div>
        <DiffPanel
          diff={diff}
          error={error}
          message={message}
          mode={overlay}
          onMode={setOverlay}
          focus={focus}
          onFocus={setFocus}
          restoreFrom={bIsHead ? { seq: a.seq, onRestore: setPicking } : undefined}
        />
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {bIsHead && (
          <button
            onClick={() => setSelecting({ source: a, target: b })}
            className="rounded-md border border-zinc-700 px-3 py-1.5 text-sm hover:bg-zinc-900"
          >
            Select part of v{a.seq} by hand, for v{b.seq}…
          </button>
        )}
        {aIsHead && (
          <button
            onClick={() => setSelecting({ source: b, target: a })}
            className="rounded-md border border-zinc-700 px-3 py-1.5 text-sm hover:bg-zinc-900"
          >
            Select part of v{b.seq} by hand, for v{a.seq}…
          </button>
        )}
      </div>

      {selecting && (
        <SelectAreaDialog
          source={selecting.source}
          target={selecting.target}
          onClose={() => setSelecting(null)}
          onDone={(c) => {
            setSelecting(null);
            onCommitted(c);
          }}
        />
      )}

      {picking && (
        <CherryPickDialog
          source={a}
          target={b}
          label={picking}
          onClose={() => setPicking(null)}
          onDone={(c) => {
            setPicking(null);
            onCommitted(c);
          }}
        />
      )}
    </div>
  );
}
