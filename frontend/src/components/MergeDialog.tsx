import { useEffect, useState } from "react";
import { api, assetUrl, type Branch, type Commit, type MergePlan, type Side } from "../api/client";
import { cx } from "../lib/format";

interface Props {
  repoId: number;
  branches: Branch[];
  commitsById: Map<number, Commit>;
  defaultSource: string;
  onClose: () => void;
  onMerged: (c: Commit) => void;
}

/** Check what merging one branch into another would do, pick a side for each conflict, merge. */
export default function MergeDialog({ repoId, branches, commitsById, defaultSource, onClose, onMerged }: Props) {
  const names = branches.filter((b) => b.head_commit_id !== null).map((b) => b.name);
  const [source, setSource] = useState(defaultSource);
  const [target, setTarget] = useState(names.find((n) => n !== defaultSource) ?? "main");
  const [plan, setPlan] = useState<MergePlan | null>(null);
  const [choices, setChoices] = useState<Record<number, Side>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    if (busy) return;
    if (plan?.status === "open") api.abortMerge(plan.id).catch(() => {});
    onClose();
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const check = async () => {
    setBusy(true);
    setError(null);
    setPlan(null);
    try {
      const p = await api.planMerge(repoId, source, target);
      setPlan(p);
      setChoices(Object.fromEntries(p.conflicts.map((c) => [c.index, "target" as Side])));
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  };

  const merge = async () => {
    if (!plan) return;
    setBusy(true);
    setError(null);
    try {
      onMerged(await api.resolveMerge(plan.id, choices));
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const sourceHead = plan ? commitsById.get(plan.source_head) : undefined;
  const targetHead = plan ? commitsById.get(plan.target_head) : undefined;

  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/70 p-4" onClick={close}>
      <div
        role="dialog"
        aria-label="Merge branches"
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 p-5"
      >
        <h2 className="text-lg font-semibold">Merge branches</h2>

        <div className="mt-4 flex flex-wrap items-end gap-2 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-zinc-400">Bring changes from</span>
            <BranchSelect value={source} options={names} onChange={(v) => (setSource(v), setPlan(null))} />
          </label>
          <span className="pb-2 text-zinc-500">into</span>
          <label className="flex flex-col gap-1">
            <span className="text-zinc-400">Branch</span>
            <BranchSelect value={target} options={names} onChange={(v) => (setTarget(v), setPlan(null))} />
          </label>
          <button
            onClick={check}
            disabled={busy || source === target}
            className="rounded-md border border-zinc-600 px-3 py-1.5 hover:bg-zinc-800 disabled:opacity-50"
          >
            {busy && !plan ? "Checking…" : "Check"}
          </button>
        </div>

        {plan && sourceHead && targetHead && (
          <div className="mt-5 space-y-4">
            {plan.fast_forward ? (
              <p className="text-sm text-zinc-300">
                <b>{plan.target}</b> hasn't changed since <b>{plan.source}</b> branched off, so the merge takes v{sourceHead.seq}{" "}
                as it is.
              </p>
            ) : null}

            {plan.auto.length > 0 && (
              <section>
                <h3 className="text-xs font-medium tracking-wide text-zinc-500 uppercase">Taken automatically</h3>
                <ul className="mt-2 space-y-1 text-sm">
                  {plan.auto.map((a, i) => (
                    <li key={i}>
                      <span className="first-letter:uppercase">{a.label}</span>
                      <span className="text-zinc-500"> from {plan.source} · {a.hints.join(", ")}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {plan.conflicts.length > 0 && (
              <section>
                <h3 className="text-xs font-medium tracking-wide text-zinc-500 uppercase">
                  Changed on both branches: pick one
                </h3>
                <div className="mt-2 space-y-3">
                  {plan.conflicts.map((c) => (
                    <div key={c.index} className="rounded-md border border-zinc-800 p-3">
                      <p className="text-sm font-medium first-letter:uppercase">{c.label}</p>
                      <div className="mt-2 grid grid-cols-2 gap-2">
                        {(
                          [
                            ["target", targetHead, plan.target],
                            ["source", sourceHead, plan.source],
                          ] as const
                        ).map(([side, commit, name]) => (
                          <button
                            key={side}
                            onClick={() => setChoices((s) => ({ ...s, [c.index]: side }))}
                            aria-pressed={choices[c.index] === side}
                            className={cx(
                              "overflow-hidden rounded-md border-2 text-left",
                              choices[c.index] === side ? "border-orange-500" : "border-transparent hover:border-zinc-600",
                            )}
                          >
                            <RegionCrop commit={commit} bbox={c.bbox} />
                            <span className="block px-2 py-1 text-xs">
                              {side === "target" ? "Keep" : "Take"} {name}'s (v{commit.seq})
                            </span>
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {!plan.fast_forward && plan.auto.length === 0 && plan.conflicts.length === 0 && (
              <p className="text-sm text-zinc-400">Both branches made the same changes; the merge only records that they came together.</p>
            )}
          </div>
        )}

        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={close} disabled={busy} className="rounded-md px-3 py-1.5 text-sm text-zinc-300 hover:bg-zinc-800">
            Cancel
          </button>
          <button
            onClick={merge}
            disabled={!plan || busy}
            className="rounded-md bg-orange-600 px-4 py-1.5 text-sm font-medium hover:bg-orange-500 disabled:opacity-50"
          >
            {busy && plan ? "Merging…" : plan ? `Merge into ${plan.target}` : "Merge"}
          </button>
        </div>
      </div>
    </div>
  );
}

function BranchSelect({ value, options, onChange }: { value: string; options: string[]; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className="rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1.5">
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

const PAD = 0.15;

/** The bbox of a region (fractions of the image), padded, cut out of a version's image with CSS. */
function RegionCrop({ commit, bbox }: { commit: Commit; bbox: [number, number, number, number] }) {
  const [bx, by, bw, bh] = bbox;
  const x = Math.max(0, bx - bw * PAD);
  const y = Math.max(0, by - bh * PAD);
  const w = Math.min(1 - x, bw * (1 + 2 * PAD));
  const h = Math.min(1 - y, bh * (1 + 2 * PAD));
  const pos = (start: number, size: number) => (size >= 0.999 ? 0 : (start / (1 - size)) * 100);
  return (
    <div
      className="w-full bg-zinc-950 bg-no-repeat"
      style={{
        aspectRatio: `${w * commit.width} / ${h * commit.height}`,
        maxHeight: 220,
        backgroundImage: `url(${assetUrl(commit.image_url)})`,
        backgroundSize: `${100 / w}% ${100 / h}%`,
        backgroundPosition: `${pos(x, w)}% ${pos(y, h)}%`,
      }}
    />
  );
}
