import { useEffect, useState } from "react";
import { api, assetUrl, type Branch, type Commit } from "../api/client";
import { cx } from "../lib/format";

interface Props {
  commit: Commit;
  branches: Branch[];
  onClose: () => void;
  onChanged: () => void;
}

type Decision = "kept" | "discarded";

/** "Try 3 palettes for this": three preview branches off a version, each kept or discarded. */
export default function ExploreDialog({ commit, branches, onClose, onChanged }: Props) {
  const [prompt, setPrompt] = useState("");
  const [variants, setVariants] = useState<Commit[] | null>(null);
  const [decided, setDecided] = useState<Record<number, Decision>>({});
  const [names, setNames] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const shift = async () => {
    setBusy(true);
    setError(null);
    try {
      const v = await api.explore(commit.id, prompt);
      setVariants(v);
      setNames(Object.fromEntries(v.map((c) => [c.id, c.branch.replace(/^explore\//, "")])));
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  };

  const branchOf = (c: Commit) => branches.find((b) => b.id === c.branch_id);

  const decide = async (c: Commit, d: Decision) => {
    const b = branchOf(c);
    if (!b) return;
    setError(null);
    try {
      await api.updateBranch(b.id, d === "kept" ? { name: names[c.id], kind: "normal" } : { kind: "discarded" });
      setDecided((s) => ({ ...s, [c.id]: d }));
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/70 p-4" onClick={() => !busy && onClose()}>
      <div
        role="dialog"
        aria-label="Explore palettes"
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] w-full max-w-4xl overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 p-5"
      >
        <h2 className="text-lg font-semibold">Explore palettes for v{commit.seq}</h2>
        <p className="mt-1 text-sm text-zinc-400">
          Shifts the colors you painted, like an adjustment layer; nothing is redrawn. Each variation becomes its own
          branch. Keep the ones worth following; discarded ones are hidden, not deleted.
        </p>

        {!variants && (
          <div className="mt-4 flex flex-wrap gap-2">
            <input
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Optional: e.g. warmer, or darker"
              className="min-w-0 flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-sm outline-none focus:border-orange-500"
            />
            <button
              onClick={shift}
              disabled={busy}
              className="rounded-md bg-orange-600 px-4 py-1.5 text-sm font-medium hover:bg-orange-500 disabled:opacity-50"
            >
              {busy ? "Painting variations…" : prompt.trim() ? "Explore" : "Try golden hour, moonlit, overcast"}
            </button>
          </div>
        )}

        {variants && (
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {variants.map((v) => (
              <figure
                key={v.id}
                className={cx("overflow-hidden rounded-md border", decided[v.id] === "discarded" ? "border-zinc-800 opacity-40" : "border-zinc-700")}
              >
                <img src={assetUrl(v.image_url)} alt={v.message ?? "Variation"} className="w-full bg-zinc-950 object-contain" />
                <figcaption className="space-y-2 p-2.5 text-sm">
                  <p className="font-medium first-letter:uppercase">{String(v.origin_meta?.direction ?? v.branch)}</p>
                  {decided[v.id] ? (
                    <p className="text-xs text-zinc-400">{decided[v.id] === "kept" ? `Kept as ${names[v.id]}` : "Discarded"}</p>
                  ) : (
                    <>
                      <input
                        value={names[v.id] ?? ""}
                        onChange={(e) => setNames((s) => ({ ...s, [v.id]: e.target.value.replace(/\s+/g, "-") }))}
                        aria-label="Branch name"
                        className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs outline-none focus:border-orange-500"
                      />
                      <div className="flex gap-2">
                        <button onClick={() => decide(v, "kept")} className="flex-1 rounded-md bg-orange-600 px-2 py-1 text-xs font-medium hover:bg-orange-500">
                          Keep
                        </button>
                        <button onClick={() => decide(v, "discarded")} className="flex-1 rounded-md border border-zinc-700 px-2 py-1 text-xs hover:bg-zinc-800">
                          Discard
                        </button>
                      </div>
                    </>
                  )}
                </figcaption>
              </figure>
            ))}
          </div>
        )}

        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}

        <div className="mt-5 flex justify-end">
          <button onClick={onClose} disabled={busy} className="rounded-md px-3 py-1.5 text-sm text-zinc-300 hover:bg-zinc-800">
            {variants ? "Done" : "Cancel"}
          </button>
        </div>
      </div>
    </div>
  );
}
