/**
 * UserMenu — verified identity pill in the shell header & /voice header.
 * Shows who is logged in, exact AI scope tooltip, quick 1-click demo switcher (for the jury), /accounts link (admin), and logout.
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { KeyRound, LogIn, LogOut, ShieldCheck, Users } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import type { AuthRole, DemoAccount } from "@kit/shared";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { AnchoredPopover, Button, Dot, type Tone } from "@/ui";
import { AUTH_ROLE_LABEL, auth, useAuth } from "./auth-store";
import { ROLE_HELP } from "@/features/assistant/caller";

const ROLE_TONE: Record<AuthRole, Tone> = {
  client: "info",
  supplier: "warning",
  manager: "violet",
  admin: "success",
};

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("") || "?";
}

export function UserMenu({ className }: { className?: string }) {
  const { account } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const anchorRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const demos = useQuery({
    queryKey: ["auth", "demos"],
    queryFn: api.auth.demoAccounts,
    staleTime: 60_000,
    enabled: open,
  });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node | null;
      if (!t || anchorRef.current?.contains(t) || panelRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  if (!account) {
    return (
      <Button size="sm" variant="primary" icon={LogIn} onClick={() => navigate("/login")} className={className}>
        Se connecter
      </Button>
    );
  }

  const switchTo = async (d: DemoAccount) => {
    setBusyId(d.id);
    try {
      await auth.loginDemo(d);
      setOpen(false);
      navigate("/");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div ref={anchorRef} className={cn("shrink-0", className)}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="dialog"
        title={`Identité vérifiée (${AUTH_ROLE_LABEL[account.role]}) : ${ROLE_HELP[account.role]}`}
        className="inline-flex h-[26px] items-center gap-1.5 rounded-[4px] border border-border bg-card px-2 text-[12px] font-medium text-foreground transition-colors hover:border-border-hover hover:bg-muted"
      >
        <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-[3px] bg-primary/15 text-[10px] font-semibold text-primary">
          {initials(account.displayName)}
        </span>
        <Dot tone={ROLE_TONE[account.role]} />
        <span className="max-w-[140px] truncate">{account.displayName}</span>
        <span className="hidden text-[10.5px] font-normal text-muted-foreground xl:inline">
          · {AUTH_ROLE_LABEL[account.role]}
        </span>
      </button>

      <AnchoredPopover anchorRef={anchorRef} open={open} matchWidth={false} width={340} maxHeight={520} role="dialog" aria-label="Profil et changement de compte">
        <div ref={panelRef} className="flex flex-col gap-3 p-3 text-[12.5px]">
          <div className="flex items-start justify-between gap-2 border-b border-border pb-2.5">
            <div className="min-w-0">
              <div className="truncate font-semibold text-foreground">{account.displayName}</div>
              <div className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-success">
                <ShieldCheck size={12} strokeWidth={2} />
                <span>Identité vérifiée · {AUTH_ROLE_LABEL[account.role]}</span>
              </div>
              {account.entityLabel ? <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{account.entityLabel}</div> : null}
            </div>
            <span className="rounded-[3px] border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
              @{account.username}
            </span>
          </div>

          <div className="rounded-[4px] border border-border bg-muted/40 p-2 text-[11.5px] leading-[16px] text-secondary-foreground">
            <span className="font-medium text-foreground">Ce que l'agent IA peut faire : </span>
            {ROLE_HELP[account.role]}
          </div>

          <div>
            <div className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-[.06em] text-muted-foreground">
              Changer de profil (démo 1-clic)
            </div>
            <div className="flex max-h-[210px] flex-col gap-1 overflow-y-auto">
              {(demos.data ?? []).map((d) => {
                const current = d.username === account.username;
                return (
                  <button
                    key={d.id}
                    type="button"
                    disabled={busyId !== null}
                    onClick={() => void switchTo(d)}
                    className={cn(
                      "flex items-center justify-between gap-2 rounded-[4px] border px-2 py-1.5 text-left text-[12px] transition-colors",
                      current ? "border-primary/40 bg-row-selected font-medium" : "border-border bg-card hover:bg-muted",
                    )}
                  >
                    <span className="flex min-w-0 items-center gap-1.5">
                      <Dot tone={ROLE_TONE[d.role]} />
                      <span className="truncate">{d.displayName}</span>
                    </span>
                    <span className="shrink-0 text-[10.5px] text-muted-foreground">
                      {busyId === d.id ? "…" : AUTH_ROLE_LABEL[d.role]}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex items-center justify-between gap-2 border-t border-border pt-2">
            {account.role === "admin" ? (
              <Button size="sm" variant="default" icon={Users} onClick={() => { setOpen(false); navigate("/accounts"); }}>
                Comptes
              </Button>
            ) : (
              <Button size="sm" variant="ghost" icon={KeyRound} onClick={() => { setOpen(false); navigate("/login"); }}>
                Page connexion
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              icon={LogOut}
              onClick={() => {
                setOpen(false);
                void auth.logout().then(() => navigate("/login"));
              }}
            >
              Déconnexion
            </Button>
          </div>
        </div>
      </AnchoredPopover>
    </div>
  );
}
