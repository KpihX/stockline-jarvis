/**
 * Accueil — Hyper-personalised, AI-helped Dashboard per verified profile (Client, Supplier, Manager, Admin).
 * Every AI suggestion is live-computed from ERP facts + LLM briefing, rotates on refresh, and launches directly into Voix or Assistant.
 */
import { useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity, AlertTriangle, ArrowUpRight, AudioLines, Building2, CalendarClock, ClipboardList, Euro,
  MessageSquare, Package, PackageX, Plus, RefreshCw, ShieldCheck, ShoppingCart, Sparkles, TrendingUp, Truck, Users,
} from "lucide-react";
import type { ActivityEvent, Dashboard, DashboardSuggestion, DashboardSuggestionsPayload } from "@kit/shared";
import { cn } from "@/lib/cn";
import { fmtDateLong, parseDate } from "@/lib/format";
import { ACTOR_LABEL } from "@/lib/labels";
import { entityPath } from "@/lib/links";
import { useClient, useDashboard, useEvents, useInvoices, useOrders, usePurchaseOrdersPage, useStockPage, useStreamStatus, useSupplier } from "@/lib/queries";
import {
  ActorIcon, Button, DateLabel, Dot, EmptyState, Money, Page, PageBody, PageHeader, Qty, Section, Skeleton, Stat, StatGrid, StatusDot, isAiActor,
} from "@/ui";
import { shell } from "@/app/shell-state";
import { fetchAiSuggestions } from "@/features/assistant/ai-client";
import { chat } from "@/features/assistant/chat-store";
import { sessionsStore } from "@/features/assistant/sessions-store";
import { useAuth } from "@/features/auth/auth-store";
import { RevenueChart } from "./revenue-chart";

function nextRefreshSeed(): number {
  try {
    const prev = Number(sessionStorage.getItem("kit.dashSeed") || "0");
    const next = prev + 1;
    sessionStorage.setItem("kit.dashSeed", String(next));
    return next;
  } catch {
    return Math.floor(Date.now() / 1000) % 10;
  }
}

export default function DashboardPage() {
  const { account } = useAuth();
  const [seed, setSeed] = useState<number>(() => nextRefreshSeed());

  const suggestionsQ = useQuery({
    queryKey: ["ai", "suggestions", account?.id ?? "anon", seed],
    queryFn: () => fetchAiSuggestions(seed, true),
    staleTime: 60_000,
    retry: false,
  });

  if (account?.role === "client" && account.entityId) {
    return (
      <ClientDashboard
        clientId={account.entityId}
        suggestions={suggestionsQ.data}
        loadingSug={suggestionsQ.isFetching}
        onRefreshSug={() => setSeed((s) => s + 1)}
      />
    );
  }
  if (account?.role === "supplier" && account.entityId) {
    return (
      <SupplierDashboard
        supplierId={account.entityId}
        suggestions={suggestionsQ.data}
        loadingSug={suggestionsQ.isFetching}
        onRefreshSug={() => setSeed((s) => s + 1)}
      />
    );
  }
  return (
    <InternalDashboard
      role={account?.role ?? "manager"}
      actorName={account?.displayName}
      suggestions={suggestionsQ.data}
      loadingSug={suggestionsQ.isFetching}
      onRefreshSug={() => setSeed((s) => s + 1)}
    />
  );
}

// ── Shared AI Hero & Clickable Suggestions Strip ───────────────────────────────────────────────────────────────────

const SUG_TONE: Record<DashboardSuggestion["tone"], string> = {
  emerald: "border-primary/30 bg-primary/[.04] hover:border-primary",
  violet: "border-violet/30 bg-violet/[.05] hover:border-violet",
  warning: "border-warning/40 bg-warning/[.06] hover:border-warning",
  destructive: "border-destructive/40 bg-destructive/[.06] hover:border-destructive",
};

const SUG_DOT: Record<DashboardSuggestion["tone"], "success" | "violet" | "warning" | "destructive"> = {
  emerald: "success",
  violet: "violet",
  warning: "warning",
  destructive: "destructive",
};

function AiSuggestionsStrip({
  data,
  loading,
  onRefresh,
  fallbackTitle,
}: {
  data?: DashboardSuggestionsPayload;
  loading: boolean;
  onRefresh: () => void;
  fallbackTitle: string;
}) {
  const navigate = useNavigate();

  const launchSuggestion = (s: DashboardSuggestion) => {
    if (s.targetSurface === "voice") {
      sessionsStore.setPendingVoiceText(s.prompt);
      navigate("/voice");
    } else {
      shell.openAssistant();
      void chat.send(s.prompt);
    }
  };

  return (
    <div className="border-b border-border bg-gradient-to-r from-violet/[.04] via-card to-primary/[.04] px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[.06em] text-violet">
            <Sparkles size={13} strokeWidth={2} />
            <span>{data?.aiGenerated ? "Briefing IA en direct" : "Synthèse personnalisée"}</span>
          </div>
          <p className="mt-1 text-[14px] font-medium leading-[20px] text-foreground">
            {data?.headline || fallbackTitle}
          </p>
          {data?.notesDigest?.length ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {data.notesDigest.map((n, i) => (
                <span key={i} className="rounded-[3px] border border-border bg-card px-2 py-0.5 text-[11px] text-muted-foreground">
                  {n}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button size="sm" variant="default" icon={RefreshCw} loading={loading} onClick={onRefresh}>
            Nouvelles suggestions
          </Button>
          <Button size="sm" variant="primary" icon={AudioLines} onClick={() => navigate("/voice")}>
            Appeler l'agent
          </Button>
        </div>
      </div>

      {data?.suggestions?.length ? (
        <div className="mt-3.5 grid grid-cols-1 gap-2.5 md:grid-cols-2 xl:grid-cols-4">
          {data.suggestions.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => launchSuggestion(s)}
              className={cn(
                "group flex flex-col gap-1.5 rounded-[6px] border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70",
                SUG_TONE[s.tone],
              )}
            >
              <div className="flex items-center justify-between gap-2 text-[11px] font-medium text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <Dot tone={SUG_DOT[s.tone]} />
                  <span>{s.badge}</span>
                </span>
                <span className="flex items-center gap-1 font-mono text-[10px] text-foreground/70 group-hover:text-foreground">
                  {s.targetSurface === "voice" ? <AudioLines size={11} /> : <MessageSquare size={11} />}
                  {s.targetSurface === "voice" ? "Voix →" : "Chat →"}
                </span>
              </div>
              <div className="text-[13px] font-semibold leading-[17px] text-foreground">{s.title}</div>
              <div className="line-clamp-2 text-[11.5px] leading-[16px] text-muted-foreground">{s.reason}</div>
            </button>
          ))}
        </div>
      ) : loading ? (
        <div className="mt-3.5 grid grid-cols-1 gap-2.5 md:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[88px] w-full" />)}
        </div>
      ) : null}
    </div>
  );
}

// ── 1. CLIENT DASHBOARD ────────────────────────────────────────────────────────────────────────────────────────────

const DAY_FR: Record<string, string> = { mon: "lun", tue: "mar", wed: "mer", thu: "jeu", fri: "ven", sat: "sam", sun: "dim" };
const fmtDays = (ds?: string[]) => (ds?.length ? ds.map((d) => DAY_FR[d] ?? d).join(" · ") : "—");

function ClientDashboard({
  clientId,
  suggestions,
  loadingSug,
  onRefreshSug,
}: {
  clientId: string;
  suggestions?: DashboardSuggestionsPayload;
  loadingSug: boolean;
  onRefreshSug: () => void;
}) {
  const navigate = useNavigate();
  const c = useClient(clientId);
  const orders = useOrders({ clientId, limit: 12 });
  const invoices = useInvoices({ clientId, limit: 12 });
  const cli = c.data;

  const orderList = (orders.data ?? []).filter((o) => o.status !== "cancelled");
  const invoiceList = invoices.data ?? [];
  const openOrders = orderList.filter((o) => o.status !== "invoiced");
  const openInvoices = invoiceList.filter((i) => i.balance > 0);
  const openTotal = openInvoices.reduce((s, i) => s + i.balance, 0);
  const usualItems = cli?.usual?.length
    ? cli.usual.map((u) => ({ productId: u.productId, productName: u.productName, qty: u.avgQty, unit: u.unit }))
    : (suggestions?.usualProducts ?? []);

  const askVoice = (prompt: string) => {
    sessionsStore.setPendingVoiceText(prompt);
    navigate("/voice");
  };

  return (
    <Page>
      <PageHeader
        title={cli?.name ?? "Mon espace client"}
        meta={<span className="text-[12px] text-muted-foreground">{cli ? `${cli.city} · Zone ${cli.zone} · Tournées : ${fmtDays(cli.deliveryDays)}` : "Chargement…"}</span>}
        actions={
          <Button variant="primary" icon={AudioLines} onClick={() => askVoice(`Bonjour, c'est ${cli?.name ?? ""}, je souhaite passer commande comme d'habitude.`)}>
            Commander à la voix
          </Button>
        }
      />
      <PageBody flush>
        <AiSuggestionsStrip
          data={suggestions}
          loading={loadingSug}
          onRefresh={onRefreshSug}
          fallbackTitle={`Bienvenue ${cli?.name ?? ""}. Retrouvez vos habitudes, vos tarifs négociés et vos commandes en un clic.`}
        />
        <StatGrid className="md:grid-cols-4">
          <Stat icon={ShoppingCart} label="Commandes actives" value={<span className="num">{openOrders.length}</span>} hint="Brouillons, confirmées, en cours" onClick={() => navigate("/orders")} />
          <Stat icon={Euro} label="Solde factures ouvertes" value={<Money value={openTotal} />} tone={openTotal > 0 ? "warning" : undefined} hint={`${openInvoices.length} facture(s) à régler`} onClick={() => navigate("/invoices")} />
          <Stat icon={Package} label="Produits habituels" value={<span className="num">{usualItems.length}</span>} hint={cli?.usual?.length ? "Suivis sur 60 jours" : "Dernière saison / commandes"} onClick={() => navigate("/prices")} />
          <Stat icon={Truck} label="Jours de livraison" value={<span>{fmtDays(cli?.deliveryDays)}</span>} hint={cli ? (cli.paymentTermsDays ? `Paiement ${cli.paymentTermsDays} j` : "Paiement comptant") : undefined} />
        </StatGrid>

        <div className="grid grid-cols-1 gap-7 px-5 py-5 lg:grid-cols-3">
          <Section
            title="Vos produits habituels (clic = commander)"
            actions={<Link to="/prices" className="text-[12px] text-primary hover:underline">Mes tarifs →</Link>}
          >
            <ListFrame>
              {usualItems.slice(0, 7).map((u) => (
                <li key={u.productId}>
                  <button
                    type="button"
                    onClick={() => askVoice(`Ajoute ${u.qty} ${u.unit} de ${u.productName} pour ma prochaine livraison.`)}
                    className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-[12.5px] transition-colors hover:bg-muted/60"
                  >
                    <span className="min-w-0 truncate font-medium text-foreground">{u.productName}</span>
                    <span className="shrink-0 font-mono text-[11.5px] text-primary">
                      ~<Qty value={u.qty} unit={u.unit} /> · Voix →
                    </span>
                  </button>
                </li>
              ))}
              {cli && !usualItems.length ? <EmptyLine icon={Package} text="Aucune habitude enregistrée" /> : null}
            </ListFrame>
          </Section>

          <Section
            title="Vos dernières commandes"
            actions={<Link to="/orders" className="text-[12px] text-primary hover:underline">Tout voir →</Link>}
          >
            <ListFrame>
              {orderList.slice(0, 6).map((o) => (
                <li key={o.id}>
                  <Link to={`/orders/${o.id}`} className="flex items-center justify-between gap-2 px-3 py-2 text-[12.5px] hover:bg-muted/60">
                    <span className="min-w-0 flex items-center gap-2">
                      <span className="font-mono text-[12px] font-medium text-foreground">{o.number}</span>
                      <span className="text-[11px] text-muted-foreground">{o.deliveryDate}</span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2.5">
                      <StatusDot kind="order" value={o.status} />
                      <Money value={o.totalHt} className="font-medium" />
                    </span>
                  </Link>
                </li>
              ))}
              {orders.data && !orderList.length ? <EmptyLine icon={ShoppingCart} text="Aucune commande" /> : null}
            </ListFrame>
          </Section>

          <Section
            title="Notes & historique récent"
            actions={<Link to="/history" className="text-[12px] text-primary hover:underline">Historique →</Link>}
          >
            <ListFrame>
              {(cli?.recentEvents ?? []).slice(0, 6).map((e) => (
                <li key={e.id} className="px-3 py-2 text-[12px]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-foreground">{e.title}</span>
                    <span className="shrink-0 font-mono text-[10.5px] text-muted-foreground">{e.at.slice(0, 10)}</span>
                  </div>
                  {e.description ? <div className="mt-0.5 line-clamp-1 text-[11px] text-muted-foreground">{e.description}</div> : null}
                </li>
              ))}
              {cli && !cli.recentEvents?.length ? <EmptyLine icon={Activity} text="Aucun événement récent" /> : null}
            </ListFrame>
          </Section>
        </div>
      </PageBody>
    </Page>
  );
}

// ── 2. SUPPLIER DASHBOARD ──────────────────────────────────────────────────────────────────────────────────────────

function SupplierDashboard({
  supplierId,
  suggestions,
  loadingSug,
  onRefreshSug,
}: {
  supplierId: string;
  suggestions?: DashboardSuggestionsPayload;
  loadingSug: boolean;
  onRefreshSug: () => void;
}) {
  const navigate = useNavigate();
  const s = useSupplier(supplierId);
  const pos = usePurchaseOrdersPage({ supplierId, limit: 12 });
  const lowStock = useStockPage({ tab: "low", limit: 20 });
  const sup = s.data;
  const poList = pos.data?.items ?? [];
  const openPos = poList.filter((p) => p.status === "sent" || p.status === "partially_received");

  return (
    <Page>
      <PageHeader
        title={sup?.name ?? "Espace fournisseur"}
        meta={<span className="text-[12px] text-muted-foreground">{sup ? `${sup.city} · Paiement ${sup.paymentTermsDays} j` : "Chargement…"}</span>}
        actions={
          <Button variant="primary" icon={AudioLines} onClick={() => navigate("/voice")}>
            Contacter l'agent acheteur
          </Button>
        }
      />
      <PageBody flush>
        <AiSuggestionsStrip
          data={suggestions}
          loading={loadingSug}
          onRefresh={onRefreshSug}
          fallbackTitle={`Bienvenue ${sup?.name ?? ""}. Suivez vos bons de commande d'achat, livraisons et stocks associés.`}
        />
        <StatGrid className="md:grid-cols-4">
          <Stat icon={ClipboardList} label="Achats en cours" value={<span className="num">{openPos.length}</span>} tone={openPos.length > 0 ? "violet" : undefined} hint="À livrer ou partiels" onClick={() => navigate("/purchase-orders")} />
          <Stat icon={Euro} label="Volume ouvert HT" value={<Money value={sup?.purchaseStats?.openTotal ?? 0} />} hint="Commandes en attente" />
          <Stat icon={Package} label="Total bons d'achat" value={<span className="num">{sup?.purchaseStats?.count ?? poList.length}</span>} onClick={() => navigate("/purchase-orders")} />
          <Stat icon={Building2} label="Ma fiche fournisseur" value="Active" hint="Détails & incidents" onClick={() => navigate(`/suppliers/${supplierId}`)} />
        </StatGrid>

        <div className="grid grid-cols-1 gap-7 px-5 py-5 lg:grid-cols-3">
          <Section title="Bons de commande d'achat" actions={<Link to="/purchase-orders" className="text-[12px] text-primary hover:underline">Tous les achats →</Link>}>
            <ListFrame>
              {poList.slice(0, 7).map((po) => (
                <li key={po.id}>
                  <Link to={`/purchase-orders/${po.id}`} className="flex items-center justify-between gap-2 px-3 py-2 text-[12.5px] hover:bg-muted/60">
                    <span className="min-w-0">
                      <span className="font-mono text-[12px] font-medium text-foreground">{po.number}</span>
                      <span className="ml-2 text-[11px] text-muted-foreground">{po.expectedDate}</span>
                    </span>
                    <StatusDot kind="purchaseOrder" value={po.status} />
                  </Link>
                </li>
              ))}
              {!poList.length ? <EmptyLine icon={ClipboardList} text="Aucun bon d'achat" /> : null}
            </ListFrame>
          </Section>

          <Section title="Stocks bas chez Alpes Restauration" actions={<Link to="/stock" className="text-[12px] text-primary hover:underline">Stocks →</Link>}>
            <ListFrame>
              {(lowStock.data?.items ?? []).slice(0, 7).map((r) => (
                <li key={r.productId}>
                  <Link to={`/products/${r.productId}`} className="flex items-center justify-between gap-2 px-3 py-2 text-[12.5px] hover:bg-muted/60">
                    <span className="truncate font-medium text-foreground">{r.product.name}</span>
                    <Qty value={r.available} unit={r.product.unit} className="shrink-0 font-medium text-warning" />
                  </Link>
                </li>
              ))}
              {lowStock.data && !lowStock.data.items.length ? <EmptyLine icon={Package} text="Aucune alerte stock" /> : null}
            </ListFrame>
          </Section>

          <Section title="Derniers événements qualité / relation">
            <ListFrame>
              {(sup?.recentEvents ?? []).slice(0, 6).map((e) => (
                <li key={e.id} className="px-3 py-2 text-[12px]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-foreground">{e.title}</span>
                    <span className="shrink-0 font-mono text-[10.5px] text-muted-foreground">{e.at.slice(0, 10)}</span>
                  </div>
                  {e.description ? <div className="mt-0.5 line-clamp-1 text-[11px] text-muted-foreground">{e.description}</div> : null}
                </li>
              ))}
              {sup && !sup.recentEvents?.length ? <EmptyLine icon={Activity} text="Aucun événement" /> : null}
            </ListFrame>
          </Section>
        </div>
      </PageBody>
    </Page>
  );
}

// ── 3. MANAGER / ADMIN DASHBOARD ───────────────────────────────────────────────────────────────────────────────────

function InternalDashboard({
  role,
  actorName,
  suggestions,
  loadingSug,
  onRefreshSug,
}: {
  role: string;
  actorName?: string | null;
  suggestions?: DashboardSuggestionsPayload;
  loadingSug: boolean;
  onRefreshSug: () => void;
}) {
  const navigate = useNavigate();
  const { data: d, isLoading, isError, refetch } = useDashboard();
  const status = useStreamStatus();

  return (
    <Page>
      <PageHeader
        title={role === "admin" ? "Accueil · Direction" : "Accueil · Commercial"}
        meta={
          <span className="flex items-center gap-2 text-[12px] text-muted-foreground">
            {d ? <span className="capitalize">{fmtDateLong(d.today)}</span> : null}
            <span className="flex items-center gap-1.5">
              <Dot tone={status === "live" ? "success" : status === "connecting" ? "warning" : "destructive"} pulse={status === "live"} />
              {status === "live" ? "En direct" : status === "connecting" ? "Connexion…" : "Hors ligne"}
            </span>
          </span>
        }
        actions={
          <div className="flex items-center gap-2">
            {role === "admin" ? (
              <Button variant="default" icon={ShieldCheck} onClick={() => navigate("/accounts")}>Comptes (Admin)</Button>
            ) : null}
            <Button variant="primary" icon={Plus} onClick={() => navigate("/orders?new=1")}>Nouvelle commande</Button>
          </div>
        }
      />
      <PageBody flush>
        <AiSuggestionsStrip
          data={suggestions}
          loading={loadingSug}
          onRefresh={onRefreshSug}
          fallbackTitle={`Bonjour ${actorName ?? "l'équipe"}. Pilotez les commandes du jour, les ruptures et la relance client avec l'IA.`}
        />
        {isError && !d ? (
          <EmptyState icon={TrendingUp} title="Tableau de bord indisponible" description="L'API ne répond pas. Vérifiez que le serveur tourne sur le port 4000." action={<Button size="sm" onClick={() => refetch()}>Réessayer</Button>} />
        ) : (
          <>
            <Kpis d={d} loading={isLoading} />
            <div className="grid grid-cols-1 gap-8 px-5 py-5 xl:grid-cols-[minmax(0,1fr)_360px]">
              <div className="flex min-w-0 flex-col gap-7">
                <RevenueSection d={d} />
                <div className="grid grid-cols-1 gap-7 lg:grid-cols-3">
                  <TopClients d={d} />
                  <LowStock d={d} />
                  <Expiring d={d} />
                </div>
              </div>
              <LiveActivity />
            </div>
          </>
        )}
      </PageBody>
    </Page>
  );
}

function Kpis({ d, loading }: { d?: Dashboard; loading: boolean }) {
  const navigate = useNavigate();
  const v = (node: ReactNode) => (loading || !d ? <Skeleton className="mt-1 h-5 w-20" /> : node);
  return (
    <StatGrid className="md:grid-cols-3 xl:grid-cols-6 [&>*:nth-child(-n+3)]:border-b [&>*]:border-border xl:[&>*]:border-b-0">
      <Stat icon={Euro} label="CA du jour" value={v(<Money value={d?.revenueToday} compact />)} hint="Livraisons du jour, HT" onClick={() => navigate("/orders?date=today")} />
      <Stat icon={TrendingUp} label="CA du mois" value={v(<Money value={d?.revenueMonth} compact />)} hint="Depuis le 1er, HT" onClick={() => navigate("/invoices")} />
      <Stat icon={ShoppingCart} label="Commandes du jour" value={v(<span className="num">{d?.ordersToday}</span>)} hint="Livraison aujourd'hui" onClick={() => navigate("/orders?date=today")} />
      <Stat
        icon={ClipboardList} label="Pré-commandes à traiter" value={v(<span className="num">{d?.draftOrders}</span>)}
        tone={d && d.draftOrders > 0 ? "violet" : undefined} hint="À confirmer" onClick={() => navigate("/orders?status=draft")}
      />
      <Stat icon={Truck} label="À livrer aujourd'hui" value={v(<span className="num">{d?.toDeliverToday}</span>)} hint="Confirmées ou préparées" onClick={() => navigate("/orders?date=today")} />
      <Stat
        icon={AlertTriangle} label="Impayés en retard" value={v(<Money value={d?.overdueInvoicesAmount} compact />)}
        tone={d && d.overdueInvoicesAmount > 0 ? "destructive" : undefined}
        hint={d ? `${d.overdueInvoicesCount} facture${d.overdueInvoicesCount > 1 ? "s" : ""}` : undefined}
        onClick={() => navigate("/invoices?status=overdue")}
      />
    </StatGrid>
  );
}

function RevenueSection({ d }: { d?: Dashboard }) {
  const navigate = useNavigate();
  const total = useMemo(() => d?.revenueByDay.reduce((s, x) => s + x.revenue, 0) ?? 0, [d]);
  const days = d?.revenueByDay.filter((x) => x.revenue > 0).length ?? 0;
  return (
    <Section
      title="Chiffre d'affaires · 30 jours"
      actions={d ? (
        <span className="flex items-center gap-3 text-[12px] text-muted-foreground">
          <span>Total <Money value={total} compact className="font-medium text-foreground" /></span>
          <span>Moyenne <Money value={days ? total / days : 0} compact className="font-medium text-foreground" /> / jour livré</span>
        </span>
      ) : null}
    >
      <div className="rounded-[6px] border border-border bg-card px-3 pb-1 pt-3">
        {d ? (
          d.revenueByDay.length ? (
            <RevenueChart data={d.revenueByDay} today={d.today} onPick={(date) => navigate(`/orders?date=${date}`)} />
          ) : (
            <EmptyState compact icon={TrendingUp} title="Pas encore de chiffre d'affaires" />
          )
        ) : (
          <Skeleton className="mb-2 h-[164px] w-full" />
        )}
      </div>
    </Section>
  );
}

function ListFrame({ children }: { children: ReactNode }) {
  return <ul className="flex flex-col divide-y divide-border overflow-hidden rounded-[6px] border border-border bg-card">{children}</ul>;
}
function ListSkeleton() {
  return <ListFrame>{Array.from({ length: 5 }).map((_, i) => <li key={i} className="flex h-9 items-center px-3"><Skeleton className="h-3 w-full" /></li>)}</ListFrame>;
}
function EmptyLine({ icon: Icon, text }: { icon: typeof Users; text: string }) {
  return <li className="flex items-center gap-2 px-3 py-4 text-[12.5px] text-muted-foreground"><Icon size={14} strokeWidth={1.75} />{text}</li>;
}
const ROW_LINK = "flex h-9 items-center justify-between gap-2 px-3 text-[13px] transition-colors hover:bg-muted/60";

function TopClients({ d }: { d?: Dashboard }) {
  return (
    <Section title="Clients actifs (30 j)" actions={<Link to="/clients" className="text-[12px] text-muted-foreground hover:text-foreground">Tous</Link>}>
      {!d ? <ListSkeleton /> : d.topClients.length === 0 ? <ListFrame><EmptyLine icon={Users} text="Aucune vente sur 30 j" /></ListFrame> : (
        <ListFrame>
          {d.topClients.map((c) => (
            <li key={c.clientId}>
              <Link to={`/clients/${c.clientId}`} className={ROW_LINK}>
                <span className="truncate font-medium">{c.name}</span>
                <span className="flex shrink-0 items-center gap-2">
                  <Money value={c.revenue} compact className="font-medium" />
                </span>
              </Link>
            </li>
          ))}
        </ListFrame>
      )}
    </Section>
  );
}

function LowStock({ d }: { d?: Dashboard }) {
  return (
    <Section title="Stock bas" actions={<Link to="/stock?tab=low" className="text-[12px] text-muted-foreground hover:text-foreground">Tout voir</Link>}>
      {!d ? <ListSkeleton /> : d.lowStock.length === 0 ? <ListFrame><EmptyLine icon={PackageX} text="Aucun produit sous le seuil" /></ListFrame> : (
        <ListFrame>
          {d.lowStock.map((p) => (
            <li key={p.productId}>
              <Link to={`/products/${p.productId}`} className={ROW_LINK}>
                <span className="truncate">{p.name}</span>
                <Qty value={p.available} unit={p.unit} className={cn("shrink-0 font-medium", p.available <= 0 ? "text-destructive" : "text-warning")} />
              </Link>
            </li>
          ))}
        </ListFrame>
      )}
    </Section>
  );
}

function Expiring({ d }: { d?: Dashboard }) {
  return (
    <Section title="DLC proches (≤ 2 j)" actions={<Link to="/stock?tab=expiring" className="text-[12px] text-muted-foreground hover:text-foreground">Lots</Link>}>
      {!d ? <ListSkeleton /> : d.expiringSoon.length === 0 ? <ListFrame><EmptyLine icon={CalendarClock} text="Aucun lot à échéance proche" /></ListFrame> : (
        <ListFrame>
          {d.expiringSoon.map((l) => (
            <li key={l.lotId}>
              <Link to={`/products/${l.productId}`} className={ROW_LINK}>
                <span className="min-w-0 truncate">{l.name}</span>
                <span className="flex shrink-0 items-center gap-2 text-[12px]">
                  <span className="num text-muted-foreground">{l.qtyRemaining}</span>
                  <DateLabel date={l.expiresAt} />
                </span>
              </Link>
            </li>
          ))}
        </ListFrame>
      )}
    </Section>
  );
}

function LiveActivity() {
  const { data: events } = useEvents(20);
  return (
    <Section title="Activité en direct" actions={<Link to="/activity" className="text-[12px] text-muted-foreground hover:text-foreground">Journal →</Link>}>
      <ListFrame>
        {(events ?? []).slice(0, 10).map((ev: ActivityEvent) => {
          const to = entityPath(ev.entity, ev.entityId);
          return (
            <li key={ev.id} className="px-3 py-2 text-[12px]">
              <div className="flex items-start justify-between gap-2">
                <span className={cn("flex items-center gap-1.5 font-medium", isAiActor(ev.actor) && "text-violet")}>
                  <ActorIcon actor={ev.actor} />
                  <span>{ev.actorName || ACTOR_LABEL[ev.actor] || ev.actor}</span>
                </span>
                <span className="shrink-0 font-mono text-[10.5px] text-muted-foreground">{parseDate(ev.at).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}</span>
              </div>
              <div className="mt-0.5 text-[12px] text-secondary-foreground">{ev.summary}</div>
              {to ? (
                <Link to={to} className="mt-0.5 inline-flex items-center gap-0.5 text-[11px] text-primary hover:underline">
                  Ouvrir <ArrowUpRight size={10} />
                </Link>
              ) : null}
            </li>
          );
        })}
        {events && !events.length ? <EmptyLine icon={Activity} text="Aucune activité récente" /> : null}
      </ListFrame>
    </Section>
  );
}
