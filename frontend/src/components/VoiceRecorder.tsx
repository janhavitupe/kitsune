import { useEffect, useRef, useState } from "react";
import { cx } from "../lib/format";

const MAX_SECONDS = 120;

interface Props {
  /** `heard` is the browser's own transcript (Chrome, Edge, Safari), sent as a fallback for Voice Transcribe. */
  onRecorded: (audio: Blob | null, heard: string) => void;
}

// The Web Speech API isn't in TypeScript's DOM types yet; this is the part we use.
interface Recognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((e: { results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
}
type RecognitionCtor = new () => Recognition;

function speechRecognition(): Recognition | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  if (!Ctor) return null;
  const r = new Ctor();
  r.continuous = true;
  r.interimResults = true;
  r.lang = navigator.language || "en-US";
  return r;
}

/** Record a voice note in the browser (MediaRecorder, webm/opus), capped at two minutes. */
export default function VoiceRecorder({ onRecorded }: Props) {
  const [state, setState] = useState<"idle" | "recording" | "done">("idle");
  const [seconds, setSeconds] = useState(0);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const recognition = useRef<Recognition | null>(null);
  const [heard, setHeard] = useState("");

  useEffect(() => () => {
    recorder.current?.stream.getTracks().forEach((t) => t.stop());
    recognition.current?.stop();
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
      let transcript = "";
      const speech = speechRecognition();
      if (speech) {
        speech.onresult = (e) => {
          transcript = Array.from(e.results, (r) => r[0].transcript).join(" ").replace(/\s+/g, " ").trim();
          setHeard(transcript);
        };
        speech.onerror = () => {}; // no transcript is fine; the recording is what matters
        try {
          speech.start();
          recognition.current = speech;
        } catch {
          recognition.current = null;
        }
      }
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        recognition.current?.stop();
        const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
        setUrl(URL.createObjectURL(blob));
        setState("done");
        // Recognition delivers its last words just after stop(), so read them a moment later.
        setTimeout(() => onRecorded(blob, transcript), 400);
      };
      recorder.current = rec;
      rec.start();
      setHeard("");
      setSeconds(0);
      setState("recording");
    } catch {
      setError("Microphone not available. You can attach an audio file instead.");
    }
  };

  const reset = () => {
    setUrl(null);
    setHeard("");
    setState("idle");
    onRecorded(null, "");
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
      {heard && (
        <p className="text-xs italic text-zinc-400" title="Your browser's transcript, used if Voice Transcribe is unavailable">
          Heard: “{heard}”
        </p>
      )}
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
