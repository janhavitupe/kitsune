import { useEffect, useState, type FormEvent } from "react";
import { api, type Repo } from "../api/client";
import { FoxMark, Skeleton } from "../components/Logo";
import { timeAgo } from "../lib/format";

export default function RepoPicker({ onOpen }: { onOpen: (id: number) => void }) {
  const [repos, setRepos] = useState<Repo[] | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setError(null);
    api.listRepos().then(setRepos, (e: Error) => setError(e.message));
  };
  useEffect(load, []);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      const repo = await api.createRepo(name.trim());
      onOpen(repo.id);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <main className="mx-auto max-w-xl px-4 py-12">
      <h1 className="flex items-center gap-2 text-3xl font-semibold">
        <FoxMark className="size-9" /> Kitsune
      </h1>
      <p className="mt-1 text-zinc-400">Version control for digital artists.</p>

      <form onSubmit={create} className="mt-8 flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New piece, e.g. forest girl"
          maxLength={100}
          className="min-w-0 flex-1 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 outline-none focus:border-orange-500"
        />
        <button className="rounded-md bg-orange-600 px-4 py-2 font-medium hover:bg-orange-500 disabled:opacity-50" disabled={!name.trim()}>
          Create
        </button>
      </form>

      {error && (
        <p className="mt-4 text-sm text-red-400">
          {error}{" "}
          {repos === null && (
            <button type="button" onClick={load} className="text-orange-400 hover:underline">
              Try again
            </button>
          )}
        </p>
      )}

      <h2 className="mt-10 text-sm font-medium uppercase tracking-wide text-zinc-500">Your pieces</h2>
      {repos === null && !error && (
        <div className="mt-3 space-y-2" aria-label="Loading pieces">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
      )}
      {repos?.length === 0 && <p className="mt-3 text-zinc-500">Nothing yet. Create your first piece above.</p>}
      <ul className={repos?.length ? "mt-3 divide-y divide-zinc-800 rounded-md border border-zinc-800" : "hidden"}>
        {repos?.map((r) => (
          <li key={r.id}>
            <button onClick={() => onOpen(r.id)} className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-zinc-900">
              <span>{r.name}</span>
              <span className="text-sm text-zinc-500">{timeAgo(r.created_at)}</span>
            </button>
          </li>
        ))}
      </ul>
    </main>
  );
}
