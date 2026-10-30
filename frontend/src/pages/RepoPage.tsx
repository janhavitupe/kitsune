import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Commit, type RepoDetail } from "../api/client";
import AssistantPanel from "../components/AssistantPanel";
import CommitDetail from "../components/CommitDetail";
import CompareView from "../components/CompareView";
import ExploreDialog from "../components/ExploreDialog";
import { FoxMark, Skeleton } from "../components/Logo";
import MergeDialog from "../components/MergeDialog";
import SearchBar from "../components/SearchBar";
import StoryView from "../components/StoryView";
import Timeline from "../components/Timeline";
import UploadDialog from "../components/UploadDialog";
import { cx } from "../lib/format";

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
  const [exploring, setExploring] = useState<Commit | null>(null);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [storyOpen, setStoryOpen] = useState(false);
  const [found, setFound] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);
  const timeline = useRef<HTMLElement>(null);

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
        <div className="mt-4 flex gap-4">
          <button onClick={refresh} className="rounded-md bg-orange-600 px-3 py-1.5 text-sm font-medium hover:bg-orange-500">
            Try again
          </button>
          <button onClick={onBack} className="text-orange-400 hover:underline">
            ← Back to pieces
          </button>
        </div>
      </main>
    );
  }
  if (!repo) {
    return (
      <div className="flex min-h-screen flex-col" aria-label="Loading piece">
        <header className="flex items-center gap-3 border-b border-zinc-800 px-4 py-3">
          <FoxMark />
          <Skeleton className="h-5 w-40" />
          <Skeleton className="ml-auto h-8 w-32" />
        </header>
        <div className="flex gap-5 overflow-hidden border-b border-zinc-800 py-4 pl-28">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-[108px] w-[116px] shrink-0" />
          ))}
        </div>
        <Skeleton className="m-4 h-[50vh]" />
      </div>
    );
  }

  const [a, b] = [...picked].sort((x, y) => x.seq - y.seq);
  const isTip = (c: Commit) => repo?.branches.some((br) => br.name === c.branch && br.head_commit_id === c.id) ?? false;
  // Discarded explore branches are hidden, not deleted (history is append-only).
  const branches = repo.branches.filter((br) => br.kind !== "discarded");
  const shown = new Set(branches.map((br) => br.id));
  const visible = commits.filter((c) => shown.has(c.branch_id));
  const heads = new Map(branches.map((br) => [br.name, br.head_commit_id]));

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-zinc-800 px-4 py-3">
        <button onClick={onBack} className="text-lg font-semibold hover:text-orange-400" title="All pieces">
          <span className="flex items-center gap-1.5">
            <FoxMark /> Kitsune
          </span>
        </button>
        <span className="text-zinc-600">/</span>
        <h1 className="truncate font-medium">{repo.name}</h1>
        <label
          className="flex cursor-pointer items-center gap-1.5 text-xs text-zinc-400"
          title="Captions and search run on self-hosted open weights, never the hosted API. Segmentation still uses the hosted API."
        >
          <input
            type="checkbox"
            checked={repo.private_mode}
            onChange={async (e) => setRepo(await api.updateRepo(repo.id, { private_mode: e.target.checked }))}
            className="accent-orange-500"
          />
          Private
        </label>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {commits.length > 0 && (
            <>
              <button onClick={() => setStoryOpen(true)} className="rounded-md border border-zinc-700 px-3 py-1.5 text-sm hover:bg-zinc-900">
                Story
              </button>
              <button onClick={() => setAssistantOpen(true)} className="rounded-md border border-zinc-700 px-3 py-1.5 text-sm hover:bg-zinc-900">
                Assistant
              </button>
            </>
          )}
          <label className="text-sm text-zinc-400" htmlFor="branch">
            Branch
          </label>
          <select
            id="branch"
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            className="max-w-48 truncate rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm"
          >
            {branches.map((br) => (
              <option key={br.id} value={br.name}>
                {br.name}
              </option>
            ))}
          </select>
          {branches.filter((br) => br.head_commit_id !== null).length > 1 && (
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

      <section ref={timeline} className="border-b border-zinc-800">
        {commits.length === 0 ? (
          <div className="px-4 py-16 text-center text-zinc-500">
            <p>No versions yet.</p>
            <button onClick={() => setUploadOpen(true)} className="mt-3 text-orange-400 hover:underline">
              Upload your first version
            </button>
          </div>
        ) : (
          <>
            <SearchBar repoId={repo.id} onResults={setFound} onPick={(id) => setSelected([id])} />
            <Timeline
              branches={branches}
              commits={visible}
              selected={selected}
              highlighted={found}
              currentBranchHead={heads.get(branch) ?? null}
              onSelect={select}
            />
            <p className={cx("px-4 pb-3 text-xs", pickingSecond ? "font-medium text-orange-400" : "text-zinc-500")}>
              {pickingSecond
                ? "Pick a second version to compare."
                : window.matchMedia("(pointer: coarse)").matches
                  ? "Tap a version to view it, then use Compare with another version."
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
            aIsHead={isTip(a)}
            bIsHead={isTip(b)}
            onClose={() => setSelected([b.id])}
            onCommitted={onCherryPicked}
          />
        ) : a ? (
          <CommitDetail
            commit={a}
            parent={a.parent_id ? byId.get(a.parent_id) : undefined}
            branches={repo.branches}
            onCompareWithParent={() => a.parent_id && setSelected([a.parent_id, a.id])}
            onPickSecond={() => {
              setPickingSecond(true);
              timeline.current?.scrollIntoView(); // on a phone the timeline is far above this button
            }}
            onBranchCreated={onBranchCreated}
            onExplore={() => setExploring(a)}
            onNotesChanged={refresh}
            onDeleted={() => {
              setSelected(a.parent_id ? [a.parent_id] : []);
              refresh();
            }}
          />
        ) : null}
      </main>

      {assistantOpen && (
        <AssistantPanel
          repoId={repo.id}
          onClose={() => setAssistantOpen(false)}
          onChanged={refresh}
          working={picked[picked.length - 1]}
          onOpen={(id) => {
            const c = byId.get(id);
            if (c) setBranch(c.branch);
            setSelected(c?.parent_id ? [c.parent_id, id] : [id]);
          }}
        />
      )}

      {storyOpen && (
        <StoryView repoId={repo.id} commitsBySeq={new Map(commits.map((c) => [c.seq, c]))} onClose={() => setStoryOpen(false)} />
      )}

      {exploring && (
        <ExploreDialog commit={exploring} branches={repo.branches} onClose={() => setExploring(null)} onChanged={refresh} />
      )}

      {mergeOpen && (
        <MergeDialog
          repoId={repo.id}
          branches={branches}
          commitsById={byId}
          defaultSource={branch !== "main" ? branch : (branches.find((br) => br.name !== "main")?.name ?? "main")}
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
