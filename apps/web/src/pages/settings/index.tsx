/**
 * /settings — WhatsApp Baileys QR Code Pairing & Test Phone Bindings (Manager & Admin ONLY).
 * Uses ONLY design-system primitives from @/ui.
 */
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Link2, Phone, Power, QrCode, RefreshCw, ShieldAlert, Smartphone } from "lucide-react";
import { useClients } from "@/lib/queries";
import { Button, Dot, EmptyState, Field, Input, Page, PageBody, PageHeader, Section, Select } from "@/ui";
import { useAuth } from "@/features/auth/auth-store";
import { callsStore, useCalls } from "@/features/calls/calls-store";

export default function SettingsPage() {
  const { account } = useAuth();
  const cs = useCalls();
  const clientsQ = useClients();
  const [phoneInput, setPhoneInput] = useState("33745717350");
  const [clientId, setClientId] = useState("cli_0082");

  const aiHealth = useQuery({
    queryKey: ["ai", "health"],
    queryFn: async () => {
      const r = await fetch("/ai/health");
      return r.ok ? r.json() : null;
    },
    staleTime: 30_000,
  });

  useEffect(() => {
    callsStore.connectStream();
    void callsStore.refreshWa();
    void callsStore.refreshConfig();
    const id = window.setInterval(() => {
      void callsStore.refreshWa();
    }, 4500);
    return () => window.clearInterval(id);
  }, []);

  if (account?.role !== "manager" && account?.role !== "admin") {
    return (
      <Page>
        <PageHeader title="Paramètres WhatsApp" />
        <PageBody>
          <EmptyState
            icon={ShieldAlert}
            title="Accès réservé aux commerciaux et à la direction"
            description="L'appairage WhatsApp et la centrale d'appels sont réservés à l'équipe interne."
          />
        </PageBody>
      </Page>
    );
  }

  const clientOpts = useMemo(
    () => (clientsQ.data ?? []).map((c) => ({ value: c.id, label: c.name, hint: c.city })),
    [clientsQ.data],
  );

  const onBind = (e: FormEvent) => {
    e.preventDefault();
    if (!phoneInput.trim() || !clientId) return;
    void callsStore.bindPhone(phoneInput.trim(), clientId);
  };

  const connected = cs.wa.status === "connected";

  return (
    <Page>
      <PageHeader
        title="Paramètres WhatsApp & Pont VoIP"
        icon={<QrCode size={16} strokeWidth={1.75} />}
        meta={
          <span className="flex items-center gap-2 text-[12px] text-muted-foreground">
            <Dot tone={connected ? "success" : cs.wa.status === "qr_pending" ? "warning" : "destructive"} pulse={connected} />
            <span>
              {connected
                ? `Connecté · ${cs.wa.phone.split(":")[0]}`
                : cs.wa.status === "qr_pending"
                  ? "QR prêt à scanner"
                  : cs.wa.status === "unavailable"
                    ? "Bridge Node WA indisponible"
                    : "Déconnecté"}
            </span>
          </span>
        }
        actions={
          <Button size="sm" icon={RefreshCw} loading={cs.busy} onClick={() => void callsStore.refreshWa()}>
            Actualiser
          </Button>
        }
      />

      <PageBody>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* 1. WhatsApp QR Code Pairing Card */}
          <Section title="Connexion WhatsApp (Appareils connectés)">
            <div className="flex flex-col gap-4 rounded-[6px] border border-border bg-card p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-[14px] font-semibold text-foreground">Pont Baileys VoIP + WebRTC</h2>
                  <p className="mt-1 text-[12.5px] leading-[18px] text-muted-foreground">
                    Scannez ce QR Code depuis WhatsApp sur votre téléphone (Menu → Appareils connectés → Connecter un appareil) pour recevoir de vrais appels vocaux directement dans l'ERP.
                  </p>
                </div>
                <Smartphone size={20} className="shrink-0 text-primary" />
              </div>

              {connected ? (
                <div className="flex items-center gap-3 rounded-[6px] border border-primary/30 bg-primary/[.06] p-4">
                  <CheckCircle2 size={22} className="shrink-0 text-primary" />
                  <div>
                    <div className="text-[13.5px] font-semibold text-foreground">Session WhatsApp active</div>
                    <div className="font-mono text-[12px] text-muted-foreground">
                      Compte lié : {cs.wa.phone || "connecté"} · Les appels entrants sonnent sur /calls
                    </div>
                  </div>
                </div>
              ) : cs.qrDataUrl ? (
                <div className="flex flex-col items-center gap-3 rounded-[6px] border border-border bg-white p-5">
                  <img src={cs.qrDataUrl} alt="QR Code WhatsApp" className="h-[240px] w-[240px]" />
                  <span className="text-[12px] font-medium text-neutral-700">
                    Scannez ce code avec WhatsApp (valide ~2 min)
                  </span>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-2 rounded-[6px] border border-dashed border-border px-4 py-8 text-center text-[12.5px] text-muted-foreground">
                  <QrCode size={28} className="text-muted-foreground/60" />
                  <span>
                    {cs.wa.status === "unavailable"
                      ? "Le service Node `wa` (port 3001) ne répond pas encore."
                      : "Cliquez sur « Générer un QR Code » pour appairer un compte WhatsApp."}
                  </span>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-2 pt-1">
                <Button variant="primary" icon={QrCode} loading={cs.busy} onClick={() => void callsStore.connectWa(!connected)}>
                  {connected ? "Reconnecter / Nouveau QR" : "Générer un QR Code"}
                </Button>
                {connected ? (
                  <Button variant="danger" icon={Power} loading={cs.busy} onClick={() => void callsStore.disconnectWa()}>
                    Déconnecter
                  </Button>
                ) : null}
              </div>
            </div>
          </Section>

          {/* 2. Phone <-> Client ERP Mapping + Stack Health */}
          <div className="flex flex-col gap-6">
            <Section title="Associer un numéro WhatsApp à un client ERP">
              <form onSubmit={onBind} className="flex flex-col gap-3 rounded-[6px] border border-border bg-card p-5">
                <p className="text-[12.5px] leading-[18px] text-muted-foreground">
                  Lorsqu'un client appelle depuis un numéro de test (ex. votre compte WhatsApp <code className="font-mono">337…</code>), associez-le ici pour que J.A.R.V.I.S charge sa fiche et ses tarifs automatiquement dès la sonnerie.
                </p>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <Field label="Numéro WhatsApp (E.164 ou 07…)">
                    <Input value={phoneInput} onChange={(e) => setPhoneInput(e.target.value)} placeholder="33745717350" required />
                  </Field>
                  <Field label="Client ERP associé">
                    <Select value={clientId} onChange={setClientId} options={clientOpts} placeholder="Choisir un client…" />
                  </Field>
                </div>
                <div>
                  <Button type="submit" size="sm" variant="primary" icon={Link2}>
                    Enregistrer l'association
                  </Button>
                </div>

                {cs.bindings.length ? (
                  <div className="mt-2 divide-y divide-border rounded-[4px] border border-border">
                    {cs.bindings.map((b) => (
                      <div key={b.phoneDigits} className="flex items-center justify-between px-3 py-2 text-[12px]">
                        <span className="flex items-center gap-2 font-mono text-foreground">
                          <Phone size={12} className="text-muted-foreground" /> {b.phoneDigits}
                        </span>
                        <span className="font-medium text-primary">
                          {b.clientName} ({b.clientId})
                        </span>
                      </div>
                    ))}
                  </div>
                ) : null}
              </form>
            </Section>

            <Section title="État de la pile J.A.R.V.I.S">
              <div className="grid grid-cols-2 gap-3 rounded-[6px] border border-border bg-card p-4 text-[12.5px]">
                <div>
                  <div className="text-[11px] text-muted-foreground">Modèle LLM</div>
                  <div className="font-mono font-medium text-foreground">
                    {aiHealth.data?.llm ? `${aiHealth.data.llm.provider}:${aiHealth.data.llm.model}` : "—"}
                  </div>
                </div>
                <div>
                  <div className="text-[11px] text-muted-foreground">STT / TTS</div>
                  <div className="font-mono font-medium text-foreground">
                    {aiHealth.data ? `${aiHealth.data.stt?.provider} / ${aiHealth.data.tts?.provider}` : "—"}
                  </div>
                </div>
                <div>
                  <div className="text-[11px] text-muted-foreground">Pont WebRTC</div>
                  <div className="font-mono font-medium text-foreground">Opus 48 kHz ↔ VAD 16 kHz</div>
                </div>
                <div>
                  <div className="text-[11px] text-muted-foreground">Flux temps réel</div>
                  <div className="font-mono font-medium text-foreground">{cs.streamOpen ? "SSE connecté" : "En attente"}</div>
                </div>
              </div>
            </Section>
          </div>
        </div>
      </PageBody>
    </Page>
  );
}
