// Typed wrappers for the Kitsune backend. Shapes mirror backend/app/schemas.py.

const BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/$/, "");

export type AnalysisStatus = "pending" | "running" | "done" | "failed";

export interface Repo {
  id: number;
  name: string;
  created_at: string;
  private_mode: boolean;
}

export type AssistantEvent =
  | { type: "plan"; text: string }
  | { type: "tool_call"; step: number; name: string; arguments: Record<string, unknown> }
  | { type: "tool_result"; step: number; name: string; result?: Record<string, unknown>; error?: string }
  | { type: "final"; text: string; created: number[]; working_commit: number | null; branch: string | null }
  | { type: "error"; message: string };

export interface Story {
  markdown: string;
  source: "wonder" | "template";
}

export interface Branch {
  id: number;
  repo_id: number;
  name: string;
  head_commit_id: number | null;
  kind: string;
  created_at: string;
}

export interface RepoDetail extends Repo {
  branches: Branch[];
}

export interface Commit {
  id: number;
  repo_id: number;
  seq: number;
  branch_id: number;
  branch: string;
  parent_id: number | null;
  merge_parent_id: number | null;
  blob_sha: string;
  width: number;
  height: number;
  message: string | null;
  auto_message: string | null;
  origin: string;
  origin_meta: Record<string, unknown> | null;
  analysis_status: AnalysisStatus;
  note_count: number;
  created_at: string;
  image_url: string;
  thumb_url: string;
}

export interface ChangedRegion {
  label: string;
  source: string; // "sam-3.1" for named regions, "change" for position-named change areas
  region_id: number | null;
  changed_px: number;
  changed_ratio: number;
  image_share: number;
  bbox: [number, number, number, number]; // x, y, w, h as fractions of the image
  hints: string[];
  polygons: [number, number][][];
}

export interface Diff {
  id: number;
  from_commit: number;
  to_commit: number;
  summary: string;
  regions: ChangedRegion[];
  changed_fraction: number;
  resized: boolean;
  segmented: boolean;
  size: [number, number];
  change_mask_url: string;
}

export interface MergeChange {
  label: string;
  bbox: [number, number, number, number];
  hints: string[];
}

export interface MergeConflict extends MergeChange {
  index: number;
  target_labels: string[];
}

export interface MergePlan {
  id: number;
  status: "open" | "resolved" | "aborted";
  source: string;
  target: string;
  source_head: number;
  target_head: number;
  base: number;
  fast_forward: boolean;
  auto: MergeChange[];
  conflicts: MergeConflict[];
}

export type Side = "source" | "target";

export type NoteKind = "artist" | "client";

export interface Note {
  id: number;
  commit_id: number;
  kind: NoteKind;
  transcript: string | null;
  summary: string | null;
  audio_url: string | null;
  created_at: string;
}

export interface SearchResult {
  commit_id: number;
  seq: number;
  snippet: string;
  reason: string;
}

export interface SearchResponse {
  query: string;
  relation: string | null;
  parser: string;
  results: SearchResult[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Backend-relative URLs (image_url, thumb_url) need the API origin in production. */
export const assetUrl = (path: string) => BASE + path;

/** What to tell the artist for failures that aren't about their input. Null keeps the server's message. */
function friendly(status: number, retryAfter: string | null): string | null {
  if (status === 429) {
    const s = Number(retryAfter);
    return `That's a lot of requests at once. Try again in ${s > 0 ? `${s} seconds` : "a moment"}.`;
  }
  if (status === 502 || status === 503) return "The server is waking up or busy. Try again in a few seconds.";
  if (status === 504) return "Analysis is taking longer than usual. Try again in a moment.";
  if (status >= 500) return "Something went wrong on the server. Try again, and if it keeps happening, reload the page.";
  return null;
}

/** fetch, but a dropped connection becomes an ApiError with a readable message instead of "Failed to fetch". */
async function send(path: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(BASE + path, init);
  } catch {
    throw new ApiError(0, "Can't reach the Kitsune server. Check your connection and try again.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // keep statusText
    }
    throw new ApiError(res.status, friendly(res.status, res.headers.get("Retry-After")) ?? detail);
  }
  return res;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return (await send(path, init)).json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  listRepos: () => request<Repo[]>("/api/repos"),
  createRepo: (name: string) => request<RepoDetail>("/api/repos", json({ name })),
  getRepo: (id: number) => request<RepoDetail>(`/api/repos/${id}`),
  updateRepo: (id: number, patch: { name?: string; private_mode?: boolean }) =>
    request<RepoDetail>(`/api/repos/${id}`, { ...json(patch), method: "PATCH" }),
  story: (repoId: number) => request<Story>(`/api/repos/${repoId}/story`, { method: "POST" }),
  /** Run the studio assistant, calling onEvent for each server-sent event as it arrives. */
  runAssistant: async (repoId: number, ask: string, onEvent: (e: AssistantEvent) => void, startCommit?: number) => {
    const res = await send(`/api/repos/${repoId}/assistant`, json({ ask, start_commit: startCommit ?? null }));
    if (!res.body) throw new ApiError(res.status, "The assistant didn't send a response. Try again.");
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() ?? "";
      for (const chunk of chunks) {
        const line = chunk.split("\n").find((l) => l.startsWith("data: "));
        if (line) onEvent(JSON.parse(line.slice(6)) as AssistantEvent);
      }
    }
  },
  listCommits: (repoId: number) => request<Commit[]>(`/api/repos/${repoId}/commits`),
  retryAnalysis: (commitId: number) => request<Commit>(`/api/commits/${commitId}/analyze`, { method: "POST" }),
  createBranch: (repoId: number, name: string, fromCommit: number | null) =>
    request<Branch>(`/api/repos/${repoId}/branches`, json({ name, from_commit: fromCommit })),
  getDiff: (from: number, to: number) => request<Diff>(`/api/diff?from=${from}&to=${to}`),
  cherryPickPreviewUrl: (target: number, source: number, label: string) =>
    `${BASE}/api/commits/${target}/cherry-pick/preview?source=${source}&label=${encodeURIComponent(label)}`,
  cherryPick: (target: number, source: number, label: string) =>
    request<Commit>(`/api/commits/${target}/cherry-pick`, json({ source_commit: source, label })),
  planMerge: (repoId: number, source: string, target: string) =>
    request<MergePlan>(`/api/repos/${repoId}/merges`, json({ source, target })),
  resolveMerge: (mergeId: number, choices: Record<number, Side>) =>
    request<Commit>(`/api/merges/${mergeId}/resolve`, json({ choices })),
  abortMerge: (mergeId: number) => request<MergePlan>(`/api/merges/${mergeId}/abort`, { method: "POST" }),
  updateBranch: (branchId: number, patch: { name?: string; kind?: string }) =>
    request<Branch>(`/api/branches/${branchId}`, { ...json(patch), method: "PATCH" }),
  listNotes: (commitId: number) => request<Note[]>(`/api/commits/${commitId}/notes`),
  addNote: (commitId: number, kind: NoteKind, text: string, audio: Blob | null, audioName = "note.webm", heard = "") => {
    const form = new FormData();
    form.append("kind", kind);
    if (text.trim()) form.append("text", text.trim());
    if (audio) form.append("audio", audio, audioName);
    if (audio && heard.trim()) form.append("fallback_text", heard.trim());
    return request<Note>(`/api/commits/${commitId}/notes`, { method: "POST", body: form });
  },
  transcribeNote: (noteId: number) => request<Note>(`/api/notes/${noteId}/transcribe`, { method: "POST" }),
  deleteNote: async (noteId: number) => {
    await send(`/api/notes/${noteId}`, { method: "DELETE" });
  },
  search: (repoId: number, q: string) =>
    request<SearchResponse>(`/api/repos/${repoId}/search?q=${encodeURIComponent(q)}`),
  explore: (commitId: number, prompt: string) =>
    request<Commit[]>(`/api/commits/${commitId}/explore`, json({ prompt: prompt.trim() || null })),
  uploadCommit: (repoId: number, file: File, branch: string, message: string) => {
    const form = new FormData();
    form.append("image", file);
    form.append("branch", branch);
    if (message.trim()) form.append("message", message.trim());
    return request<Commit>(`/api/repos/${repoId}/commits`, { method: "POST", body: form });
  },
};
