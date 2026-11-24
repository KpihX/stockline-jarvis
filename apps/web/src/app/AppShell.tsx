import { useCallback, useEffect, useState } from "react";
import { Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";
import { PhoneCall, PhoneOff, ShieldAlert } from "lucide-react";
import { useActivityStream } from "@/lib/queries";
import { cn } from "@/lib/cn";
import { Button, CommandK, Dot, EmptyState, Page, PageBody, PageHeader, PageHeaderSlot, ResizeHandle, Toaster, useResizableWidth } from "@/ui";
import { AssistantPanel } from "@/features/assistant/AssistantPanel";
import { UserMenu } from "@/features/auth/UserMenu";
import { canVisitRoute, useAuth } from "@/features/auth/auth-store";
import { callsStore, useCalls } from "@/features/calls/calls-store";
import { VoiceCommandButton, VoiceCommandProvider } from "@/features/voice-command";
import { AssistantButton } from "./AssistantButton";
import { Sidebar } from "./Sidebar";
import { shell, useShell } from "./shell-state";

/**
 * Sidebar 232px (resizable, ⌘\ / ⌘B → 56px rail) | page (Outlet) | Assistant 400px (⌘J, resizable 320–720, pushes
 * content; width + opacity animate 200ms ease-out). Mounts SSE, ⌘K and toasts once.
 */
function ShellHeaderTools() {
  return (
    <div className="flex shrink-0 items-center gap-1" data-shell-tools>
      <UserMenu />
      <VoiceCommandButton />
      <AssistantButton />
    </div>
  );
}

function ForbiddenView({ role }: { role: string }) {
  const navigate = useNavigate();
  return (
    <Page>
      <PageHeader title="Accès réservé" />
      <PageBody>
        <EmptyState
          icon={ShieldAlert}
          title="Cette page n'est pas accessible avec ce profil"
          description={`Vous êtes connecté avec le rôle « ${role} ». Chaque profil ne voit que son périmètre métier.`}
          action={<Button variant="primary" onClick={() => navigate("/")}>Retour à l'accueil</Button>}
        />
      </PageBody>
    </Page>
  );
}

export function AppShell() {
  const { account } = useAuth();
  const loc = useLocation();
  const navigate = useNavigate();
  const cs = useCalls();
  useActivityStream();
  useEffect(() => {
    if (account && (account.role === "manager" || account.role === "admin")) {
      callsStore.connectStream();
    } else {
      callsStore.disconnectStream();
    }
  }, [account?.id, account?.role]);
  const { assistantOpen } = useShell();
  const assistant = useResizableWidth("assistant", 400, 320, 720);
  // Keep the panel mounted while it animates closed (unmounting resets chat focus/scroll, chat state lives in its store).
  const [assistantMounted, setAssistantMounted] = useState(assistantOpen);
  const [assistantShown, setAssistantShown] = useState(assistantOpen);
  useEffect(() => {
    if (assistantOpen) {
      setAssistantMounted(true);
      void import("@/features/assistant/chat-store").then(({ chat }) => chat.syncFromActive());
      // Mount at 0 width, let one frame paint it, then grow (a single rAF fires before that first paint).
      let raf = requestAnimationFrame(() => { raf = requestAnimationFrame(() => setAssistantShown(true)); });
      return () => cancelAnimationFrame(raf);
    }
    setAssistantShown(false);
    const t = window.setTimeout(() => setAssistantMounted(false), 220);
    return () => window.clearTimeout(t);
  }, [assistantOpen]);
  const [headers, setHeaders] = useState(0);
  const registerHeader = useCallback(() => {
    setHeaders((n) => n + 1);
    return () => setHeaders((n) => n - 1);
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === "j") { e.preventDefault(); shell.toggleAssistant(); }
      else if (k === "\\" || k === "b") { e.preventDefault(); shell.toggleSidebar(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!account) {
    const next = encodeURIComponent(loc.pathname + loc.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  if (account.role === "client" && loc.pathname === "/clients" && account.entityId) {
    return <Navigate to={`/clients/${account.entityId}`} replace />;
  }
  if (account.role === "supplier" && loc.pathname === "/suppliers" && account.entityId) {
    return <Navigate to={`/suppliers/${account.entityId}`} replace />;
  }
  const allowed = canVisitRoute(account.role, loc.pathname, account.entityId);

  const isStaff = account.role === "manager" || account.role === "admin";
  const showCallBar = isStaff && cs.activeCall && (cs.activeCall.status === "ringing" || cs.activeCall.status === "active");

  return (
    <div className="flex h-full min-w-[1024px] overflow-hidden bg-background">
      <audio ref={(el) => callsStore.bindAudioElement(el)} autoPlay playsInline className="hidden" />
      <Sidebar />
      <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
        {showCallBar && cs.activeCall ? (
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-primary/40 bg-primary/[.08] px-5 py-2 text-[12.5px]">
            <div className="flex items-center gap-2.5">
              <Dot tone={cs.activeCall.status === "active" ? "success" : "warning"} pulse />
              <span className="font-semibold text-foreground">
                {cs.activeCall.status === "ringing" ? "Appel WhatsApp entrant :" : "Appel WhatsApp actif :"}
              </span>
              <span className="font-medium text-primary">{cs.activeCall.clientName || cs.activeCall.phoneNumber}</span>
              <span className="font-mono text-[11px] text-muted-foreground">{cs.activeCall.phoneNumber}</span>
              {cs.activeCall.linkedCommands?.length ? (
                <span className="rounded-[3px] border border-primary/30 bg-card px-1.5 py-0.5 font-mono text-[11px] text-primary">
                  {cs.activeCall.linkedCommands[0].number}
                </span>
              ) : null}
            </div>
            <div className="flex items-center gap-2">
              {cs.activeCall.status === "ringing" ? (
                <>
                  <Button size="sm" variant="primary" icon={PhoneCall} loading={cs.busy} onClick={() => { void callsStore.answerCall(cs.activeCall!.callId); navigate("/calls"); }}>
                    Décrocher
                  </Button>
                  <Button size="sm" variant="danger" icon={PhoneOff} onClick={() => void callsStore.rejectCall(cs.activeCall!.callId)}>
                    Refuser
                  </Button>
                </>
              ) : (
                <Button size="sm" variant="danger" icon={PhoneOff} onClick={() => void callsStore.hangupCall(cs.activeCall!.callId)}>
                  Raccrocher
                </Button>
              )}
              <Button size="sm" variant="default" onClick={() => navigate("/calls")}>
                Ouvrir Appels
              </Button>
            </div>
          </div>
        ) : null}
        <div className="relative min-h-0 flex-1 overflow-hidden">
          <PageHeaderSlot trailing={<ShellHeaderTools />} register={registerHeader}>
            {allowed ? <Outlet /> : <ForbiddenView role={account.role} />}
          </PageHeaderSlot>
          {headers === 0 ? (
            <div className="absolute right-5 top-0 z-30 flex h-12 items-center">
              <ShellHeaderTools />
            </div>
          ) : null}
        </div>
      </main>
      {assistantMounted ? (
        <div
          data-assistant-panel={assistantShown ? "open" : "closed"}
          style={{ width: assistantShown ? assistant.width : 0 }}
          className={cn(
            "relative h-full shrink-0 overflow-hidden",
            !assistant.dragging && "transition-[width,opacity] duration-200 ease-out motion-reduce:transition-none",
            assistantShown ? "opacity-100" : "opacity-0",
          )}
        >
          {/* Fixed inner width: the chat never reflows while the column animates. Pinned right so it slides in. */}
          <aside style={{ width: assistant.width }} className="absolute inset-y-0 right-0 border-l border-border bg-card">
            <AssistantPanel />
            <ResizeHandle r={assistant} edge="left" label="Redimensionner l'assistant" />
          </aside>
        </div>
      ) : null}
      <CommandK />
      <Toaster />
      <VoiceCommandProvider />
    </div>
  );
}
