/**
 * CallerBadge — « qui est au bout du fil ? » : the header control that sets the DECLARED identity (role, client, name) used by the
 * voice call, the chat panel and the voice command. Honest by design: this is a demo declaration (no telephony, no caller-ID);
 * the AI service enforces what each role may do, whatever the model is told or says (apps/ai/app/policy.py).
 */
import { useEffect, useRef, useState } from "react";
import { ShieldAlert, UserRound } from "lucide-react";
import type { CallerRole } from "@kit/shared";
import { cn } from "@/lib/cn";
import { useClients } from "@/lib/queries";
import { AnchoredPopover, Button, Dot, Field, Input, Segmented, Select, type Tone } from "@/ui";
import { caller, callerLabel, callerWire, ROLE_HELP, ROLE_LABEL, useCaller } from "./caller";

const ROLE_OPTIONS = (["unknown", "client", "sales", "direction"] as const).map((id) => ({ id, label: id === "unknown" ? "Inconnu" : ROLE_LABEL[id] })); // short: it must fit one line
const TONE: Record<CallerRole, Tone> = { unknown: "warning", client: "info", sales: "violet", direction: "violet" };

export function CallerBadge({ effectiveRole, className }: { effectiveRole?: CallerRole; className?: string }) {
  const c = useCaller();
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const clients = useClients();

  // Close on a click outside (the client Select portals its own list: that is "inside") and on Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Element | null;
      if (!t || anchorRef.current?.contains(t) || panelRef.current?.contains(t) || t.closest('[role="listbox"]')) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const options = (clients.data ?? []).map((cl) => ({ value: cl.id, label: cl.name, hint: cl.city }));
  const nameOf = (id: string) => clients.data?.find((cl) => cl.id === id)?.name;
  const wire = callerWire(c);
  const mismatch = effectiveRole !== undefined && effectiveRole !== wire.role;  // the server enforces something else than what we declared
  const incomplete = c.role === "client" && !c.clientId;

  return (
    <div ref={anchorRef} className={cn("shrink-0", className)}>
      <Button
        size="sm"
        variant="default"
        icon={UserRound}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="dialog"
        title="Identité déclarée (démo) : le serveur applique les droits du rôle choisi"
      >
        <Dot tone={mismatch ? "destructive" : incomplete ? "warning" : TONE[c.role]} />
        <span className="max-w-[200px] truncate">{callerLabel(c)}</span>
        {c.role !== "unknown" ? <span className="hidden text-[11px] font-normal text-muted-foreground 2xl:inline">déclaré</span> : null}
      </Button>
      <AnchoredPopover anchorRef={anchorRef} open={open} matchWidth={false} width={352} maxHeight={520} role="dialog" aria-label="Identité de l'appelant">
        <div ref={panelRef} className="flex flex-col gap-3 p-3">
          <div>
            <div className="text-[13px] font-semibold">Qui est au bout du fil ?</div>
            <div className="mt-0.5 flex items-center gap-1 text-[11.5px] text-warning">
              <ShieldAlert size={12} strokeWidth={1.75} className="shrink-0" />
              Identité déclarée (démo)
            </div>
          </div>
          <Segmented<CallerRole>
            value={c.role}
            options={ROLE_OPTIONS}
            onChange={(role) => caller.set(role === "unknown" ? { role } : { role, clientId: c.clientId, actorName: role === c.role ? c.actorName : undefined })}
            className="self-start"
          />
          <p className="text-[12px] leading-[17px] text-muted-foreground">{ROLE_HELP[c.role]}</p>
          {c.role === "client" || c.role === "sales" || c.role === "direction" ? (
            <Field label={c.role === "client" ? "Client (obligatoire)" : "Client en cours (facultatif)"}>
              <Select
                size="sm"
                value={c.clientId ?? ""}
                placeholder={c.role === "client" ? "Choisir le client…" : "Aucun"}
                options={options}
                onChange={(id) =>
                  caller.set({ ...c, clientId: id || undefined, actorName: c.role === "client" ? (id ? nameOf(id) : undefined) : c.actorName })
                }
              />
            </Field>
          ) : null}
          {c.role === "sales" || c.role === "direction" ? (
            <Field label="Votre nom (facultatif)" hint="Signe les écritures de l'agent dans l'ERP.">
              <NameField key={c.role} value={c.actorName ?? ""} placeholder={c.role === "sales" ? "ex. Thibault" : "ex. Claire"} onCommit={(actorName) => caller.set({ ...c, actorName })} />
            </Field>
          ) : null}
          {incomplete ? (
            <p className="text-[12px] text-warning">Choisissez le client : en attendant, l'agent traite l'appelant comme non identifié.</p>
          ) : mismatch ? (
            <p className="text-[12px] text-destructive">Le serveur applique « {ROLE_LABEL[effectiveRole!]} » et non « {ROLE_LABEL[wire.role]} ».</p>
          ) : null}
          <p className="border-t border-border pt-2 text-[11.5px] leading-[16px] text-muted-foreground">
            Aucune téléphonie ni numéro appelant dans ce hackathon : l'identité est simplement déclarée ici. L'agent n'est pas cru sur parole,
            le serveur refuse ce que le rôle n'autorise pas. En production, l'appelant serait reconnu par son numéro ou une authentification.
          </p>
        </div>
      </AnchoredPopover>
    </div>
  );
}

/** Committed on blur / Enter, not per keystroke: every identity change restarts the voice session and clears the chat. */
function NameField({ value, placeholder, onCommit }: { value: string; placeholder: string; onCommit: (v: string) => void }) {
  const [v, setV] = useState(value);
  const commit = () => { if (v.trim() !== value) onCommit(v.trim()); };
  return (
    <Input
      size="sm"
      value={v}
      onChange={(e) => setV(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }}
      placeholder={placeholder}
    />
  );
}
