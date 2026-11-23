/**
 * Login page (/login) — clean sign-in form + 1-click Demo Accounts grid for the jury.
 * Supports light and dark theme, keyboard focus, error feedback and ?next= redirect.
 */
import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AudioLines, Building2, CheckCircle2, Lock, ShieldCheck, Sparkles, UserCheck, Users } from "lucide-react";
import type { AuthRole, DemoAccount } from "@kit/shared";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Dot, Field, Input, ThemeToggle, type Tone } from "@/ui";
import { AUTH_ROLE_LABEL, auth } from "@/features/auth/auth-store";
import { ROLE_HELP } from "@/features/assistant/caller";

const ROLE_TONE: Record<AuthRole, Tone> = {
  client: "info",
  supplier: "warning",
  manager: "violet",
  admin: "success",
};

const ROLE_ICON: Record<AuthRole, typeof Users> = {
  client: UserCheck,
  supplier: Building2,
  manager: Users,
  admin: ShieldCheck,
};

export default function LoginPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get("next") || "/";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [demoLoading, setDemoLoading] = useState<string | null>(null);

  const demos = useQuery({
    queryKey: ["auth", "demos"],
    queryFn: api.auth.demoAccounts,
    staleTime: 60_000,
  });

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError("Saisissez votre identifiant et votre mot de passe.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      await auth.login(username.trim(), password);
      navigate(next, { replace: true });
    } catch (err) {
      setError((err as Error).message || "Connexion impossible.");
    } finally {
      setLoading(false);
    }
  };

  const onQuickDemo = async (d: DemoAccount) => {
    setError(null);
    setDemoLoading(d.id);
    try {
      await auth.loginDemo(d);
      navigate(next, { replace: true });
    } catch (err) {
      setError((err as Error).message || "Connexion démo impossible.");
    } finally {
      setDemoLoading(null);
    }
  };

  return (
    <div className="flex min-h-full flex-col bg-background text-foreground">
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-border px-6">
        <div className="flex items-center gap-2.5">
          <img src="/brand/stockline-mark-black.svg" alt="" width={18} height={18} className="h-[18px] w-[18px] dark:hidden" />
          <img src="/brand/stockline-mark-white.svg" alt="" width={18} height={18} className="hidden h-[18px] w-[18px] dark:block" />
          <span className="text-[13.5px] font-semibold">Alpes Restauration</span>
          <span className="text-[12px] text-muted-foreground">· ERP & Agent Vocal Stockline</span>
        </div>
        <ThemeToggle />
      </header>

      <div className="mx-auto grid w-full max-w-[1040px] flex-1 grid-cols-1 items-center gap-8 px-6 py-10 lg:grid-cols-[380px_minmax(0,1fr)]">
        {/* Left: standard sign-in card */}
        <section className="rounded-[6px] border border-border bg-card p-6 shadow-sm">
          <div className="mb-5">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[.06em] text-primary">
              <Lock size={12} strokeWidth={2} />
              <span>Accès vérifié par profil</span>
            </div>
            <h1 className="mt-1.5 text-[20px] font-semibold tracking-tight">Connexion</h1>
            <p className="mt-1 text-[12.5px] leading-[18px] text-muted-foreground">
              Votre rôle fixe ce que l'ERP affiche et ce que l'agent vocal a le droit de consulter ou d'écrire.
            </p>
          </div>

          <form onSubmit={onSubmit} className="flex flex-col gap-3.5">
            <Field label="Identifiant">
              <Input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="ex. payet, chambaran, thibault, admin"
                autoComplete="username"
              />
            </Field>
            <Field label="Mot de passe">
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Mot de passe"
                autoComplete="current-password"
              />
            </Field>
            {error ? (
              <div role="alert" className="rounded-[4px] border border-destructive/30 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
                {error}
              </div>
            ) : null}
            <Button type="submit" variant="primary" loading={loading} className="mt-1 w-full justify-center">
              Se connecter
            </Button>
          </form>

          <div className="mt-5 flex items-start gap-2 rounded-[4px] border border-border bg-muted/40 p-3 text-[11.5px] leading-[16px] text-muted-foreground">
            <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-success" />
            <span>
              Jeton signé HMAC côté serveur (12 h). L'agent IA reçoit votre identité vérifiée, pas une simple affirmation orale.
            </span>
          </div>
        </section>

        {/* Right: 1-click Demo Profiles for jury */}
        <section className="flex flex-col gap-4">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[.06em] text-violet">
                <Sparkles size={12} strokeWidth={2} />
                <span>Comptes de démo (connexion 1-clic)</span>
              </div>
              <h2 className="mt-1 text-[17px] font-semibold">Tester chaque point de vue instantanément</h2>
              <p className="mt-0.5 text-[12.5px] text-muted-foreground">
                Démo : identifiants fictifs. Chaque profil adapte le tableau de bord, la navigation, les droits API et le contexte du LLM.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {(demos.data ?? []).map((d) => {
              const Icon = ROLE_ICON[d.role];
              const isBusy = demoLoading === d.id;
              return (
                <button
                  key={d.id}
                  type="button"
                  disabled={demoLoading !== null}
                  onClick={() => void onQuickDemo(d)}
                  className={cn(
                    "group flex flex-col gap-2 rounded-[6px] border border-border bg-card p-3.5 text-left transition-colors hover:border-primary/50 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70 disabled:opacity-60",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5 text-[11.5px] font-medium text-muted-foreground">
                      <Dot tone={ROLE_TONE[d.role]} />
                      <Icon size={13} strokeWidth={1.75} />
                      <span>{AUTH_ROLE_LABEL[d.role]}</span>
                    </span>
                    <span className="rounded-[3px] border border-border bg-background px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground group-hover:border-primary/40 group-hover:text-primary">
                      {isBusy ? "Connexion…" : "1 clic →"}
                    </span>
                  </div>
                  <div className="text-[14px] font-semibold text-foreground">{d.displayName}</div>
                  <div className="line-clamp-2 text-[11.5px] leading-[16px] text-muted-foreground">
                    {ROLE_HELP[d.role]}
                  </div>
                  <div className="mt-auto flex items-center justify-between border-t border-border/60 pt-2 font-mono text-[10.5px] text-muted-foreground">
                    <span>@{d.username}</span>
                    <span>mdp : {d.demoPassword}</span>
                  </div>
                </button>
              );
            })}
          </div>

          <div className="flex items-center gap-2 text-[11.5px] text-muted-foreground">
            <AudioLines size={13} className="text-violet" />
            <span>Astuce jury : connectez-vous en <strong>Client (Le Refuge Payet)</strong> puis cliquez une suggestion IA pour tester un appel vocal complet.</span>
          </div>
        </section>
      </div>
    </div>
  );
}
