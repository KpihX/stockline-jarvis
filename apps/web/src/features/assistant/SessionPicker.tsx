/**
 * Unified SessionPicker — shared by Assistant (sidebar) and Voix (/voice).
 * Full CRUD + accent-folded search over /ai/sessions; switching here updates both surfaces.
 */
import { useEffect, useRef, useState } from "react";
import { AudioLines, Check, MessageSquare, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { AnchoredPopover, Button, Dot, IconButton, Input } from "@/ui";
import { sessionsStore, useSessions } from "./sessions-store";

export function SessionPicker({
  surface,
  onPick,
  onCreate,
  className,
}: {
  surface: "chat" | "voice";
  onPick: (id: string) => void;
  onCreate: () => void;
  className?: string;
}) {
  const { activeId, list, loading } = useSessions();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const anchorRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    void sessionsStore.refresh(query);
  }, [open, query]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node | null;
      if (!t || anchorRef.current?.contains(t) || panelRef.current?.contains(t)) return;
      setOpen(false);
      setEditingId(null);
      setConfirmDeleteId(null);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const active = list.find((s) => s.id === activeId);
  const label = active?.title ?? (activeId ? "Session active" : "Sessions");

  return (
    <div ref={anchorRef} className={cn("shrink-0", className)}>
      <Button
        size="sm"
        variant="default"
        icon={surface === "voice" ? AudioLines : MessageSquare}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="dialog"
        title="Parcourir, rechercher, renommer ou reprendre une session (unifié Assistant & Voix)"
      >
        <span className="max-w-[140px] truncate">{label}</span>
        {list.length ? <span className="num text-[10.5px] text-muted-foreground">({list.length})</span> : null}
      </Button>
      <AnchoredPopover anchorRef={anchorRef} open={open} matchWidth={false} width={360} maxHeight={480} role="dialog" aria-label="Sessions de conversation">
        <div ref={panelRef} className="flex flex-col gap-2 p-3">
          <div className="flex items-center justify-between gap-2">
            <div>
              <div className="text-[13px] font-semibold">Sessions unifiées</div>
              <div className="text-[11px] text-muted-foreground">Partagées entre l'Assistant et la Voix</div>
            </div>
            <Button
              size="sm"
              variant="primary"
              icon={Plus}
              onClick={() => {
                setOpen(false);
                onCreate();
              }}
            >
              Nouvelle
            </Button>
          </div>
          <div className="relative">
            <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Rechercher par client, produit, commande…"
              className="h-8 pl-7 text-[12px]"
            />
          </div>
          <div className="max-h-[310px] divide-y divide-border overflow-y-auto rounded-[4px] border border-border">
            {loading && list.length === 0 ? (
              <div className="p-3 text-center text-[12px] text-muted-foreground">Chargement…</div>
            ) : list.length === 0 ? (
              <div className="p-3 text-center text-[12px] text-muted-foreground">Aucune session trouvée.</div>
            ) : (
              list.map((s) => {
                const isActive = s.id === activeId;
                const isEditing = editingId === s.id;
                const isDel = confirmDeleteId === s.id;
                return (
                  <div
                    key={s.id}
                    className={cn("flex flex-col gap-1 px-2.5 py-2 text-[12px] transition-colors", isActive ? "bg-row-selected" : "hover:bg-muted/60")}
                  >
                    <div className="flex items-center gap-1.5">
                      <Dot tone={s.surface === "voice" ? "violet" : "info"} />
                      {isEditing ? (
                        <form
                          className="flex flex-1 items-center gap-1"
                          onSubmit={(e) => {
                            e.preventDefault();
                            if (draftTitle.trim()) void sessionsStore.rename(s.id, draftTitle.trim());
                            setEditingId(null);
                          }}
                        >
                          <Input
                            value={draftTitle}
                            onChange={(e) => setDraftTitle(e.target.value)}
                            className="h-6 flex-1 text-[12px]"
                            autoFocus
                          />
                          <IconButton icon={Check} label="Valider" size="sm" type="submit" />
                          <IconButton icon={X} label="Annuler" size="sm" onClick={() => setEditingId(null)} />
                        </form>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() => {
                              setOpen(false);
                              onPick(s.id);
                            }}
                            className="min-w-0 flex-1 truncate text-left font-medium text-foreground hover:text-primary"
                          >
                            {s.title}
                          </button>
                          <span className="shrink-0 rounded-[3px] border border-border bg-card px-1 font-mono text-[10px] text-muted-foreground">
                            {s.surface === "voice" ? "voix" : "chat"} · {s.turns}t
                          </span>
                          <IconButton
                            icon={Pencil}
                            label="Renommer"
                            size="sm"
                            onClick={() => {
                              setEditingId(s.id);
                              setDraftTitle(s.title);
                            }}
                          />
                          {isDel ? (
                            <Button
                              size="sm"
                              variant="danger"
                              onClick={() => {
                                void sessionsStore.remove(s.id);
                                setConfirmDeleteId(null);
                              }}
                              className="h-6 px-1.5 text-[10.5px]"
                            >
                              Supprimer ?
                            </Button>
                          ) : (
                            <IconButton
                              icon={Trash2}
                              label="Supprimer"
                              size="sm"
                              onClick={() => setConfirmDeleteId(s.id)}
                            />
                          )}
                        </>
                      )}
                    </div>
                    {s.preview ? <div className="truncate pl-3.5 text-[11px] text-muted-foreground">{s.preview}</div> : null}
                  </div>
                );
              })
            )}
          </div>
        </div>
      </AnchoredPopover>
    </div>
  );
}
