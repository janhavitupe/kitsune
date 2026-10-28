import { useEffect, useState, type ReactNode } from "react";
import { api, assetUrl, type Commit, type Story } from "../api/client";

interface Props {
  repoId: number;
  commitsBySeq: Map<number, Commit>;
  onClose: () => void;
}

/** The history as a process breakdown: headings, paragraphs, quotes, lists, [v3] as thumbnails. */
export default function StoryView({ repoId, commitsBySeq, onClose }: Props) {
  const [story, setStory] = useState<Story | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api.story(repoId).then(setStory, (e: Error) => setError(e.message));
  }, [repoId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const copy = async () => {
    if (!story) return;
    try {
      await navigator.clipboard.writeText(story.markdown);
      setCopied(true);
    } catch {
      setError("Couldn't copy; select the text instead.");
    }
  };

  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <article
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 p-6"
        aria-label="Process story"
      >
        {!story && !error && <p className="animate-pulse text-zinc-400">Writing the story…</p>}
        {error && <p className="text-red-400">{error}</p>}
        {story && (
          <>
            <Markdown text={story.markdown} commitsBySeq={commitsBySeq} />
            <div className="mt-6 flex items-center justify-between border-t border-zinc-800 pt-4 text-sm">
              <span className="text-zinc-500">
                {story.source === "wonder" ? "Written by Muse Wonder from your history" : "Assembled from your history"}
              </span>
              <div className="flex gap-2">
                <button onClick={copy} className="rounded-md border border-zinc-700 px-3 py-1.5 hover:bg-zinc-800">
                  {copied ? "Copied" : "Copy markdown"}
                </button>
                <button onClick={onClose} className="rounded-md px-3 py-1.5 text-zinc-300 hover:bg-zinc-800">
                  Close
                </button>
              </div>
            </div>
          </>
        )}
      </article>
    </div>
  );
}

function Markdown({ text, commitsBySeq }: { text: string; commitsBySeq: Map<number, Commit> }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length) blocks.push(<ul key={blocks.length} className="my-2 list-disc space-y-1 pl-5">{list.map((l, i) => <li key={i}>{inline(l, commitsBySeq)}</li>)}</ul>);
    list = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    if (/^[-*] /.test(line)) {
      list.push(line.slice(2));
      continue;
    }
    flush();
    if (!line.trim()) continue;
    const k = blocks.length;
    if (line.startsWith("# ")) blocks.push(<h1 key={k} className="mb-3 text-2xl font-semibold">{inline(line.slice(2), commitsBySeq)}</h1>);
    else if (line.startsWith("## ")) blocks.push(<h2 key={k} className="mt-5 mb-2 text-lg font-semibold">{inline(line.slice(3), commitsBySeq)}</h2>);
    else if (line.startsWith("> ")) blocks.push(<blockquote key={k} className="my-2 border-l-2 border-sky-700 pl-3 text-zinc-300 italic">{inline(line.slice(2), commitsBySeq)}</blockquote>);
    else blocks.push(<p key={k} className="my-2 leading-relaxed text-zinc-200">{inline(line, commitsBySeq)}</p>);
  }
  flush();
  return <>{blocks}</>;
}

/** [v3] → a small thumbnail of version 3; **bold** kept. */
function inline(text: string, commitsBySeq: Map<number, Commit>): ReactNode[] {
  return text.split(/(\[v\d+\]|\*\*[^*]+\*\*)/g).map((part, i) => {
    const v = part.match(/^\[v(\d+)\]$/);
    if (v) {
      const c = commitsBySeq.get(Number(v[1]));
      return c ? (
        <span key={i} className="mx-0.5 inline-flex items-center gap-1 rounded bg-zinc-800 py-0.5 pr-1.5 pl-0.5 align-middle text-xs not-italic">
          <img src={assetUrl(c.thumb_url)} alt="" className="h-5 w-7 rounded-sm object-cover" />v{c.seq}
        </span>
      ) : (
        <span key={i}>{part}</span>
      );
    }
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    return <span key={i}>{part}</span>;
  });
}
