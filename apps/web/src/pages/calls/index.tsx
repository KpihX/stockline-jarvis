/**
 * /calls — WhatsApp VoIP Call Desk (Manager & Admin ONLY).
 * Bidirectional WebRTC Opus 48 kHz + VAD STT + Jev routing + Live J.A.R.V.I.S ERP copilot & warnings.
 * Uses ONLY design-system primitives from @/ui.
 */
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  AlertTriangle, ArrowUpRight, CheckCircle2, Mic, MicOff, Phone, PhoneCall, PhoneIncoming,
  PhoneOff, QrCode, Send, ShieldAlert, Sparkles, UserCheck, Volume2,
} from "lucide-react";
import { fmtDateLong } from "@/lib/format";
import { useClients } from "@/lib/queries";
import { Button, Dot, EmptyState, Field, Input, Page, PageBody, PageHeader, Section, Select, StatusDot } from "@/ui";
import { useAuth } from "@/features/auth/auth-store";
import { callsStore, useCalls } from "@/features/calls/calls-store";

const PRESET_SCENARIOS = [
  {
    id: "payet-trap",
    label: "Le Refuge Payet · Hors saison (200 kg frites au 1er déc.)",
    clientId: "cli_0082",
    phone: "0695497769",
    text: "Bonjour c'est Le Refuge Payet, mets-moi 200 kilos de frites surgelées pour le 1er décembre.",
  },
  {
    id: "usual",
    label: "Hôtel des Neiges · Raclette & jambon cru",
    clientId: "cli_0013",
    phone: "0623505859",
    text: "Bonjour, c'est Pauline de l'Hôtel des Neiges, il me faut 25 kilos de raclette tranchée et 10 kilos de jambon cru pour jeudi.",
  },
  {
    id: "blocked",
    label: "La Bergerie des Deux Alpes · Compte bloqué impayés",
    clientId: "cli_0003",
    phone: "0651279340",
    text: "Salut c'est Ludovic de La Bergerie des Deux Alpes, envoie-moi 30 kilos de raclette en meule pour demain.",
  },
];

export default function CallsPage() {
  const { account } = useAuth();
  const navigate = useNavigate();
  const cs = useCalls();
  const clientsQ = useClients();

  const [simClientId, setSimClientId] = useState("cli_0082");
  const [simPhone, setSimPhone] = useState("0695497769");
  const [simText, setSimText] = useState(PRESET_SCENARIOS[0].text);
  const [injectMsg, setInjectMsg] = useState("Ajoute aussi 15 kilos de raclette tranchée s'il vous plaît.");
  const [injectSpeaker, setInjectSpeaker] = useState<"client" | "manager">("client");
  const [bindCid, setBindCid] = useState("");

  useEffect(() => {
    callsStore.connectStream();
    void callsStore.refreshCalls();
    void callsStore.refreshWa();
  }, []);

  if (account?.role !== "manager" && account?.role !== "admin") {
    return (
      <Page>
        <PageHeader title="Appels WhatsApp" />
        <PageBody>
          <EmptyState
            icon={ShieldAlert}
            title="Accès réservé aux commerciaux et à la direction"
            description="La centrale d'appels WhatsApp VoIP est réservée à l'équipe interne."
          />
        </PageBody>
      </Page>
    );
  }

  const clientOpts = useMemo(
    () => (clientsQ.data ?? []).map((c) => ({ value: c.id, label: c.name, hint: `${c.city} · ${c.contacts?.[0]?.phone || ""}` })),
    [clientsQ.data],
  );

  const displayedCall = useMemo(() => {
    if (cs.activeCall && (!cs.selectedCallId || cs.selectedCallId === cs.activeCall.callId)) return cs.activeCall;
    return cs.recentCalls.find((c) => c.callId === cs.selectedCallId) ?? cs.activeCall ?? cs.recentCalls[0] ?? null;
  }, [cs.activeCall, cs.recentCalls, cs.selectedCallId]);

  const isLive = displayedCall && (displayedCall.status === "ringing" || displayedCall.status === "active");

  const pickPreset = (presetId: string) => {
    const p = PRESET_SCENARIOS.find((x) => x.id === presetId);
    if (!p) return;
    setSimClientId(p.clientId);
    setSimPhone(p.phone);
    setSimText(p.text);
  };

  const onSimSubmit = (e: FormEvent) => {
    e.preventDefault();
    void callsStore.simulateCall(simPhone, simText, simClientId);
  };

  const onInjectSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!displayedCall || !injectMsg.trim()) return;
    void callsStore.injectText(displayedCall.callId, injectMsg.trim(), injectSpeaker);
    setInjectMsg("");
  };

  const waTone = cs.wa.status === "connected" ? "success" : cs.wa.status === "qr_pending" ? "warning" : "muted";
  const waLabel = cs.wa.status === "connected"
    ? `WhatsApp connecté (${cs.wa.phone.split(":")[0] || "prêt"})`
    : cs.wa.status === "qr_pending"
      ? "QR prêt à scanner"
      : cs.wa.status === "unavailable"
        ? "Service WA hors ligne"
        : "WhatsApp non appairé";

  return (
    <Page>
      <PageHeader
        title="Appels WhatsApp VoIP"
        icon={<PhoneIncoming size={16} strokeWidth={1.75} />}
        meta={
          <span className="flex items-center gap-2 text-[12px] text-muted-foreground">
            <Dot tone={waTone} pulse={cs.wa.status === "connected"} />
            <span>{waLabel}</span>
          </span>
        }
        actions={
          <div className="flex items-center gap-2">
            <Button size="sm" variant="default" icon={QrCode} onClick={() => navigate("/settings")}>
              {cs.wa.status === "connected" ? "Réglages WA" : "Scanner QR WhatsApp"}
            </Button>
          </div>
        }
      />

      <PageBody flush>
        <div className="grid grid-cols-1 gap-6 p-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          {/* Left main column: Live Call + Transcript + J.A.R.V.I.S Copilot */}
          <div className="flex min-w-0 flex-col gap-5">
            {displayedCall ? (
              <div className="rounded-[6px] border border-border bg-card">
                {/* Call Header */}
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <Dot
                        tone={displayedCall.status === "active" ? "success" : displayedCall.status === "ringing" ? "warning" : "muted"}
                        pulse={!!isLive}
                      />
                      <span className="text-[15px] font-semibold text-foreground">
                        {displayedCall.clientName || displayedCall.phoneNumber}
                      </span>
                      <span className="font-mono text-[12px] text-muted-foreground">{displayedCall.phoneNumber}</span>
                      {displayedCall.clientId ? (
                        <Link
                          to={`/clients/${displayedCall.clientId}`}
                          className="inline-flex items-center gap-1 rounded-[3px] border border-primary/30 bg-primary/10 px-1.5 py-0.5 font-mono text-[11px] font-medium text-primary hover:underline"
                        >
                          {displayedCall.clientId} <ArrowUpRight size={11} />
                        </Link>
                      ) : (
                        <span className="rounded-[3px] border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-[11px] font-medium text-warning">
                          Numéro non associé
                        </span>
                      )}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-[11.5px] text-muted-foreground">
                      <span className="font-mono">{displayedCall.callId}</span>
                      <span>·</span>
                      <span>Mode : {displayedCall.mode === "simulation" ? "Simulation audio" : "WhatsApp VoIP réel"}</span>
                      <span>·</span>
                      <span>WebRTC Opus 48 kHz ({cs.webrtcState})</span>
                    </div>
                  </div>

                  {/* Call Controls */}
                  <div className="flex flex-wrap items-center gap-2">
                    {displayedCall.status === "ringing" ? (
                      <>
                        <Button
                          variant="primary"
                          icon={PhoneCall}
                          loading={cs.busy}
                          onClick={() => void callsStore.answerCall(displayedCall.callId)}
                        >
                          Décrocher
                        </Button>
                        <Button
                          variant="danger"
                          icon={PhoneOff}
                          disabled={cs.busy}
                          onClick={() => void callsStore.rejectCall(displayedCall.callId)}
                        >
                          Refuser
                        </Button>
                      </>
                    ) : displayedCall.status === "active" ? (
                      <>
                        <Button
                          size="sm"
                          variant={displayedCall.muted ? "danger" : "default"}
                          icon={displayedCall.muted ? MicOff : Mic}
                          onClick={() => void callsStore.toggleMute(displayedCall.callId, !displayedCall.muted)}
                        >
                          {displayedCall.muted ? "Micro coupé" : "Micro actif"}
                        </Button>
                        <Button
                          size="sm"
                          variant="default"
                          icon={Sparkles}
                          loading={cs.busy}
                          onClick={() => void callsStore.commitCall(displayedCall.callId)}
                        >
                          Extraire vers ERP
                        </Button>
                        <Button
                          size="sm"
                          variant="danger"
                          icon={PhoneOff}
                          disabled={cs.busy}
                          onClick={() => void callsStore.hangupCall(displayedCall.callId)}
                        >
                          Raccrocher
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="sm"
                        variant="default"
                        icon={Sparkles}
                        loading={cs.busy}
                        onClick={() => void callsStore.commitCall(displayedCall.callId)}
                      >
                        Ré-analyser l'appel
                      </Button>
                    )}
                  </div>
                </div>

                {/* Bind unknown caller to ERP client */}
                {!displayedCall.clientId ? (
                  <div className="flex flex-wrap items-center gap-2 border-b border-border bg-warning/[.06] px-4 py-2.5 text-[12px]">
                    <UserCheck size={14} className="shrink-0 text-warning" />
                    <span className="font-medium text-foreground">Associer ce numéro ({displayedCall.phoneNumber}) à un client ERP :</span>
                    <Select
                      size="sm"
                      value={bindCid}
                      onChange={setBindCid}
                      placeholder="Choisir le client…"
                      options={clientOpts}
                      className="w-[260px]"
                    />
                    <Button
                      size="sm"
                      variant="primary"
                      disabled={!bindCid}
                      onClick={() => void callsStore.bindCallClient(displayedCall.callId, bindCid)}
                    >
                      Associer
                    </Button>
                  </div>
                ) : null}

                {/* J.A.R.V.I.S Live Copilot Card + Warnings + Linked Orders */}
                {(displayedCall.copilotNote || displayedCall.warnings?.length || displayedCall.linkedCommands?.length) ? (
                  <div className="flex flex-col gap-2.5 border-b border-border bg-gradient-to-r from-violet/[.05] to-primary/[.04] px-4 py-3">
                    <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[.06em] text-violet">
                      <Sparkles size={13} />
                      <span>Copilote J.A.R.V.I.S en direct · Mise à jour ERP</span>
                    </div>
                    {displayedCall.copilotNote ? (
                      <p className="text-[13px] leading-[19px] text-foreground">{displayedCall.copilotNote}</p>
                    ) : null}
                    {displayedCall.warnings?.map((w, i) => (
                      <div
                        key={`${w.code}-${i}`}
                        className="flex items-start gap-2 rounded-[4px] border border-warning/40 bg-warning/10 px-3 py-2 text-[12px] text-foreground"
                      >
                        <AlertTriangle size={14} className="mt-0.5 shrink-0 text-warning" />
                        <span>
                          <strong className="font-mono text-warning">{w.code}</strong> · {w.message}
                        </span>
                      </div>
                    ))}
                    {displayedCall.linkedCommands?.length ? (
                      <div className="flex flex-wrap gap-2">
                        {displayedCall.linkedCommands.map((cmd) => (
                          <Link
                            key={cmd.id}
                            to={`/orders/${cmd.id}`}
                            className="inline-flex items-center gap-2 rounded-[4px] border border-primary/30 bg-card px-2.5 py-1.5 text-[12px] font-medium text-foreground transition-colors hover:border-primary"
                          >
                            <CheckCircle2 size={13} className="text-primary" />
                            <span className="font-mono">{cmd.number}</span>
                            <StatusDot kind="order" value={cmd.status as "draft" | "confirmed"} />
                            {cmd.deliveryDate ? <span className="text-muted-foreground">{cmd.deliveryDate}</span> : null}
                            <ArrowUpRight size={12} className="text-muted-foreground" />
                          </Link>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}

                {/* Bicanal Live Transcript */}
                <div className="flex flex-col gap-2.5 p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-[11.5px] font-semibold uppercase tracking-[.06em] text-muted-foreground">
                      Transcription bicanale en direct
                    </span>
                    <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      <Volume2 size={12} /> VAD 16 kHz → STT + Jev + ERP
                    </span>
                  </div>
                  {displayedCall.transcripts.length === 0 ? (
                    <div className="rounded-[4px] border border-dashed border-border px-4 py-6 text-center text-[12.5px] text-muted-foreground">
                      {displayedCall.status === "ringing"
                        ? "Cliquez sur « Décrocher » pour ouvrir le pont WebRTC et démarrer l'écoute."
                        : "En attente de parole… Parlez dans WhatsApp / le micro ou injectez une phrase ci-dessous."}
                    </div>
                  ) : (
                    <div className="flex max-h-[320px] flex-col gap-2 overflow-y-auto pr-1">
                      {displayedCall.transcripts.map((t) => (
                        <div
                          key={t.id}
                          className={`flex flex-col gap-1 rounded-[5px] border px-3 py-2 text-[12.5px] ${
                            t.speaker === "manager"
                              ? "ml-8 border-primary/30 bg-primary/[.05]"
                              : "mr-8 border-border bg-muted/40"
                          }`}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
                            <span className="font-semibold text-foreground">
                              {t.speaker === "manager" ? "Gestionnaire (ERP)" : displayedCall.clientName || "Client"}
                            </span>
                            <span className="flex items-center gap-1.5 font-mono">
                              {t.jevMs != null ? (
                                <span className="rounded-[3px] border border-violet/30 bg-violet/10 px-1 py-0.2 text-[10px] text-violet">
                                  Jev {t.jevMs} ms · {t.jevRoute}
                                </span>
                              ) : null}
                              <span>{t.durationMs} ms</span>
                            </span>
                          </div>
                          <p className="text-foreground">{t.text}</p>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Inject utterance during an active call */}
                  {displayedCall.status === "active" ? (
                    <form onSubmit={onInjectSubmit} className="mt-2 flex flex-wrap items-center gap-2 border-t border-border pt-3">
                      <Select
                        size="sm"
                        value={injectSpeaker}
                        onChange={(v) => setInjectSpeaker(v as "client" | "manager")}
                        options={[
                          { value: "client", label: "Parole Client" },
                          { value: "manager", label: "Parole Gestionnaire" },
                        ]}
                        className="w-[165px]"
                      />
                      <Input
                        value={injectMsg}
                        onChange={(e) => setInjectMsg(e.target.value)}
                        placeholder="Tester une réplique vocale dans l'appel…"
                        className="min-w-[240px] flex-1"
                      />
                      <Button type="submit" size="sm" variant="primary" icon={Send}>
                        Dire dans l'appel
                      </Button>
                    </form>
                  ) : null}
                </div>
              </div>
            ) : (
              <div className="rounded-[6px] border border-border bg-card p-6">
                <EmptyState
                  icon={Phone}
                  title="Aucun appel WhatsApp en cours"
                  description={
                    cs.wa.status === "connected"
                      ? "Appelez votre numéro WhatsApp appairé depuis un autre téléphone (ex. votre compte 337) ou lancez une simulation ci-contre."
                      : "Connectez WhatsApp par QR Code dans Réglages ou testez dès maintenant avec le simulateur d'appel."
                  }
                  action={
                    <Button variant="primary" icon={QrCode} onClick={() => navigate("/settings")}>
                      Configurer WhatsApp (QR Code)
                    </Button>
                  }
                />
              </div>
            )}

            {/* Recent Call History */}
            <Section title={`Historique des appels (${cs.recentCalls.length})`}>
              <div className="divide-y divide-border overflow-hidden rounded-[6px] border border-border bg-card">
                {cs.recentCalls.length === 0 ? (
                  <div className="px-4 py-4 text-[12.5px] text-muted-foreground">Aucun appel enregistré pour le moment.</div>
                ) : (
                  cs.recentCalls.map((c) => (
                    <button
                      key={c.callId}
                      type="button"
                      onClick={() => callsStore.selectCall(c.callId)}
                      className={`flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left text-[12.5px] transition-colors hover:bg-muted/60 ${
                        displayedCall?.callId === c.callId ? "bg-muted/70" : ""
                      }`}
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 font-medium text-foreground">
                          <span className="truncate">{c.clientName || c.phoneNumber}</span>
                          <span className="font-mono text-[11px] text-muted-foreground">{c.phoneNumber}</span>
                        </div>
                        <div className="truncate text-[11.5px] text-muted-foreground">
                          {c.copilotNote || c.transcripts?.[0]?.text || "Aucune transcription"}
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-2.5">
                        {c.linkedCommands?.length ? (
                          <span className="rounded-[3px] border border-primary/30 bg-primary/10 px-1.5 py-0.5 font-mono text-[10.5px] text-primary">
                            {c.linkedCommands.length} cmd
                          </span>
                        ) : null}
                        <span className="text-[11px] text-muted-foreground">{fmtDateLong(c.startedAt.slice(0, 10))}</span>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </Section>
          </div>

          {/* Right rail: 1-Click Call Simulator */}
          <div className="flex flex-col gap-5">
            <Section title="Simulateur d'appel client (démo 1-clic)">
              <form onSubmit={onSimSubmit} className="flex flex-col gap-3 rounded-[6px] border border-border bg-card p-4">
                <p className="text-[12px] leading-[17px] text-muted-foreground">
                  Déclenche une vraie sonnerie WebRTC + synthèse audio 16 kHz + VAD + STT + extraction J.A.R.V.I.S sans dépendre du réseau cellulaire.
                </p>
                <Field label="Scénario rapide">
                  <Select
                    value={PRESET_SCENARIOS.find((p) => p.clientId === simClientId)?.id || "payet-trap"}
                    onChange={pickPreset}
                    options={PRESET_SCENARIOS.map((p) => ({ value: p.id, label: p.label }))}
                  />
                </Field>
                <Field label="Client ERP appelant">
                  <Select value={simClientId} onChange={setSimClientId} options={clientOpts} placeholder="Choisir un client…" />
                </Field>
                <Field label="Numéro affiché">
                  <Input value={simPhone} onChange={(e) => setSimPhone(e.target.value)} placeholder="0695497769" />
                </Field>
                <Field label="Phrase du client (synthétisée à 16 kHz)">
                  <textarea
                    value={simText}
                    onChange={(e) => setSimText(e.target.value)}
                    rows={3}
                    className="w-full rounded-[4px] border border-border bg-background px-2.5 py-2 text-[12.5px] text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                </Field>
                <Button type="submit" variant="primary" icon={PhoneIncoming} loading={cs.busy}>
                  Faire sonner l'ERP
                </Button>
              </form>
            </Section>
          </div>
        </div>
      </PageBody>
    </Page>
  );
}
