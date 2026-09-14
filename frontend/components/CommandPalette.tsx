"use client";

/**
 * Global Ctrl/Cmd+K command palette -- mounted once in BrandHeader.tsx (every
 * authenticated workspace page renders BrandHeader, so this is effectively
 * app-wide without needing a change to the root layout). Renders nothing
 * (not even the trigger button) until a session exists -- every action below
 * either navigates within the authenticated app or calls an authenticated
 * endpoint, so there is nothing useful to offer pre-login.
 *
 * Built on `cmdk` (unstyled combobox primitive) inside this app's existing
 * Dialog (components/ui/dialog.tsx) rather than cmdk's own Command.Dialog, so
 * it inherits the same overlay/border/surface treatment as every other modal
 * in the app instead of a one-off look.
 */

import * as React from "react";
import { Command } from "cmdk";
import { useRouter } from "next/navigation";
import { Activity, Briefcase, Clock, Crosshair, FolderKanban, LayoutDashboard, LogOut, Search, Settings2, ShieldCheck } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { getCurrentUser, isLoggedIn, listLookups, logout } from "@/lib/api";

interface RecentLookup {
  id: string;
  ioc_value: string;
  ioc_type: string;
}

type IconComponent = React.ComponentType<React.SVGProps<SVGSVGElement>>;

interface NavCommand {
  value: string;
  icon: IconComponent;
  href: string;
  adminOnly?: boolean;
}

// Declared in this exact priority order -- when a typed query matches more
// than one nav label as a substring, the FIRST declared match wins the
// forced selection below, e.g. "prov" matches both "Provider Health" and
// "Providers", and Provider Health (declared first) wins.
const NAV_COMMANDS: NavCommand[] = [
  { value: "Dashboard", icon: LayoutDashboard, href: "/dashboard" },
  { value: "Basket", icon: Briefcase, href: "/basket" },
  { value: "Cases", icon: FolderKanban, href: "/cases" },
  { value: "Provider Health", icon: Activity, href: "/dashboard/provider-health" },
  { value: "Pentest", icon: Crosshair, href: "/pentest" },
  { value: "Providers", icon: Settings2, href: "/providers", adminOnly: true },
  { value: "Administration", icon: ShieldCheck, href: "/admin", adminOnly: true },
];

const GROUP_CLASS =
  "[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.08em] [&_[cmdk-group-heading]]:text-muted-foreground/70";

const ITEM_CLASS =
  "flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-sm text-foreground outline-none data-[selected=true]:bg-muted";

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const [isAdmin, setIsAdmin] = React.useState(false);
  const [recent, setRecent] = React.useState<RecentLookup[]>([]);
  const [recentLoading, setRecentLoading] = React.useState(false);
  const [loggedIn, setLoggedIn] = React.useState(false);

  React.useEffect(() => {
    setLoggedIn(isLoggedIn());
  }, []);

  React.useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (!isLoggedIn()) return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  React.useEffect(() => {
    if (!open) return;
    setSearch("");
    getCurrentUser()
      .then((u) => setIsAdmin(u.role === "admin"))
      .catch(() => setIsAdmin(false));
    setRecentLoading(true);
    listLookups()
      .then((rows: RecentLookup[]) => setRecent(rows.slice(0, 5)))
      .catch(() => setRecent([]))
      .finally(() => setRecentLoading(false));
  }, [open]);

  const go = React.useCallback(
    (path: string) => {
      setOpen(false);
      router.push(path);
    },
    [router]
  );

  const trimmedSearch = search.trim();
  const q = trimmedSearch.toLowerCase();

  // Filtering/ordering is done here, in plain JS, with `shouldFilter={false}`
  // on <Command> below -- NOT left to cmdk's own built-in fuzzy scoring.
  // cmdk scores every item against the query and auto-selects the top
  // scorer; the "Investigate" item's own value IS the raw query, so it
  // always scores a perfect/tying match against anything typed -- including
  // a real nav label like "Provider Health" -- and can win or tie a genuine
  // destination purely by being declared first. That's a real bug, not a
  // cosmetic one: confirmed live, it sent a typed "Provider Health" to a
  // bogus IOC investigation instead of the real Provider Health page.
  // Controlling cmdk's `value`/`onValueChange` was tried first and did NOT
  // reliably fix it (cmdk's own scoring still ran underneath), so filtering
  // is done manually instead: a real Navigate match always renders (and is
  // therefore always the default-selected FIRST item) before Recent
  // Investigations, which always renders before the generic Investigate
  // catch-all -- simple substring matching, not fuzzy, but deterministic
  // and correct, which matters far more here than fuzzy typo-tolerance
  // across a list of seven nav commands.
  const visibleNavCommands = React.useMemo(() => {
    const base = NAV_COMMANDS.filter((c) => !c.adminOnly || isAdmin);
    return q ? base.filter((c) => c.value.toLowerCase().includes(q)) : base;
  }, [isAdmin, q]);
  const showSignOut = !q || "sign out".includes(q);
  const matchingRecent = React.useMemo(() => {
    if (!q) return recent;
    return recent.filter((r) => r.ioc_value.toLowerCase().includes(q) || r.ioc_type.toLowerCase().includes(q));
  }, [recent, q]);

  if (!loggedIn) return null;

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        className="gap-1.5 self-center text-muted-foreground"
      >
        <Search className="h-3.5 w-3.5" aria-hidden="true" />
        <span className="hidden sm:inline">Search</span>
        <kbd className="hidden rounded border border-border bg-muted px-1 font-data text-[10px] sm:inline">Ctrl K</kbd>
      </Button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          className="max-w-lg overflow-hidden p-0"
          onOpenAutoFocus={(e) => {
            // cmdk's own <Command.Input autoFocus> already grabs focus
            // correctly -- letting Radix's default autofocus run too just
            // fights it for the first render's focus target.
            e.preventDefault();
          }}
        >
          <DialogTitle className="sr-only">Command palette</DialogTitle>
          <DialogDescription className="sr-only">
            Investigate an IOC, or jump to any page in the application.
          </DialogDescription>
          <Command label="Command palette" shouldFilter={false} className="flex flex-col">
            <div className="flex items-center gap-2 border-b border-border px-3">
              <Search className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              <Command.Input
                autoFocus
                value={search}
                onValueChange={setSearch}
                placeholder="Investigate an IOC, or jump to..."
                className="flex-1 bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground"
              />
            </div>
            <Command.List className="max-h-80 overflow-y-auto p-2">
              <Command.Empty className="py-6 text-center text-sm text-muted-foreground">No matches.</Command.Empty>

              {(visibleNavCommands.length > 0 || showSignOut) && (
                <Command.Group heading="Navigate" className={GROUP_CLASS}>
                  {visibleNavCommands.map((c) => (
                    <Command.Item key={c.value} value={c.value} onSelect={() => go(c.href)} className={ITEM_CLASS}>
                      <c.icon className="h-3.5 w-3.5" aria-hidden="true" />
                      {c.value}
                    </Command.Item>
                  ))}
                  {showSignOut && (
                    <Command.Item
                      value="Sign out"
                      onSelect={() => {
                        setOpen(false);
                        logout();
                        router.push("/login");
                      }}
                      className={ITEM_CLASS}
                    >
                      <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
                      Sign out
                    </Command.Item>
                  )}
                </Command.Group>
              )}

              {!recentLoading && matchingRecent.length > 0 && (
                <Command.Group heading="Recent Investigations" className={GROUP_CLASS}>
                  {matchingRecent.map((r) => (
                    <Command.Item
                      key={r.id}
                      value={r.id}
                      onSelect={() => go(`/lookup/${r.id}`)}
                      className={ITEM_CLASS}
                    >
                      <Clock className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                      <span className="truncate font-data">{r.ioc_value}</span>
                      <span className="ml-auto shrink-0 text-xs text-muted-foreground">{r.ioc_type}</span>
                    </Command.Item>
                  ))}
                </Command.Group>
              )}

              {/* Always last, and with shouldFilter={false} above, DOM order
                 is selection-priority order -- the first rendered item is
                 cmdk's default selection, so a real Navigate/Recent match
                 (rendered in the groups above) is always selected over this
                 catch-all whenever one exists, deterministically. */}
              {trimmedSearch && (
                <Command.Group heading="Investigate" className={GROUP_CLASS}>
                  <Command.Item
                    value={`investigate:${trimmedSearch}`}
                    onSelect={() => go(`/lookup/new?value=${encodeURIComponent(trimmedSearch)}`)}
                    className={ITEM_CLASS}
                  >
                    <Search className="h-3.5 w-3.5" aria-hidden="true" />
                    Investigate &quot;{trimmedSearch}&quot;
                  </Command.Item>
                </Command.Group>
              )}
            </Command.List>
          </Command>
        </DialogContent>
      </Dialog>
    </>
  );
}
