import { assetUrl, type Diff } from "../api/client";

export type OverlayMode = "regions" | "mask" | "off";

interface Props {
  diff: Diff | null;
  mode: OverlayMode;
  focus: number | null; // index into diff.regions
}

/**
 * Drawn over the newer image. Coordinates are fractions of the image, so a 0..1 viewBox stretched
 * over the image box lines up at any zoom. Never takes pointer events: the slider and pan below it
 * keep working.
 */
export default function RegionOverlay({ diff, mode, focus }: Props) {
  if (!diff || mode === "off") return null;

  if (mode === "mask") {
    return (
      <img
        src={assetUrl(diff.change_mask_url)}
        alt=""
        className="pointer-events-none absolute inset-0 h-full w-full"
        draggable={false}
      />
    );
  }

  const focused = focus === null ? null : diff.regions[focus];
  return (
    <div className="pointer-events-none absolute inset-0">
      <svg viewBox="0 0 1 1" preserveAspectRatio="none" className="h-full w-full" aria-hidden>
        {diff.regions.map((r, i) =>
          r.polygons.map((poly, j) => (
            <polygon
              key={`${i}-${j}`}
              points={poly.map(([x, y]) => `${x},${y}`).join(" ")}
              vectorEffect="non-scaling-stroke"
              strokeWidth={i === focus ? 3 : 1.5}
              strokeLinejoin="round"
              className={
                i === focus
                  ? "fill-orange-500/30 stroke-orange-400"
                  : focus === null
                    ? "fill-orange-500/12 stroke-orange-400"
                    : "fill-orange-500/5 stroke-orange-400/30"
              }
            />
          )),
        )}
      </svg>
      {focused && (
        <span
          className="absolute -translate-y-full rounded bg-orange-600 px-1.5 py-0.5 text-xs font-medium whitespace-nowrap text-white shadow"
          style={{ left: `${focused.bbox[0] * 100}%`, top: `${focused.bbox[1] * 100}%` }}
        >
          {focused.label}
        </span>
      )}
    </div>
  );
}
