import { useEffect, useRef, useState } from "react";
import { cx } from "../lib/format";

const MAX_SECONDS = 120;

interface Props {
  onRecorded: (audio: Blob | null) => void;
}

/** Record a voice note in the browser (MediaRecorder, webm/opus), capped at two minutes. */
export default function VoiceRecorder({ onRecorded }: Props) {
  const [state, setState] = useState<"idle" | "recording" | "done">("idle");
  const [seconds, setSeconds] = useState(0);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);

  useEffect(() => () => {
    recorder.current?.stream.getTracks().forEach((t) => t.stop());
    if (url) URL.revokeObjectURL(url);
  }, [url]);

  useEffect(() => {
    if (state !== "recording") return;
    const t = setInterval(() => {
      setSeconds((s) => {
        if (s + 1 >= MAX_SECONDS) recorder.current?.stop();
        return s + 1;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [state]);

  const start = async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
        setUrl(URL.createObjectURL(blob));
        setState("done");
        onRecorded(blob);
      };
      recorder.current = rec;
      rec.start();
      setSeconds(0);
      setState("recording");
    } catch {
      setError("Microphone not available. You can attach an audio file instead.");
    }
  };

  const reset = () => {
    setUrl(null);
    setState("idle");
    onRecorded(null);
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        {state === "recording" ? (
          <button
            type="button"
            onClick={() => recorder.current?.stop()}
            className="flex items-center gap-2 rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium hover:bg-red-500"
          >
            <span className="size-2 animate-pulse rounded-full bg-white" /> Stop · {seconds}s
          </button>
        ) : (
          <button
            type="button"
            onClick={state === "done" ? reset : start}
            className={cx(
              "flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm",
              "border-zinc-700 hover:bg-zinc-800",
            )}
          >
            <MicIcon /> {state === "done" ? "Discard recording" : "Record"}
          </button>
        )}
      </div>
      {url && <audio src={url} controls className="h-8 w-full" />}
      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}

export function MicIcon({ className = "size-3.5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" className={className} aria-hidden>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  );
}
