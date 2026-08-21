import * as React from "react";
import { cn } from "@/lib/utils";

// Flat fill bounded by a single hairline border, deliberately no
// box-shadow -- panels should read as machined instrument-panel layers cut
// from the same slab, not "elevated" cards floating on a lighter canvas the
// way a generic Bootstrap-style dashboard looks.
export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("rounded-lg border border-border bg-card text-card-foreground", className)} {...props} />
  )
);
Card.displayName = "Card";

export const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => <div ref={ref} className={cn("flex flex-col gap-1 p-4", className)} {...props} />
);
CardHeader.displayName = "CardHeader";

// "Panel nameplate" label styling -- uppercase, tracked, the display face,
// muted color -- rather than a default-case bold sentence-style heading.
// Callers that genuinely need a prominent title (not a section label) can
// still override via className, same as before.
export const CardTitle = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h3
      ref={ref}
      className={cn("font-display text-xs font-semibold uppercase leading-none tracking-[0.08em] text-muted-foreground", className)}
      {...props}
    />
  )
);
CardTitle.displayName = "CardTitle";

export const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => <div ref={ref} className={cn("p-4 pt-0", className)} {...props} />
);
CardContent.displayName = "CardContent";
