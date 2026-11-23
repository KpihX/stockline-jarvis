/** Latency chips: per turn (from agent_done.timings) and the running average across turns. */
import type { TurnTimings } from "@kit/shared";
import { Gauge } from "lucide-react";
import { cn } from "@/lib/cn";
import { SECTION_LABEL } from "@/ui";
import type { VoiceTurn } from "@/features/assistant/useVoiceSession";

type Key = Exclude<keyof TurnTimings, "firstSoundKind"> | "perceivedMs";
const METRICS: { key: Key; label: string; title: string }[] = [
  { key: "sttMs", label: "STT", title: "Transcription de la parole de l'appelant" },
  { key: "llmFirstTokenMs", label: "LLM 1er", title: "Premier token du modèle" },
  { key: "llmTotalMs", label: "LLM", title: "Modèle, outils compris" },
  { key: "ttsFirstByteMs", label: "TTS 1er", title: "Premier octet audio de la première phrase synthétisée (un filler en cache n'en compte pas)" },
  { key: "totalMs", label: "Total", title: "Fin de parole de l'appelant → premier octet audio de l'agent (serveur). Peut être une phrase d'attente (filler) : voir la puce « filler »." },
  { key: "answerMs", label: "Réponse", title: "Fin de parole de l'appelant → premier octet de la vraie réponse (égal à Total sans filler)" },
  { key: "perceivedMs", label: "Perçu", title: "Relâchement de la touche → l'agent parle dans le navigateur" },
];

const value = (t: VoiceTurn, k: Key): number | undefined => (k === "perceivedMs" ? t.perceivedMs : t.timings?.[k]);
/** "Réponse" is only worth a chip when a filler spoke first; averaged over the turns that have one. */
const shown = (t: VoiceTurn, k: Key) => (k === "answerMs" ? t.timings?.firstSoundKind === "filler" : true);

const fmtTokens = (n: number) => (n < 1000 ? `${n}` : `${(n / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })}k`);
const fmtEur = (e: number) => `${e.toLocaleString("fr-FR", { minimumFractionDigits: 4, maximumFractionDigits: 4 })} €`;

function TextChip({ label, text, title, className }: { label: string; text?: string; title?: string; className?: string }) {
  return (
    <span title={title} className={cn("inline-flex h-[18px] items-center gap-1 rounded-[3px] border border-border bg-card px-1.5 font-mono text-[10.5px]", className)}>
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("num", text == null ? "text-muted-foreground/60" : "text-secondary-foreground")}>{text ?? "—"}</span>
    </span>
  );
}

/** Total latency tone: < 1,5 s fast, < 3 s acceptable, else slow. */
function tone(k: Key, ms: number) {
  if (k !== "totalMs" && k !== "perceivedMs") return "text-secondary-foreground";
  return ms < 1500 ? "text-success" : ms < 3000 ? "text-warning" : "text-destructive";
}

export const fmtMs = (ms: number) => (ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s`);

export function Chip({ label, ms, k, title, className }: { label: string; ms?: number; k: Key; title?: string; className?: string }) {
  return (
    <span title={title} className={cn("inline-flex h-[18px] items-center gap-1 rounded-[3px] border border-border bg-card px-1.5 font-mono text-[10.5px]", className)}>
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("num", ms == null ? "text-muted-foreground/60" : tone(k, ms))}>{ms == null ? "—" : fmtMs(ms)}</span>
    </span>
  );
}

export function TurnChips({ t }: { t: VoiceTurn }) {
  if (!t.timings && t.perceivedMs == null) return null;
  const c = t.cost;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {METRICS.map((m) => {
        const ms = shown(t, m.key) ? value(t, m.key) : undefined;
        return ms == null ? null : <Chip key={m.key} k={m.key} label={m.label} ms={ms} title={m.title} />;
      })}
      {t.timings?.firstSoundKind === "filler" && <TextChip label="1er son" text="filler" title="Le Total mesure une phrase d'attente pré-enregistrée, pas la réponse (voir « Réponse »)" />}
      {c?.llmCacheReadTokens != null && (
        <TextChip label="Cache" text={fmtTokens(c.llmCacheReadTokens)} title={`Tokens lus dans le cache de prompt (≈ 5 % du prix d'entrée). Lus : ${c.llmCacheReadTokens}, non cachés : ${c.llmInputTokens ?? 0}, écrits : ${c.llmCacheCreationTokens ?? 0}, sortie : ${c.llmOutputTokens ?? 0}`} />
      )}
      {c?.estimatedEur != null && (
        <TextChip label="Coût" text={fmtEur(c.estimatedEur)} title={`ESTIMATION au tarif public (apps/ai/app/pricing.py) : LLM + STT ${c.sttSeconds ?? 0} s + TTS ${c.ttsChars ?? 0} caractères. Hors préchauffage.`} />
      )}
    </div>
  );
}

/** Strip above the timeline: running averages (and the count of measured turns). */
export function MetricsBar({ turns }: { turns: VoiceTurn[] }) {
  const measured = turns.filter((t) => t.timings);
  const mean = (xs: (number | undefined)[]) => {
    const ys = xs.filter((x): x is number => x != null);
    return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : undefined;
  };
  const avg = (k: Key) => mean(turns.map((t) => (shown(t, k) ? value(t, k) : undefined)));
  const cache = mean(turns.map((t) => t.cost?.llmCacheReadTokens));
  const eur = mean(turns.map((t) => t.cost?.estimatedEur));
  const eurTotal = turns.reduce((a, t) => a + (t.cost?.estimatedEur ?? 0), 0);
  return (
    <div className="flex min-h-10 shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-5 py-1.5">
      <span className={cn(SECTION_LABEL, "flex items-center gap-1.5")}>
        <Gauge size={13} strokeWidth={1.75} />
        Latence moyenne
      </span>
      <span className="num text-[11.5px] text-muted-foreground">{measured.length ? `${measured.length} tour${measured.length > 1 ? "s" : ""}` : "aucun tour mesuré"}</span>
      <div className="flex min-w-0 flex-wrap items-center gap-1">
        {METRICS.map((m) => <Chip key={m.key} k={m.key} label={m.label} ms={avg(m.key)} title={m.title} />)}
        <TextChip label="Cache" text={cache == null ? undefined : fmtTokens(Math.round(cache))} title="Tokens de prompt lus dans le cache, en moyenne par tour" />
        <TextChip label="Coût" text={eur == null ? undefined : fmtEur(eur)} title={`Estimation moyenne par tour (tarif public, hors préchauffage). Total de la session : ${fmtEur(eurTotal)}`} />
      </div>
    </div>
  );
}
