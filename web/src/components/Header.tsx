import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MenuIcon, PlusIcon } from "lucide-react";
import { api, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import type { Page } from "@/lib/route";
import { cn } from "@/lib/utils";
import { AppLink } from "./bits";

const PAGES: { page: Page; label: string; href: string }[] = [
  { page: "items", label: "Items", href: "/app/" },
  { page: "taxonomy", label: "Taxonomy", href: "/app/taxonomy" },
];

/** The app's top bar. `onFilters` (narrow windows) shows ☰ instead of the page links; `onAdd` the "+ Add". */
export function Header({ page, onFilters, onAdd }: { page: Page; onFilters?: () => void; onAdd?: () => void }) {
  const queryClient = useQueryClient();
  const logout = useMutation({
    mutationFn: async () => unwrap(await api.POST("/auth/logout")),
    onSuccess: () => queryClient.resetQueries(),
  });

  return (
    <header className="flex items-center gap-5 py-2.5">
      {onFilters && (
        <Button variant="ghost" size="icon" aria-label="Show tags and filters" onClick={onFilters}>
          <MenuIcon />
        </Button>
      )}
      <div className="flex items-center gap-2 font-semibold tracking-tight whitespace-nowrap">
        <span className="size-[0.7rem] rounded-[2px] bg-primary" />
        Knowledge Base
      </div>
      {!onFilters && (
        <nav aria-label="Main" className="flex gap-1">
          {PAGES.map((p) => (
            <AppLink
              key={p.page}
              href={p.href}
              aria-current={p.page === page ? "page" : undefined}
              className={cn(
                "rounded-md px-2.5 py-1 font-medium text-muted-foreground",
                p.page === page && "bg-card text-foreground ring-1 ring-border",
              )}
            >
              {p.label}
            </AppLink>
          ))}
        </nav>
      )}
      <span className="flex-1" />
      {onAdd && (
        <Button onClick={onAdd}>
          <PlusIcon />
          <span className={onFilters ? "sr-only" : undefined}>Add</span>
        </Button>
      )}
      <Button variant="ghost" onClick={() => logout.mutate()}>
        Log out
      </Button>
    </header>
  );
}
