import { useState, type FormEvent } from "react";
import { api, type SearchResponse } from "../api/client";

interface Props {
  repoId: number;
  onResults: (ids: number[]) => void; // highlighted in the timeline
  onPick: (commitId: number) => void;
}

/** Search the history: messages, notes, captions, changed regions, and "before I changed the sky". */
export default function SearchBar({ repoId, onResults, onPick }: Props) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<SearchResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (e: FormEvent) => {
    e.preventDefault();
    if (!q.trim()) return clear();
    setBusy(true);
    setError(null);
    try {
      const r = await api.search(repoId, q.trim());
      setRes(r);
      onResults(r.results.map((x) => x.commit_id));
    } catch (err) {
      setError((err as Error).message);
    }
    setBusy(false);
  };

  const clear = () => {
    setQ("");
    setRes(null);
    onResults([]);
  };

  return (
    <div className="px-4 pt-3">
      <form onSubmit={run} className="flex gap-2" role="search">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder='Search the history, e.g. "before I changed the sky"'
          aria-label="Search the history"
          className="min-w-0 flex-1 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm outline-none focus:border-orange-500"
        />
        <button disabled={busy} className="rounded-md border border-zinc-700 px-3 py-1.5 text-sm hover:bg-zinc-800 disabled:opacity-50">
          {busy ? "Searching…" : "Search"}
        </button>
        {res && (
          <button type="button" onClick={clear} className="rounded-md px-2 py-1.5 text-sm text-zinc-400 hover:bg-zinc-800">
            Clear
          </button>
        )}
      </form>
      {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
      {res && (
        <ul className="mt-2 space-y-1">
          {res.results.length === 0 && <li className="text-sm text-zinc-500">No versions match.</li>}
          {res.results.map((r) => (
            <li key={r.commit_id}>
              <button onClick={() => onPick(r.commit_id)} className="w-full rounded-md px-2 py-1 text-left text-sm hover:bg-zinc-900">
                <span className="font-medium">v{r.seq}</span> <span className="text-zinc-400">· {r.reason}</span>
                {r.snippet && <Snippet text={r.snippet} />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The server marks hits with [brackets]; show them highlighted. */
function Snippet({ text }: { text: string }) {
  const parts = text.split(/(\[[^\]]*\])/g);
  return (
    <span className="block truncate text-xs text-zinc-500">
      {parts.map((p, i) =>
        p.startsWith("[") && p.endsWith("]") ? (
          <mark key={i} className="rounded bg-orange-500/30 px-0.5 text-zinc-100">
            {p.slice(1, -1)}
          </mark>
        ) : (
          p
        ),
      )}
    </span>
  );
}
