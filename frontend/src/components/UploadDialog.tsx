import { useEffect, useState, type DragEvent, type FormEvent } from "react";
import { api, type Commit } from "../api/client";
import { cx } from "../lib/format";

interface Props {
  repoId: number;
  branch: string;
  onClose: () => void;
  onUploaded: (c: Commit) => void;
}

const ACCEPT = "image/png,image/jpeg";

export default function UploadDialog({ repoId, branch, onClose, onUploaded }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) setFile(f);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      onUploaded(await api.uploadCommit(repoId, file, branch, message));
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/70 p-4" onClick={() => !busy && onClose()}>
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-lg rounded-lg border border-zinc-700 bg-zinc-900 p-5"
        aria-label="Upload a version"
      >
        <h2 className="text-lg font-semibold">
          Upload a version to <span className="text-orange-400">{branch}</span>
        </h2>

        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cx(
            "mt-4 flex h-56 cursor-pointer items-center justify-center overflow-hidden rounded-md border-2 border-dashed",
            dragging ? "border-orange-500 bg-orange-500/10" : "border-zinc-700 hover:border-zinc-500",
          )}
        >
          {preview ? (
            <img src={preview} alt="Selected file" className="h-full w-full object-contain" />
          ) : (
            <span className="px-4 text-center text-sm text-zinc-400">
              Drop a PNG or JPG here, or click to choose
              <br />
              <span className="text-zinc-500">Flatten PSD files to PNG first</span>
            </span>
          )}
          <input type="file" accept={ACCEPT} className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>

        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="What changed? (optional, Kitsune can write this for you)"
          className="mt-4 w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-orange-500"
        />

        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} disabled={busy} className="rounded-md px-3 py-1.5 text-sm text-zinc-300 hover:bg-zinc-800">
            Cancel
          </button>
          <button
            disabled={!file || busy}
            className="rounded-md bg-orange-600 px-4 py-1.5 text-sm font-medium hover:bg-orange-500 disabled:opacity-50"
          >
            {busy ? "Saving…" : "Save version"}
          </button>
        </div>
      </form>
    </div>
  );
}
