/** The Kitsune mark: a geometric fox head. Same shape as the favicon in index.html. */
export function FoxMark({ className = "size-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <path d="M3 3 L12 9 H20 L29 3 L27 15 L16 29 L5 15 Z" fill="#f97316" />
      <path d="M6 7 L10.5 10 L7 12.5 Z M26 7 L21.5 10 L25 12.5 Z" fill="#7c2d12" />
      <path d="M8 16 L16 21 L24 16 L16 29 Z" fill="#fff7ed" />
      <circle cx="16" cy="26.5" r="1.6" fill="#1c1917" />
    </svg>
  );
}

/** A grey placeholder block for loading states. */
export function Skeleton({ className }: { className: string }) {
  return <div className={`animate-pulse rounded-md bg-zinc-800/80 ${className}`} />;
}
