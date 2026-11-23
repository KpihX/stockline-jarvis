/**
 * Admin-only Accounts management page (/accounts).
 * Uses ONLY design-system components from @/ui (Select and DatePicker from the design system).
 */
import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus, ShieldAlert, ShieldCheck, Trash2, Users } from "lucide-react";
import type { Account, AuthRole } from "@kit/shared";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useClients, useSuppliers } from "@/lib/queries";
import {
  Button, DataTable, EmptyState, Field, Input, Page, PageBody, PageHeader, Section, Select, SidePanel, StatusDot, toast, type Column,
} from "@/ui";
import { AUTH_ROLE_LABEL, useAuth } from "@/features/auth/auth-store";

const ROLE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Tous les rôles" },
  { value: "client", label: "Client" },
  { value: "supplier", label: "Fournisseur" },
  { value: "manager", label: "Commercial" },
  { value: "admin", label: "Admin unique" },
];

const CREATABLE_ROLES: { value: AuthRole; label: string }[] = [
  { value: "client", label: "Client (rattaché à un cli_…)" },
  { value: "supplier", label: "Fournisseur (rattaché à un sup_…)" },
  { value: "manager", label: "Commercial (accès métier)" },
];

const STATUS_OPTIONS = [
  { value: "", label: "Tous statuts" },
  { value: "active", label: "Actifs" },
  { value: "inactive", label: "Désactivés" },
];

export default function AccountsPage() {
  const { account: me } = useAuth();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [selected, setSelected] = useState<Account | null>(null);
  const [creating, setCreating] = useState(false);

  const accounts = useQuery({
    queryKey: ["accounts"],
    queryFn: api.accounts.list,
    enabled: me?.role === "admin",
  });

  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (accounts.data ?? []).filter((a) => {
      if (roleFilter && a.role !== roleFilter) return false;
      if (statusFilter === "active" && !a.active) return false;
      if (statusFilter === "inactive" && a.active) return false;
      if (s && !`${a.username} ${a.displayName} ${a.entityLabel ?? ""} ${a.entityId ?? ""}`.toLowerCase().includes(s)) return false;
      return true;
    });
  }, [accounts.data, q, roleFilter, statusFilter]);

  if (me?.role !== "admin") {
    return (
      <Page>
        <PageHeader title="Comptes" />
        <PageBody>
          <EmptyState
            icon={ShieldAlert}
            title="Accès réservé à l'administrateur unique"
            description="Connectez-vous en tant qu'administrateur pour gérer les comptes et profils."
          />
        </PageBody>
      </Page>
    );
  }

  const columns: Column<Account>[] = [
    {
      id: "displayName",
      header: "Utilisateur",
      cell: (a) => (
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 font-medium text-foreground">
            <span>{a.displayName}</span>
            {a.role === "admin" ? (
              <span className="inline-flex items-center gap-1 rounded-[3px] border border-success/40 bg-success/10 px-1.5 py-0.5 text-[10px] font-semibold text-success">
                <ShieldCheck size={10} /> Admin unique
              </span>
            ) : null}
          </div>
          <div className="font-mono text-[11px] text-muted-foreground">@{a.username}</div>
        </div>
      ),
    },
    {
      id: "role",
      header: "Rôle",
      width: 150,
      cell: (a) => (
        <StatusDot
          tone={a.role === "admin" ? "success" : a.role === "manager" ? "violet" : a.role === "supplier" ? "warning" : "info"}
          label={AUTH_ROLE_LABEL[a.role]}
        />
      ),
    },
    {
      id: "entity",
      header: "Entité rattachée",
      cell: (a) => (
        <span className="text-[12.5px] text-secondary-foreground">
          {a.entityLabel || a.entityId || (a.role === "admin" ? "Entreprise entière" : "—")}
        </span>
      ),
    },
    {
      id: "active",
      header: "Statut",
      width: 115,
      cell: (a) => <StatusDot tone={a.active ? "success" : "muted"} label={a.active ? "Actif" : "Désactivé"} />,
    },
    {
      id: "lastLoginAt",
      header: "Dernière connexion",
      width: 145,
      cell: (a) => <span className="num text-[12px] text-muted-foreground">{a.lastLoginAt ? fmtDate(a.lastLoginAt.slice(0, 10)) : "Jamais"}</span>,
    },
  ];

  const hasFilters = !!(q || roleFilter || statusFilter);

  return (
    <Page>
      <PageHeader
        title="Comptes & Profils"
        meta={<span className="text-[12px] text-muted-foreground">Règle stricte : 1 seul administrateur</span>}
        actions={
          <Button variant="primary" icon={Plus} onClick={() => { setSelected(null); setCreating(true); }}>
            Nouveau compte
          </Button>
        }
        filters={
          <>
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher un compte…" className="w-[240px]" />
            <Select size="sm" value={roleFilter} onChange={setRoleFilter} options={ROLE_OPTIONS} />
            <Select size="sm" value={statusFilter} onChange={setStatusFilter} options={STATUS_OPTIONS} />
            {hasFilters ? (
              <Button size="sm" variant="ghost" onClick={() => { setQ(""); setRoleFilter(""); setStatusFilter(""); }}>
                Effacer les filtres
              </Button>
            ) : null}
          </>
        }
      />
      <PageBody flush>
        <DataTable
          rows={rows}
          columns={columns}
          loading={accounts.isLoading}
          getRowId={(a) => a.id}
          selectedId={selected?.id}
          onRowClick={(a) => { setCreating(false); setSelected(a); }}
          empty={<EmptyState icon={Users} title="Aucun compte correspondant" />}
        />
      </PageBody>

      {creating || selected ? (
        <SidePanel
          onClose={() => { setCreating(false); setSelected(null); }}
          title={creating ? "Nouveau compte" : selected?.displayName ?? "Compte"}
          subtitle={selected ? `@${selected.username} · ${AUTH_ROLE_LABEL[selected.role]}` : "Règle : impossible de créer un 2e admin"}
        >
          {creating ? (
            <CreateAccountForm
              onDone={() => {
                setCreating(false);
                void qc.invalidateQueries({ queryKey: ["accounts"] });
              }}
            />
          ) : selected ? (
            <EditAccountPanel
              account={selected}
              onUpdated={(acc) => {
                setSelected(acc);
                void qc.invalidateQueries({ queryKey: ["accounts"] });
              }}
              onDeleted={() => {
                setSelected(null);
                void qc.invalidateQueries({ queryKey: ["accounts"] });
              }}
            />
          ) : null}
        </SidePanel>
      ) : null}
    </Page>
  );
}

function CreateAccountForm({ onDone }: { onDone: () => void }) {
  const clients = useClients();
  const suppliers = useSuppliers();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<AuthRole>("client");
  const [entityId, setEntityId] = useState("");
  const [password, setPassword] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api.accounts.create({
        username: username.trim(),
        displayName: displayName.trim() || undefined,
        role,
        entityType: role === "client" ? "client" : role === "supplier" ? "supplier" : undefined,
        entityId: entityId || undefined,
        password,
      }),
    onSuccess: () => {
      toast.success("Compte créé");
      onDone();
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };

  const clientOpts = (clients.data ?? []).map((c) => ({ value: c.id, label: c.name, hint: c.city }));
  const supplierOpts = (suppliers.data ?? []).map((s) => ({ value: s.id, label: s.name, hint: s.city }));

  return (
    <form onSubmit={submit} className="flex flex-col gap-3.5 p-4">
      <Field label="Identifiant (unique)">
        <Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="ex. cafe-gare" required />
      </Field>
      <Field label="Nom affiché">
        <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="ex. Café de la Gare" />
      </Field>
      <Field label="Rôle" hint="L'administrateur unique existe déjà ; ce formulaire crée client, fournisseur ou commercial.">
        <Select value={role} onChange={(v) => { setRole(v as AuthRole); setEntityId(""); }} options={CREATABLE_ROLES} />
      </Field>
      {role === "client" ? (
        <Field label="Client rattaché">
          <Select value={entityId} onChange={setEntityId} placeholder="Choisir le client…" options={clientOpts} />
        </Field>
      ) : null}
      {role === "supplier" ? (
        <Field label="Fournisseur rattaché">
          <Select value={entityId} onChange={setEntityId} placeholder="Choisir le fournisseur…" options={supplierOpts} />
        </Field>
      ) : null}
      <Field label="Mot de passe initial">
        <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="4 caractères min." required />
      </Field>
      <Button type="submit" variant="primary" loading={create.isPending}>
        Créer le compte
      </Button>
    </form>
  );
}

function EditAccountPanel({ account, onUpdated, onDeleted }: { account: Account; onUpdated: (a: Account) => void; onDeleted: () => void }) {
  const [displayName, setDisplayName] = useState(account.displayName);
  const [newPw, setNewPw] = useState("");
  const isSoleAdmin = account.role === "admin";

  const save = useMutation({
    mutationFn: (patch: { displayName?: string; active?: boolean }) => api.accounts.update(account.id, patch),
    onSuccess: (acc) => { toast.success("Compte mis à jour"); onUpdated(acc); },
  });
  const resetPw = useMutation({
    mutationFn: () => api.accounts.resetPassword(account.id, newPw),
    onSuccess: (acc) => { setNewPw(""); toast.success("Mot de passe réinitialisé"); onUpdated(acc); },
  });
  const remove = useMutation({
    mutationFn: () => api.accounts.remove(account.id),
    onSuccess: () => { toast.success("Compte supprimé"); onDeleted(); },
  });

  return (
    <div className="flex flex-col gap-5 p-4">
      {isSoleAdmin ? (
        <div className="flex items-start gap-2 rounded-[4px] border border-success/40 bg-success/10 p-3 text-[12px] text-foreground">
          <ShieldCheck size={15} className="mt-0.5 shrink-0 text-success" />
          <span>Administrateur unique : impossible de le rétrograder, le désactiver ou le supprimer.</span>
        </div>
      ) : null}

      <Section title="Profil">
        <div className="flex flex-col gap-3">
          <Field label="Nom affiché">
            <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </Field>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="primary" loading={save.isPending} onClick={() => save.mutate({ displayName })}>
              Enregistrer
            </Button>
            <Button
              size="sm"
              disabled={isSoleAdmin || save.isPending}
              onClick={() => save.mutate({ active: !account.active })}
            >
              {account.active ? "Désactiver" : "Réactiver"}
            </Button>
          </div>
        </div>
      </Section>

      <Section title="Sécurité">
        <div className="flex items-center gap-2">
          <Input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} placeholder="Nouveau mot de passe…" className="flex-1" />
          <Button size="sm" icon={KeyRound} disabled={newPw.length < 4} loading={resetPw.isPending} onClick={() => resetPw.mutate()}>
            Réinitialiser
          </Button>
        </div>
      </Section>

      <Section title="Zone sensible">
        <Button size="sm" variant="danger" icon={Trash2} disabled={isSoleAdmin} loading={remove.isPending} onClick={() => remove.mutate()}>
          {isSoleAdmin ? "Admin unique protégé" : "Supprimer le compte"}
        </Button>
      </Section>
    </div>
  );
}
