import type { ReactNode } from "react";
import guide from "../USER_GUIDE.md?raw";
import { FoxMark } from "../components/Logo";

const SERVER_PLACEHOLDER = "https://your-kitsune-server";
const SITE_PLACEHOLDER = "https://your-kitsune-site";

function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/).map((part, i) => {
    if (part.startsWith("**")) return <strong key={i} className="font-semibold text-zinc-100">{part.slice(2, -2)}</strong>;
    if (part.startsWith("`")) return <code key={i} className="rounded bg-zinc-800 px-1 py-0.5 text-sm text-orange-300">{part.slice(1, -1)}</code>;
    if (part.startsWith("*")) return <em key={i}>{part.slice(1, -1)}</em>;
    return part;
  });
}

function cells(row: string): string[] {
  return row.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
}

/** The guide's markdown: headings, paragraphs, lists, tables, code blocks and inline emphasis. */
function render(markdown: string): ReactNode[] {
  const lines = markdown.split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  const takeWhile = (test: (line: string) => boolean) => {
    const taken: string[] = [];
    while (i < lines.length && test(lines[i])) taken.push(lines[i++]);
    return taken;
  };

  while (i < lines.length) {
    const line = lines[i];
    const key = blocks.length;
    const heading = line.match(/^(#{1,3}) (.+)$/);
    if (!line.trim()) {
      i++;
    } else if (line.startsWith("```")) {
      i++;
      const code = takeWhile((l) => !l.startsWith("```"));
      i++;
      blocks.push(
        <pre key={key} className="mt-3 overflow-x-auto rounded-md border border-zinc-800 bg-zinc-900 p-3 text-sm text-zinc-200">
          {code.join("\n")}
        </pre>,
      );
    } else if (heading) {
      const [, level, text] = heading;
      if (level === "#") blocks.push(<h1 key={key} className="text-3xl font-semibold">{text}</h1>);
      else if (level === "##") blocks.push(<h2 key={key} id={slug(text)} className="mt-10 scroll-mt-4 border-b border-zinc-800 pb-2 text-2xl font-semibold">{text}</h2>);
      else blocks.push(<h3 key={key} className="mt-7 text-lg font-semibold">{text}</h3>);
      i++;
    } else if (line.startsWith("|")) {
      const [head, , ...rows] = takeWhile((l) => l.startsWith("|")).map(cells);
      blocks.push(
        <div key={key} className="mt-3 overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>{head.map((c, n) => <th key={n} className="border border-zinc-800 bg-zinc-900 px-3 py-2 text-left font-medium">{c}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((row, r) => (
                <tr key={r}>{row.map((c, n) => <td key={n} className="border border-zinc-800 px-3 py-2 align-top text-zinc-300">{inline(c)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
    } else if (/^\d+\. /.test(line)) {
      const items = takeWhile((l) => /^\d+\. /.test(l));
      blocks.push(
        <ol key={key} className="mt-3 list-decimal space-y-1 pl-6 text-zinc-300">
          {items.map((item, n) => <li key={n}>{inline(item.replace(/^\d+\. /, ""))}</li>)}
        </ol>,
      );
    } else if (line.startsWith("- ")) {
      const items = takeWhile((l) => l.startsWith("- "));
      blocks.push(
        <ul key={key} className="mt-3 list-disc space-y-1 pl-6 text-zinc-300">
          {items.map((item, n) => <li key={n}>{inline(item.slice(2))}</li>)}
        </ul>,
      );
    } else {
      blocks.push(<p key={key} className="mt-3 leading-relaxed text-zinc-300">{inline(takeWhile((l) => l.trim() !== "" && !/^(#|\||```)/.test(l)).join(" "))}</p>);
    }
  }
  return blocks;
}

/** How to use Kitsune, at ?guide. The commands show this site's own addresses when it's deployed. */
export default function GuidePage({ repoId }: { repoId: number | null }) {
  const server = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") || SERVER_PLACEHOLDER;
  const text = guide.replaceAll(SERVER_PLACEHOLDER, server).replaceAll(SITE_PLACEHOLDER, window.location.origin);
  const sections = [...text.matchAll(/^## (.+)$/gm)].map((m) => m[1]);

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      <a href={repoId === null ? window.location.pathname : `?repo=${repoId}`} className="inline-flex items-center gap-1.5 text-sm text-zinc-400 hover:text-orange-400">
        <FoxMark /> Back to Kitsune
      </a>
      <nav aria-label="Guide sections" className="mt-6 flex flex-wrap gap-2 text-sm">
        {sections.map((s) => (
          <a key={s} href={`#${slug(s)}`} className="rounded-md border border-zinc-800 px-2.5 py-1 text-zinc-300 hover:bg-zinc-900">
            {s}
          </a>
        ))}
      </nav>
      <article className="mt-8">{render(text)}</article>
    </main>
  );
}
