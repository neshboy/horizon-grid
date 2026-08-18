"use client";

/**
 * Persistent attribution/contact bar rendered on every page (see
 * app/layout.tsx). Placed in normal document flow at the very top of the
 * body -- not fixed/floating -- so it's always the first thing visible on
 * load, with zero risk of overlapping WorkspaceNav's own top-right nav
 * items (Administration etc.) on the 9 pages that render that header.
 */

import { Linkedin, Mail, Heart } from "lucide-react";

const LINKEDIN_URL = "https://www.linkedin.com/in/haneswaran-sundran-3a831396/";
const CONTACT_EMAIL = "souljaboyz57@gmail.com";
const PAYPAL_DONATE_URL = `https://www.paypal.com/donate/?business=${encodeURIComponent(
  "soulja_boyz57@yahoo.com"
)}&currency_code=USD`;

const linkClass =
  "inline-flex items-center gap-1.5 rounded-md border border-primary/40 bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/20";

export function CreditFooter() {
  return (
    <div className="flex w-full items-center justify-center gap-3 border-b border-border bg-card py-1.5">
      <span className="text-xs text-muted-foreground">Built by NeshX</span>
      <a href={LINKEDIN_URL} target="_blank" rel="noopener noreferrer" className={linkClass} title="Connect on LinkedIn">
        <Linkedin className="h-3.5 w-3.5" aria-hidden="true" />
        LinkedIn
      </a>
      <a href={`mailto:${CONTACT_EMAIL}`} className={linkClass} title="Contact via email">
        <Mail className="h-3.5 w-3.5" aria-hidden="true" />
        Contact
      </a>
      <a
        href={PAYPAL_DONATE_URL}
        target="_blank"
        rel="noopener noreferrer"
        className={linkClass}
        title="Support this project via PayPal"
      >
        <Heart className="h-3.5 w-3.5" aria-hidden="true" />
        Donate
      </a>
    </div>
  );
}
