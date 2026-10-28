import { assetUrl, type Branch, type Commit } from "../api/client";
import { commitTitle, cx } from "../lib/format";
import StatusBadge from "./StatusBadge";
import { MicIcon } from "./VoiceRecorder";

const COL = 136; // horizontal distance between commits
const ROW = 124; // vertical distance between branch lanes
const CARD_W = 116;
const THUMB_H = 72;
const CARD_H = 108;
const GUTTER = 112; // lane labels on the left
const PAD = 12;
const GAP = COL - CARD_W; // space between neighbouring cards, where lane changes are drawn

interface Props {
  branches: Branch[];
  commits: Commit[]; // oldest first
  selected: number[];
  highlighted?: number[]; // search hits
  currentBranchHead: number | null;
  onSelect: (id: number, additive: boolean) => void;
}

/**
 * Commits in time order (x) on one lane per branch (y), with parent links drawn as curves.
 * Merge links are dashed. Lanes follow branch creation order, so main is always on top.
 */
export default function Timeline({ branches, commits, selected, highlighted = [], currentBranchHead, onSelect }: Props) {
  const lane = new Map(branches.map((b, i) => [b.id, i]));
  const kindOf = new Map(branches.map((b) => [b.id, b.kind]));
  const pos = new Map(
    commits.map((c, i) => [c.id, { x: GUTTER + i * COL, y: PAD + (lane.get(c.branch_id) ?? 0) * ROW }]),
  );
  const width = GUTTER + commits.length * COL + PAD;
  const height = PAD * 2 + branches.length * ROW - (ROW - CARD_H);

  /**
   * Lane changes happen inside the gap next to one end, so a link never runs behind another card:
   * a branch-off drops right after its parent (the child is the first card on its lane), and a
   * merge rises right before the merge commit (it travels along the source lane until then).
   */
  const edge = (fromId: number | null, toId: number, kind: "parent" | "merge") => {
    const from = fromId === null ? undefined : pos.get(fromId);
    const to = pos.get(toId)!;
    if (!from) return null;
    const x1 = from.x + CARD_W;
    const y1 = from.y + THUMB_H / 2;
    const x2 = to.x;
    const y2 = to.y + THUMB_H / 2;
    if (y1 === y2) return `M ${x1} ${y1} L ${x2} ${y2}`;
    const half = GAP / 2;
    return kind === "parent"
      ? `M ${x1} ${y1} C ${x1 + half} ${y1}, ${x1 + half} ${y2}, ${x1 + GAP} ${y2} L ${x2} ${y2}`
      : `M ${x1} ${y1} L ${x2 - GAP} ${y1} C ${x2 - half} ${y1}, ${x2 - half} ${y2}, ${x2} ${y2}`;
  };

  return (
    <div className="overflow-x-auto">
      <div className="relative" style={{ width, height }}>
        <svg className="absolute inset-0" width={width} height={height} aria-hidden>
          {branches.map((b, i) => (
            <line
              key={b.id}
              x1={GUTTER - 8}
              x2={width}
              y1={PAD + i * ROW + THUMB_H / 2}
              y2={PAD + i * ROW + THUMB_H / 2}
              className="stroke-zinc-900"
              strokeWidth={2}
            />
          ))}
          {commits.map((c) => {
            const main = edge(c.parent_id, c.id, "parent");
            const merge = edge(c.merge_parent_id, c.id, "merge");
            return (
              <g key={c.id} fill="none" strokeWidth={2}>
                {main && <path d={main} className="stroke-zinc-600" />}
                {merge && <path d={merge} className="stroke-zinc-600" strokeDasharray="5 4" />}
              </g>
            );
          })}
        </svg>

        {branches.map((b, i) => (
          <div
            key={b.id}
            className={cx("absolute left-3 truncate text-xs", b.kind === "explore" ? "text-zinc-500 italic" : "text-zinc-400")}
            style={{ top: PAD + i * ROW + THUMB_H / 2 - 8, width: GUTTER - 24 }}
            title={b.name}
          >
            {b.name}
          </div>
        ))}

        {commits.map((c) => {
          const p = pos.get(c.id)!;
          const slot = selected.indexOf(c.id);
          const exploring = kindOf.get(c.branch_id) === "explore";
          return (
            <button
              key={c.id}
              onClick={(e) => onSelect(c.id, e.shiftKey || e.metaKey || e.ctrlKey)}
              className={cx(
                "absolute flex flex-col overflow-hidden rounded-md border bg-zinc-900 text-left transition-colors",
                slot >= 0
                  ? "border-orange-500 ring-2 ring-orange-500/40"
                  : highlighted.includes(c.id)
                    ? "border-sky-400 ring-2 ring-sky-400/40"
                    : exploring
                      ? "border-dashed border-zinc-700 opacity-75 hover:border-zinc-500 hover:opacity-100"
                      : "border-zinc-700 hover:border-zinc-500",
              )}
              style={{ left: p.x, top: p.y, width: CARD_W, height: CARD_H }}
              title={commitTitle(c)}
              aria-pressed={slot >= 0}
            >
              <img
                src={assetUrl(c.thumb_url)}
                alt={`Version ${c.seq}`}
                className="w-full bg-zinc-800 object-cover"
                style={{ height: THUMB_H }}
                loading="lazy"
                draggable={false}
              />
              <span className="flex items-center gap-1 px-1.5 pt-1 text-xs">
                <span className="font-medium">v{c.seq}</span>
                {c.id === currentBranchHead && (
                  <span className="rounded bg-orange-600/30 px-1 text-[10px] text-orange-300">HEAD</span>
                )}
                {c.note_count > 0 && (
                  <span className="flex items-center gap-0.5 text-[10px] text-zinc-400" title={`${c.note_count} note(s)`}>
                    <MicIcon className="size-3" />
                    {c.note_count > 1 && c.note_count}
                  </span>
                )}
                {slot >= 0 && <span className="ml-auto font-semibold text-orange-400">{slot === 0 ? "A" : "B"}</span>}
              </span>
              <span className="truncate px-1.5 text-[11px] text-zinc-400">
                {c.analysis_status === "done" ? commitTitle(c) : <StatusBadge status={c.analysis_status} />}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
