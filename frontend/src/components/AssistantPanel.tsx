import { useState, type FormEvent } from "react";
import { api, assetUrl, type AssistantEvent } from "../api/client";
import { cx } from "../lib/format";

interface Props {
  repoId: number;
  onClose: () => void;
  onChanged: () => void; // new versions were made
  onOpen: (commitId: number) => void;
}

const SUGGESTIONS = [
  "Take the sky from v1, keep today's figure, and warm it to match",
  "Show me what changed between the first version and now, and try a cooler version",
];

const TOOL_LABELS: Record<string, string> = {
  list_commits: "Read the history",
  get_changes: "Compared versions",
  get_regions: "Looked at the regions",
  bring_back: "Brought back a region",
  adjust: "Adjusted the colors",
  try_variant: "Tried a variation",
  set_message: "Wrote the message",
};

interface Step {
  step: number;
  name: string;
  args: Record<string, unknown>;
  result?: Record<string, unknown>;
  error?: string;
}

/** The studio assistant: an ask, its plan, every tool call as it runs, and the result. */
export default function AssistantPanel({ repoId, onClose, onChanged, onOpen }: Props) {
  const [ask, setAsk] = useState("");
  const [plan, setPlan] = useState<string | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [final, setFinal] = useState<Extract<AssistantEvent, { type: "final" }> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (text: string) => {
    if (!text.trim() || busy) return;
    setAsk(text);
    setPlan(null);
    setSteps([]);
    setFinal(null);
    setError(null);
    setBusy(true);
    try {
      await api.runAssistant(repoId, text.trim(), (e) => {
        if (e.type === "plan") setPlan(e.text);
        else if (e.type === "tool_call") setSteps((s) => [...s, { step: e.step, name: e.name, args: e.arguments }]);
        else if (e.type === "tool_result")
          setSteps((s) => s.map((x) => (x.step === e.step ? { ...x, result: e.result, error: e.error } : x)));
        else if (e.type === "final") {
          setFinal(e);
          if (e.created.length) onChanged();
        } else if (e.type === "error") setError(e.message);
      });
    } catch (err) {
      setError((err as Error).message);
    }
    setBusy(false);
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(ask);
  };

  return (
    <aside
      className="fixed inset-y-0 right-0 z-20 flex w-full max-w-md flex-col border-l border-zinc-700 bg-zinc-900 shadow-2xl"
      aria-label="Studio assistant"
    >
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <h2 className="font-semibold">Studio assistant</h2>
        <button onClick={onClose} className="rounded-md px-2 py-1 text-sm text-zinc-400 hover:bg-zinc-800" aria-label="Close">
          ✕
        </button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4 text-sm">
        {!plan && !error && !busy && (
          <div className="space-y-2">
            <p className="text-zinc-400">Ask for something that takes a few steps. Nothing is overwritten: results go on a new branch.</p>
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => run(s)} className="block w-full rounded-md border border-zinc-700 px-3 py-2 text-left hover:bg-zinc-800">
                {s}
              </button>
            ))}
          </div>
        )}

        {busy && !plan && <p className="animate-pulse text-zinc-400">Planning…</p>}

        {plan && (
          <section>
            <h3 className="text-xs font-medium tracking-wide text-zinc-500 uppercase">Plan</h3>
            <p className="mt-1 whitespace-pre-line text-zinc-200">{plan}</p>
          </section>
        )}

        {steps.length > 0 && (
          <section>
            <h3 className="text-xs font-medium tracking-wide text-zinc-500 uppercase">Steps</h3>
            <ol className="mt-2 space-y-2">
              {steps.map((s) => (
                <li key={s.step} className="flex gap-3 rounded-md border border-zinc-800 p-2">
                  <span
                    className={cx(
                      "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-[11px]",
                      s.error ? "bg-red-900 text-red-200" : s.result ? "bg-emerald-800 text-emerald-100" : "animate-pulse bg-zinc-700",
                    )}
                  >
                    {s.error ? "!" : s.result ? "✓" : s.step}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{TOOL_LABELS[s.name] ?? s.name}</p>
                    <p className="truncate text-xs text-zinc-500">{Object.values(s.args).map(String).join(" · ")}</p>
                    {s.error && <p className="mt-1 text-xs text-red-400">{s.error}</p>}
                  </div>
                  {typeof s.result?.thumb_url === "string" && (
                    <img src={assetUrl(s.result.thumb_url)} alt={String(s.result.version)} className="h-12 w-16 shrink-0 rounded object-cover" />
                  )}
                </li>
              ))}
            </ol>
          </section>
        )}

        {final && (
          <section className="rounded-md border border-orange-500/40 bg-orange-500/10 p-3">
            <p>{final.text}</p>
            {final.working_commit && (
              <button onClick={() => onOpen(final.working_commit!)} className="mt-2 text-orange-400 hover:underline">
                Open the result{final.branch ? ` on ${final.branch}` : ""} →
              </button>
            )}
          </section>
        )}

        {error && <p className="text-red-400">{error}</p>}
      </div>

      <form onSubmit={submit} className="flex gap-2 border-t border-zinc-800 p-3">
        <input
          value={ask}
          onChange={(e) => setAsk(e.target.value)}
          placeholder="Take the sky from v4, keep today's figure…"
          aria-label="Ask the assistant"
          className="min-w-0 flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-1.5 outline-none focus:border-orange-500"
        />
        <button disabled={busy || !ask.trim()} className="rounded-md bg-orange-600 px-3 py-1.5 font-medium hover:bg-orange-500 disabled:opacity-50">
          {busy ? "Working…" : "Ask"}
        </button>
      </form>
    </aside>
  );
}
