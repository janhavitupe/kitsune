import { useEffect, useState, type FormEvent } from "react";
import { api, assetUrl, type Note, type NoteKind } from "../api/client";
import { cx, timeAgo } from "../lib/format";
import VoiceRecorder from "./VoiceRecorder";

interface Props {
  commitId: number;
  onChanged: () => void; // note counts in the timeline need a refresh
}

/** Notes pinned to a version: the artist's own reasons, or a client's feedback. Typed or recorded. */
export default function NotesPanel({ commitId, onChanged }: Props) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [kind, setKind] = useState<NoteKind>("artist");
  const [text, setText] = useState("");
  const [audio, setAudio] = useState<Blob | null>(null);
  const [audioName, setAudioName] = useState("note.webm");
  const [recorderKey, setRecorderKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.listNotes(commitId).then((n) => live && setNotes(n), () => {});
    return () => {
      live = false;
    };
  }, [commitId]);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const note = await api.addNote(commitId, kind, text, audio, audioName);
      setNotes((n) => [...n, note]);
      setText("");
      setAudio(null);
      setRecorderKey((k) => k + 1);
      onChanged();
    } catch (err) {
      setError((err as Error).message);
    }
    setBusy(false);
  };

  const retry = async (id: number) => {
    try {
      const note = await api.transcribeNote(id);
      setNotes((n) => n.map((x) => (x.id === id ? note : x)));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const remove = async (id: number) => {
    await api.deleteNote(id).catch(() => {});
    setNotes((n) => n.filter((x) => x.id !== id));
    onChanged();
  };

  return (
    <section className="space-y-3">
      <h3 className="text-xs font-medium tracking-wide text-zinc-500 uppercase">Notes</h3>

      {notes.length === 0 && <p className="text-sm text-zinc-500">Why did this change? Record or type a note.</p>}
      <ul className="space-y-2">
        {notes.map((n) => (
          <li key={n.id} className={cx("rounded-md border p-2.5 text-sm", n.kind === "client" ? "border-sky-900 bg-sky-950/40" : "border-zinc-800")}>
            <div className="flex items-center justify-between text-xs text-zinc-400">
              <span>{n.kind === "client" ? "Client feedback" : "Note"} · {timeAgo(n.created_at)}</span>
              <button onClick={() => remove(n.id)} className="hover:text-zinc-200" aria-label="Delete note">
                ✕
              </button>
            </div>
            {n.summary && <p className="mt-1 whitespace-pre-line font-medium">{n.summary}</p>}
            {n.transcript ? (
              <p className={cx("mt-1 whitespace-pre-line", n.summary && "text-zinc-400")}>{n.transcript}</p>
            ) : (
              <p className="mt-1 text-zinc-500">
                Not transcribed yet.{" "}
                <button onClick={() => retry(n.id)} className="text-orange-400 hover:underline">
                  Try again
                </button>
              </p>
            )}
            {n.audio_url && <audio src={assetUrl(n.audio_url)} controls className="mt-2 h-8 w-full" />}
          </li>
        ))}
      </ul>

      <form onSubmit={save} className="space-y-2 rounded-md border border-zinc-800 p-2.5">
        <div className="flex rounded-md border border-zinc-700 p-0.5 text-xs" role="radiogroup" aria-label="Who is this from">
          {(["artist", "client"] as const).map((k) => (
            <button
              key={k}
              type="button"
              role="radio"
              aria-checked={kind === k}
              onClick={() => setKind(k)}
              className={cx("flex-1 rounded px-2 py-1", kind === k ? "bg-zinc-700" : "text-zinc-400 hover:text-zinc-200")}
            >
              {k === "artist" ? "My note" : "Client feedback"}
            </button>
          ))}
        </div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={2}
          placeholder={kind === "client" ? "Paste or type what the client asked for" : "Changed the sky because…"}
          className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm outline-none focus:border-orange-500"
        />
        <VoiceRecorder key={recorderKey} onRecorded={(b) => (setAudio(b), setAudioName("note.webm"))} />
        <label className="block text-xs text-zinc-400">
          or attach a voice message:{" "}
          <input
            type="file"
            accept="audio/*"
            className="text-xs"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setAudio(f);
              if (f) setAudioName(f.name);
            }}
          />
        </label>
        {error && <p className="text-xs text-red-400">{error}</p>}
        <button
          disabled={busy || (!text.trim() && !audio)}
          className="rounded-md bg-orange-600 px-3 py-1.5 text-sm font-medium hover:bg-orange-500 disabled:opacity-50"
        >
          {busy ? (audio ? "Transcribing…" : "Saving…") : "Pin note"}
        </button>
      </form>
    </section>
  );
}
