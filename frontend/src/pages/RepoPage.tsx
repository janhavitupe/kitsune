import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Commit, type RepoDetail } from "../api/client";
import CommitDetail from "../components/CommitDetail";
import CompareView from "../components/CompareView";
import MergeDialog from "../components/MergeDialog";
import Timeline from "../components/Timeline";
import UploadDialog from "../components/UploadDialog";

interface Props {
  repoId: number;
  onBack: () => void;
}

/** The selection lives in the URL (&sel=3,7) so a compare view can be reloaded or shared. */
function readSelection(): number[] {
  const raw = new URLSearchParams(window.location.search).get("sel") ?? "";
  return raw.split(",").map(Number).filter((n) => Number.isInteger(n) && n > 0).slice(0, 2);
}

export default function RepoPage({ repoId, onBack }: Props) {
  const [repo, setRepo] = useState<RepoDetail | null>(null);
  const [commits, setCommits] = useState<Commit[]>([]);
  const [branch, setBranch] = useState("main");
  const [selected, setSelected] = useState<number[]>(readSelection);
  const [pickingSecond, setPickingSecond] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [r, c] = await Promise.all([api.getRepo(repoId), api.listCommits(repoId)]);
      setRepo(r);
      setCommits(c);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [repoId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (selected.length) params.set("sel", selected.join(","));
    else params.delete("sel");
    window.history.replaceState(null, "", `?${params}`);
  }, [selected]);

  // Poll while any commit is still being analyzed.
  const analyzing = commits.some((c) => c.analysis_status === "pending" || c.analysis_status === "running");
  useEffect(() => {
    if (!analyzing) return;
    const t = setTimeout(refresh, 2000);
    return () => clearTimeout(t);
  }, [analyzing, commits, refresh]);

  const byId = useMemo(() => new Map(commits.map((c) => [c.id, c])), [commits]);
  const picked = selected.map((id) => byId.get(id)).filter((c): c is Commit => !!c);

  const select = (id: number, additive: boolean) => {
    if (additive || pickingSecond) {
      setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id].slice(-2)));
      setPickingSecond(false);
    } else {
      setSelected((s) => (s.length === 1 && s[0] === id ? [] : [id]));
    }
  };

  const onUploaded = async (c: Commit) => {
    setUploadOpen(false);
    await refresh();
    setSelected([c.id]);
  };

  // Show what the cherry-pick did: the version it went into against the new one.
  const onCherryPicked = async (c: Commit) => {
    await refresh();
    if (c.parent_id) setSelected([c.parent_id, c.id]);
  };

  // Show the merge result against the version it merged into, on the receiving branch.
  const onMerged = async (c: Commit) => {
    setMergeOpen(false);
    await refresh();
    setBranch(c.branch);
    if (c.parent_id) setSelected([c.parent_id, c.id]);
  };

  const onBranchCreated = async (name: string) => {
    await refresh();
    setBranch(name);
  };

  if (error && !repo) {
    return (
      <main className="p-6">
        <p className="text-red-400">{error}</p>
        <button onClick={onBack} className="mt-4 text-orange-400 hover:underline">
          ← Back to pieces
        </button>
      </main>
    );
  }
  if (!repo) return <main className="p-6 text-zinc-500">Loading…</main>;

  const [a, b] = [...picked].sort((x, y) => x.seq - y.seq);
  const heads = new Map(repo.branches.map((br) => [br.name, br.head_commit_id]));

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-zinc-800 px-4 py-3">
        <button onClick={onBack} className="text-lg font-semibold hover:text-orange-400" title="All pieces">
          <span aria-hidden>🦊</span> Kitsune
        </button>
        <span className="text-zinc-600">/</span>
        <h1 className="truncate font-medium">{repo.name}</h1>
        <div className="ml-auto flex items-center gap-2">
          <label className="text-sm text-zinc-400" htmlFor="branch">
            Branch
          </label>
          <select
            id="branch"
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            className="rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm"
          >
            {repo.branches.map((br) => (
              <option key={br.id} value={br.name}>
                {br.name}
              </option>
            ))}
          </select>
          {repo.branches.filter((br) => br.head_commit_id !== null).length > 1 && (
            <button onClick={() => setMergeOpen(true)} className="rounded-md border border-zinc-700 px-3 py-1.5 text-sm hover:bg-zinc-900">
              Merge…
            </button>
          )}
          <button onClick={() => setUploadOpen(true)} className="rounded-md bg-orange-600 px-3 py-1.5 text-sm font-medium hover:bg-orange-500">
            Upload version
          </button>
        </div>
      </header>

      {error && <p className="bg-red-950 px-4 py-2 text-sm text-red-300">{error}</p>}

      <section className="border-b border-zinc-800">
        {commits.length === 0 ? (
          <div className="px-4 py-16 text-center text-zinc-500">
            <p>No versions yet.</p>
            <button onClick={() => setUploadOpen(true)} className="mt-3 text-orange-400 hover:underline">
              Upload your first version
            </button>
          </div>
        ) : (
          <>
            <Timeline
              branches={repo.branches}
              commits={commits}
              selected={selected}
              currentBranchHead={heads.get(branch) ?? null}
              onSelect={select}
            />
            <p className="px-4 pb-3 text-xs text-zinc-500">
              {pickingSecond
                ? "Pick a second version to compare."
                : "Click a version to view it. Shift-click a second version to compare."}
            </p>
          </>
        )}
      </section>

      <main className="flex-1 p-4">
        {a && b ? (
          <CompareView
            a={a}
            b={b}
            bIsHead={repo.branches.some((br) => br.head_commit_id === b.id)}
            onClose={() => setSelected([b.id])}
            onCommitted={onCherryPicked}
          />
        ) : a ? (
          <CommitDetail
            commit={a}
            parent={a.parent_id ? byId.get(a.parent_id) : undefined}
            branches={repo.branches}
            onCompareWithParent={() => a.parent_id && setSelected([a.parent_id, a.id])}
            onPickSecond={() => setPickingSecond(true)}
            onBranchCreated={onBranchCreated}
          />
        ) : null}
      </main>

      {mergeOpen && (
        <MergeDialog
          repoId={repo.id}
          branches={repo.branches}
          commitsById={byId}
          defaultSource={branch !== "main" ? branch : (repo.branches.find((br) => br.name !== "main")?.name ?? "main")}
          onClose={() => setMergeOpen(false)}
          onMerged={onMerged}
        />
      )}

      {uploadOpen && (
        <UploadDialog repoId={repo.id} branch={branch} onClose={() => setUploadOpen(false)} onUploaded={onUploaded} />
      )}
    </div>
  );
}
