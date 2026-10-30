import { useState, type FormEvent } from "react";
import { api, assetUrl, type Branch, type Commit } from "../api/client";
import { commitTitle, timeAgo } from "../lib/format";
import NotesPanel from "./NotesPanel";
import StatusBadge from "./StatusBadge";

interface Props {
  commit: Commit;
  parent: Commit | undefined;
  branches: Branch[];
  onCompareWithParent: () => void;
  onPickSecond: () => void;
  onBranchCreated: (name: string) => void;
  onExplore: () => void;
  onNotesChanged: () => void;
  onDeleted: () => void;
}

export default function CommitDetail({
  commit, parent, branches, onCompareWithParent, onPickSecond, onBranchCreated, onExplore, onNotesChanged, onDeleted,
}: Props) {
  const [branching, setBranching] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const createBranch = async (e: FormEvent) => {
    e.preventDefault();
    if (branches.some((b) => b.name === name)) {
      setError(`Branch '${name}' already exists`);
      return;
    }
    try {
      await api.createBranch(commit.repo_id, name, commit.id);
      setBranching(false);
      setName("");
      setError(null);
      onBranchCreated(name);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  // Only the latest version of a branch can go; the server checks nothing else is built on it.
  const isTip = branches.some((b) => b.name === commit.branch && b.head_commit_id === commit.id);
  const remove = async () => {
    if (!window.confirm(`Delete v${commit.seq}? Its image and notes are removed for good.`)) return;
    try {
      await api.deleteCommit(commit.id);
      setError(null);
      onDeleted();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const retryAnalysis = async () => {
    try {
      await api.retryAnalysis(commit.id);
      setError(null);
      onNotesChanged(); // refreshes the graph, which starts polling until analysis finishes
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
      <div className="flex items-center justify-center rounded-md bg-zinc-900 p-2">
        <img
          src={assetUrl(commit.image_url)}
          alt={`Version ${commit.seq}`}
          className="max-h-[70vh] w-auto max-w-full object-contain"
        />
      </div>

      <aside className="space-y-4">
        <div>
          <p className="text-sm text-zinc-400">
            v{commit.seq} · {commit.branch} · {timeAgo(commit.created_at)}
          </p>
          <h2 className="mt-1 text-lg font-medium">{commitTitle(commit)}</h2>
          <div className="mt-1 flex items-center gap-2">
            <StatusBadge status={commit.analysis_status} />
            {commit.analysis_status === "failed" && (
              <button onClick={retryAnalysis} className="text-xs text-orange-400 hover:underline">
                Retry
              </button>
            )}
          </div>
          <p className="mt-2 text-xs text-zinc-500">
            {commit.width} × {commit.height}px
          </p>
        </div>

        <div className="flex flex-col gap-2">
          {parent && (
            <button onClick={onCompareWithParent} className="rounded-md border border-zinc-700 px-3 py-2 text-left text-sm hover:bg-zinc-900">
              Compare with previous (v{parent.seq})
            </button>
          )}
          <button onClick={onPickSecond} className="rounded-md border border-zinc-700 px-3 py-2 text-left text-sm hover:bg-zinc-900">
            Compare with another version…
          </button>

          {branching ? (
            <form onSubmit={createBranch} className="flex gap-2">
              <input
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value.replace(/\s+/g, "-"))}
                placeholder="dusk-palette"
                pattern="[A-Za-z0-9][A-Za-z0-9._/\-]{0,63}"
                title="Letters, numbers, dot, dash, underscore or slash"
                className="min-w-0 flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm outline-none focus:border-orange-500"
              />
              <button disabled={!name} className="rounded-md bg-orange-600 px-3 text-sm font-medium hover:bg-orange-500 disabled:opacity-50">
                Create
              </button>
            </form>
          ) : (
            <button onClick={() => setBranching(true)} className="rounded-md border border-zinc-700 px-3 py-2 text-left text-sm hover:bg-zinc-900">
              Branch from here
            </button>
          )}
          <button onClick={onExplore} className="rounded-md border border-zinc-700 px-3 py-2 text-left text-sm hover:bg-zinc-900">
            Explore palettes…
          </button>
          {commit.source_url && (
            <a href={assetUrl(commit.source_url)} className="rounded-md border border-zinc-700 px-3 py-2 text-sm hover:bg-zinc-900">
              Download with layers (.{commit.source_ext})
            </a>
          )}
          {isTip && (
            <button onClick={remove} className="rounded-md border border-red-900 px-3 py-2 text-left text-sm text-red-400 hover:bg-red-950">
              Delete this version
            </button>
          )}
          {error && <p className="text-sm text-red-400">{error}</p>}
        </div>

        <NotesPanel commitId={commit.id} onChanged={onNotesChanged} />
      </aside>
    </div>
  );
}
