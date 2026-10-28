// Typed wrappers for the Kitsune backend. Shapes mirror backend/app/schemas.py.

const BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/$/, "");

export type AnalysisStatus = "pending" | "running" | "done" | "failed";

export interface Repo {
  id: number;
  name: string;
  created_at: string;
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
  created_at: string;
  image_url: string;
  thumb_url: string;
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      // keep statusText
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
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
  listCommits: (repoId: number) => request<Commit[]>(`/api/repos/${repoId}/commits`),
  createBranch: (repoId: number, name: string, fromCommit: number | null) =>
    request<Branch>(`/api/repos/${repoId}/branches`, json({ name, from_commit: fromCommit })),
  uploadCommit: (repoId: number, file: File, branch: string, message: string) => {
    const form = new FormData();
    form.append("image", file);
    form.append("branch", branch);
    if (message.trim()) form.append("message", message.trim());
    return request<Commit>(`/api/repos/${repoId}/commits`, { method: "POST", body: form });
  },
};
