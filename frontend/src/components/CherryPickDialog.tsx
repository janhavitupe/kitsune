import { useEffect, useState } from "react";
import { api, type Commit } from "../api/client";

interface Props {
  source: Commit; // the older version the region comes from
  target: Commit; // the latest version it goes into
  label: string;
  onClose: () => void;
  onDone: (c: Commit) => void;
}

/** Preview, then confirm, bringing one region of an older version back into the latest one. */
export default function CherryPickDialog({ source, target, label, onClose, onDone }: Props) {
  const [loaded, setLoaded] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await api.cherryPick(target.id, source.id, label));
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/70 p-4" onClick={() => !busy && onClose()}>
      <div
        role="dialog"
        aria-label={`Bring back the ${label}`}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl rounded-lg border border-zinc-700 bg-zinc-900 p-5"
      >
        <h2 className="text-lg font-semibold">
          Bring back the <span className="text-orange-400">{label}</span> from v{source.seq}?
        </h2>
        <p className="mt-1 text-sm text-zinc-400">
          Everything else stays as it is in v{target.seq}. The result is saved as a new version on {target.branch}; nothing is
          overwritten.
        </p>

        <div className="mt-4 flex aspect-[4/3] items-center justify-center overflow-hidden rounded-md bg-zinc-950">
          {previewFailed ? (
            <p className="text-sm text-red-400">Couldn't build a preview.</p>
          ) : (
            <img
              src={api.cherryPickPreviewUrl(target.id, source.id, label)}
              alt="Preview of the result"
              className={loaded ? "max-h-full max-w-full object-contain" : "hidden"}
              onLoad={() => setLoaded(true)}
              onError={() => setPreviewFailed(true)}
            />
          )}
          {!loaded && !previewFailed && <p className="animate-pulse text-sm text-zinc-400">Building preview…</p>}
        </div>

        {error && <p className="mt-3 text-sm text-red-400">{error}</p>}

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} disabled={busy} className="rounded-md px-3 py-1.5 text-sm text-zinc-300 hover:bg-zinc-800">
            Cancel
          </button>
          <button
            onClick={confirm}
            disabled={busy}
            className="rounded-md bg-orange-600 px-4 py-1.5 text-sm font-medium hover:bg-orange-500 disabled:opacity-50"
          >
            {busy ? "Blending…" : `Bring back the ${label}`}
          </button>
        </div>
      </div>
    </div>
  );
}
