import type { AnalysisStatus } from "../api/client";
import { cx } from "../lib/format";

const LABELS: Record<Exclude<AnalysisStatus, "done">, string> = {
  pending: "Queued",
  running: "Analyzing",
  failed: "Analysis failed",
};

/** Nothing is shown once analysis is done; only in-progress and failed states need attention. */
export default function StatusBadge({ status }: { status: AnalysisStatus }) {
  if (status === "done") return null;
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-zinc-400" title={LABELS[status]}>
      <span
        className={cx(
          "size-1.5 rounded-full",
          status === "pending" && "bg-zinc-500",
          status === "running" && "animate-pulse bg-amber-400",
          status === "failed" && "bg-red-500",
        )}
      />
      {LABELS[status]}
    </span>
  );
}
