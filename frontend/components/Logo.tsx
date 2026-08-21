/**
 * The HORIZON GRID mark: an original, wholly-geometric triangulation motif --
 * a horizon line with two open "signal" nodes converging on one filled
 * "detection" node, literally depicting the tagline ("Every Signal. One
 * Operational Picture.") rather than just looking generically tactical. No
 * insignia, seal, shield, or existing company/military symbol of any kind.
 *
 * Built on lucide-react's own 24x24 grid/stroke-width convention so it sits
 * naturally beside lucide icons in the nav/header -- but every stroke uses
 * square caps and miter joins (lucide defaults to round) as a deliberate,
 * low-cost signature: same weight and grid, sharp instead of soft, reading
 * as engineered/precise rather than friendly.
 *
 * The peak/convergence node is the ONLY saturated-color element in the
 * entire mark (filled with --primary); every other stroke is currentColor
 * (foreground) -- echoing the palette's own "one live-signal accent against
 * an otherwise neutral instrument face" rule.
 *
 * Edge coordinates for the two connecting segments are computed geometrically
 * (circle-edge to circle-edge along the true center-to-center vector), not
 * eyeballed, so the lines visually terminate exactly at each node's outline
 * rather than overlapping or falling short.
 */
import { cn } from "@/lib/utils";

interface MarkProps {
  className?: string;
  /** Drops the left node + its connector for legibility at very small sizes
   * (16px and below) -- 3 primitives instead of 6: horizon line, one
   * diagonal rising to the peak, and the filled peak node. */
  favicon?: boolean;
}

export function HorizonGridMark({ className, favicon = false }: MarkProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("shrink-0", className)}
      role="img"
      aria-label="HORIZON GRID mark"
    >
      {/* Horizon line */}
      <line x1="2" y1="16" x2="22" y2="16" stroke="currentColor" strokeWidth={favicon ? 2.5 : 2} strokeLinecap="square" />
      {!favicon && (
        <>
          {/* Left signal node (open) */}
          <circle cx="5" cy="13" r="1.6" stroke="currentColor" strokeWidth="2" />
          {/* left-node edge -> peak-node edge */}
          <line x1="6.13" y1="11.87" x2="10.44" y2="7.56" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
          {/* Right signal node (open) */}
          <circle cx="19" cy="12" r="1.6" stroke="currentColor" strokeWidth="2" />
          {/* peak-node edge -> right-node edge */}
          <line x1="13.67" y1="7.43" x2="17.78" y2="10.96" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
        </>
      )}
      {favicon && (
        /* single diagonal rising to the peak, replacing both connectors */
        <line x1="7.5" y1="12.5" x2="10.44" y2="7.56" stroke="currentColor" strokeWidth="2.5" strokeLinecap="square" />
      )}
      {/* Peak / convergence node -- the one saturated element in the mark */}
      <circle cx="12" cy="6" r={favicon ? "2.4" : "2.2"} className="fill-primary" />
    </svg>
  );
}

/** Four independent L-shaped corner brackets -- the compact-lockup badge
 * frame, and reused directly as the app-wide focus/selected-state accent
 * (see globals.css / card components) so the logo and the chrome are
 * literally the same asset at different scales. */
export function CornerBracketFrame({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg" className={cn("shrink-0", className)} aria-hidden="true">
      <path d="M2 8 L2 2 L8 2" stroke="currentColor" strokeWidth="2" strokeLinecap="square" strokeLinejoin="miter" />
      <path d="M20 2 L26 2 L26 8" stroke="currentColor" strokeWidth="2" strokeLinecap="square" strokeLinejoin="miter" />
      <path d="M26 20 L26 26 L20 26" stroke="currentColor" strokeWidth="2" strokeLinecap="square" strokeLinejoin="miter" />
      <path d="M8 26 L2 26 L2 20" stroke="currentColor" strokeWidth="2" strokeLinecap="square" strokeLinejoin="miter" />
    </svg>
  );
}

interface LogoProps {
  size?: "full" | "compact" | "mark";
  className?: string;
  markClassName?: string;
}

/**
 * Full lockup: mark + "HORIZON GRID", monochrome wordmark (the mark already
 * carries the palette's one accent color, so keeping the wordmark itself
 * monochrome reads as more disciplined than a two-tone split).
 * Compact lockup: mark inside a corner-bracket badge + "HG", for collapsed
 * headers/mobile.
 * Mark: the icon alone, for tight inline contexts (favicon, loading states).
 */
export function Logo({ size = "full", className, markClassName }: LogoProps) {
  if (size === "mark") {
    return <HorizonGridMark className={cn("h-6 w-6 text-foreground", markClassName)} />;
  }

  if (size === "compact") {
    return (
      <div className={cn("flex items-center gap-2", className)}>
        <span className="relative inline-flex h-8 w-8 items-center justify-center text-foreground">
          <CornerBracketFrame className="absolute inset-0 h-8 w-8 text-border" />
          <HorizonGridMark className="h-5 w-5" />
        </span>
        <span className="font-display text-base font-semibold uppercase tracking-[0.08em] text-foreground">HG</span>
      </div>
    );
  }

  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <HorizonGridMark className={cn("h-7 w-7 text-foreground", markClassName)} />
      <span className="font-display text-lg font-semibold uppercase tracking-[0.08em] text-foreground">
        Horizon<span className="ml-1.5">Grid</span>
      </span>
    </div>
  );
}
