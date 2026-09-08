"use client";

/**
 * Global workspace nav -- grouped per the HORIZON GRID nav-reorg:
 *   COMMAND        -> Dashboard (/dashboard)
 *   INTELLIGENCE   -> Basket (/basket) -- "Investigate" itself has no link
 *                     here on purpose: it's the search bar (TopSearchBar),
 *                     rendered in the header right next to this nav, not a
 *                     nav-bar destination.
 *   ANALYSIS       -> Cases (/cases)
 *   OPERATIONS     -> Provider Health (/dashboard/provider-health) -- a
 *                     distinct route from Dashboard; the two must not be
 *                     conflated into one link or one active-state match.
 *   ADMINISTRATION -> Providers (/providers) + Administration (/admin), both
 *                     gated on isAdmin. Every /providers data call
 *                     (listAIProviders/listIOCProviders/getAuditLog) is
 *                     server-side gated on admin-only permissions
 *                     (provider:manage / audit:read), so the whole group is
 *                     hidden rather than showing a link a non-admin would
 *                     land on with a silently empty page. This group renders
 *                     as an expandable menu so the two links don't have to
 *                     compete for space under one caption.
 *
 * Most groups have exactly one real destination, so they render as a small
 * uppercase caption above a single pill link rather than a dropdown --
 * a dropdown-per-group would be overkill for one item.
 *
 * Active-state matching: pathname === href or a sub-route of it (e.g.
 * /cases/[id] under /cases). /dashboard and /dashboard/provider-health share
 * a prefix, so the *longest* matching href wins -- otherwise visiting
 * provider-health would also light up Dashboard/COMMAND.
 *
 * /lookup/* has no exact link here (see INTELLIGENCE above), which would
 * otherwise leave the whole nav looking inactive while investigating. Since
 * Investigate conceptually lives in INTELLIGENCE alongside Basket, the
 * INTELLIGENCE caption (only the caption, not the Basket pill itself) lights
 * up on /lookup/* too -- that keeps something visibly "on" without falsely
 * implying Basket is the active route.
 */

import * as React from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  Briefcase,
  ChevronDown,
  Crosshair,
  FolderKanban,
  LayoutDashboard,
  LogOut,
  Settings2,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { getCurrentUser, isLoggedIn, listBasket, logout } from "@/lib/api";

type IconComponent = React.ComponentType<React.SVGProps<SVGSVGElement>>;

/** True if `pathname` is exactly `href` or a sub-route of it. */
function matchesRoute(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  return pathname === href || pathname.startsWith(`${href}/`);
}

const NAV_HREFS = ["/dashboard", "/dashboard/provider-health", "/basket", "/cases", "/pentest", "/providers", "/admin"];

/** Longest (most specific) href that matches the current pathname, if any. */
function resolveActiveHref(pathname: string | null): string | null {
  if (!pathname) return null;
  const byLengthDesc = [...NAV_HREFS].sort((a, b) => b.length - a.length);
  return byLengthDesc.find((href) => matchesRoute(pathname, href)) ?? null;
}

function pillClass(active: boolean) {
  return cn(
    "inline-flex items-center gap-1.5 rounded-tight border px-3 py-1.5 text-xs font-medium transition-colors",
    active
      ? "border-primary bg-primary/10 text-primary"
      : "border-border text-muted-foreground hover:bg-muted hover:text-foreground"
  );
}

function captionClass(active: boolean) {
  return cn(
    "font-display text-[10px] font-semibold uppercase tracking-[0.08em]",
    active ? "text-primary" : "text-muted-foreground/70"
  );
}

function NavGroup({
  label,
  active,
  children,
}: {
  label: string;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-start gap-1">
      <span className={captionClass(active)}>{label}</span>
      {children}
    </div>
  );
}

function NavLink({
  href,
  active,
  icon: Icon,
  children,
}: {
  href: string;
  active: boolean;
  icon: IconComponent;
  children: React.ReactNode;
}) {
  return (
    <Link href={href} className={pillClass(active)}>
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {children}
    </Link>
  );
}

export function WorkspaceNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [basketCount, setBasketCount] = React.useState<number | null>(null);
  const [isAdmin, setIsAdmin] = React.useState(false);
  const [adminMenuOpen, setAdminMenuOpen] = React.useState(false);
  const adminMenuRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!isLoggedIn()) return;
    listBasket()
      .then((items) => setBasketCount(items.length))
      .catch(() => setBasketCount(null));
    // Gates the Administration link only -- the real authorization boundary
    // is server-side (require_permission("user:manage") on every
    // /api/v1/admin/* route); this just avoids showing a link a non-admin
    // would immediately get a 403 from.
    getCurrentUser()
      .then((user) => setIsAdmin(user.role === "admin"))
      .catch(() => setIsAdmin(false));
  }, [pathname]);

  // Close the Administration dropdown on every route change (including a
  // click on one of its own links) so it never lingers open after a
  // client-side navigation.
  React.useEffect(() => {
    setAdminMenuOpen(false);
  }, [pathname]);

  // ...and on an outside click while it's open.
  React.useEffect(() => {
    if (!adminMenuOpen) return;
    function handlePointerDown(e: MouseEvent) {
      if (adminMenuRef.current && !adminMenuRef.current.contains(e.target as Node)) {
        setAdminMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [adminMenuOpen]);

  // Real bug found live during overnight QA: no page in the app except '/'
  // had any sign-out control at all -- WorkspaceNav (rendered on every
  // workspace page via BrandHeader) had zero logout affordance, so the only
  // way to sign out from /dashboard, /basket, /cases, /pentest, /providers,
  // /admin, or /dashboard/provider-health was to manually navigate to '/'
  // first. router.push (not router.replace) so the browser back button
  // still behaves normally; logout() itself already revokes the token
  // server-side and clears localStorage.
  const handleSignOut = React.useCallback(() => {
    logout();
    router.push("/login");
  }, [router]);

  const activeHref = resolveActiveHref(pathname);
  const dashboardActive = activeHref === "/dashboard";
  const basketActive = activeHref === "/basket";
  const casesActive = activeHref === "/cases";
  const providerHealthActive = activeHref === "/dashboard/provider-health";
  const pentestActive = activeHref === "/pentest";
  const providersActive = activeHref === "/providers";
  const adminActive = activeHref === "/admin";
  const intelligenceActive = basketActive || matchesRoute(pathname, "/lookup");
  const administrationActive = providersActive || adminActive;

  return (
    <nav className="flex items-start gap-4">
      <NavGroup label="Command" active={dashboardActive}>
        <NavLink href="/dashboard" active={dashboardActive} icon={LayoutDashboard}>
          Dashboard
        </NavLink>
      </NavGroup>

      <NavGroup label="Intelligence" active={intelligenceActive}>
        <NavLink href="/basket" active={basketActive} icon={Briefcase}>
          Basket
          {basketCount !== null && basketCount > 0 && (
            <span className="font-data rounded-full bg-primary px-1.5 py-0 text-[10px] tabular-nums text-primary-foreground">
              {basketCount}
            </span>
          )}
        </NavLink>
      </NavGroup>

      <NavGroup label="Analysis" active={casesActive}>
        <NavLink href="/cases" active={casesActive} icon={FolderKanban}>
          Cases
        </NavLink>
      </NavGroup>

      <NavGroup label="Operations" active={providerHealthActive}>
        <NavLink href="/dashboard/provider-health" active={providerHealthActive} icon={Activity}>
          Provider Health
        </NavLink>
      </NavGroup>

      <NavGroup label="Pentest" active={pentestActive}>
        <NavLink href="/pentest" active={pentestActive} icon={Crosshair}>
          Pentest
        </NavLink>
      </NavGroup>

      {isAdmin && (
        <div ref={adminMenuRef} className="relative flex flex-col items-start gap-1">
          <span className={captionClass(administrationActive)}>Administration</span>
          <button
            type="button"
            onClick={() => setAdminMenuOpen((open) => !open)}
            aria-haspopup="menu"
            aria-expanded={adminMenuOpen}
            className={pillClass(administrationActive)}
          >
            <Settings2 className="h-3.5 w-3.5" aria-hidden="true" />
            Manage
            <ChevronDown className="h-3 w-3" aria-hidden="true" />
          </button>
          {adminMenuOpen && (
            <div
              role="menu"
              className="absolute left-0 top-[calc(100%+0.25rem)] z-20 flex min-w-[10rem] flex-col gap-1 rounded-md border border-border bg-card p-1.5"
            >
              <Link
                href="/providers"
                role="menuitem"
                onClick={() => setAdminMenuOpen(false)}
                className={pillClass(providersActive)}
              >
                <Settings2 className="h-3.5 w-3.5" aria-hidden="true" />
                Providers
              </Link>
              <Link
                href="/admin"
                role="menuitem"
                onClick={() => setAdminMenuOpen(false)}
                className={pillClass(adminActive)}
              >
                <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                Administration
              </Link>
            </div>
          )}
        </div>
      )}

      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={handleSignOut}
        className="ml-auto self-center"
      >
        <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
        Sign out
      </Button>
    </nav>
  );
}
