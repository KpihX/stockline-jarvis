/** Navigation model: filtered by authenticated role (`client`, `supplier`, `manager`, `admin`). */
import {
  Activity, AudioLines, BadgeEuro, BookOpen, Boxes, Building2, FileText, History, Home,
  Package, PhoneIncoming, QrCode, Scale, ShieldCheck, ShoppingCart, Sparkles, Tags, Truck, Users, Wallet, Warehouse,
  type LucideIcon,
} from "lucide-react";
import type { AuthRole } from "@kit/shared";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  keywords?: string;
  roles?: AuthRole[]; // omitted = visible to manager & admin
}
export interface NavGroup { label?: string; items: NavItem[] }

export const NAV: NavGroup[] = [
  { items: [{ to: "/", label: "Accueil", icon: Home, keywords: "dashboard tableau de bord", roles: ["client", "supplier", "manager", "admin"] }] },
  {
    label: "Ventes",
    items: [
      { to: "/orders", label: "Commandes", icon: ShoppingCart, keywords: "ventes commande", roles: ["client", "manager", "admin"] },
      { to: "/clients", label: "Clients", icon: Users, keywords: "client restaurant", roles: ["client", "manager", "admin"] },
      { to: "/prices", label: "Prix", icon: BadgeEuro, keywords: "tarifs règles remise prix négocié", roles: ["client", "manager", "admin"] },
      { to: "/history", label: "Historique", icon: History, keywords: "historique réclamation litige retour", roles: ["client", "manager", "admin"] },
    ],
  },
  {
    label: "Achats & stock",
    items: [
      { to: "/products", label: "Produits", icon: Package, keywords: "catalogue article", roles: ["client", "supplier", "manager", "admin"] },
      { to: "/stock", label: "Stocks", icon: Warehouse, keywords: "lots inventaire", roles: ["client", "supplier", "manager", "admin"] },
      { to: "/purchase-orders", label: "Achats", icon: Boxes, keywords: "commande fournisseur", roles: ["supplier", "manager", "admin"] },
      { to: "/suppliers", label: "Fournisseurs", icon: Building2, keywords: "fournisseur", roles: ["supplier", "manager", "admin"] },
    ],
  },
  {
    label: "Finance",
    items: [
      { to: "/receivables", label: "Encours", icon: Scale, keywords: "encours balance âgée retard", roles: ["manager", "admin"] },
      { to: "/invoices", label: "Factures", icon: FileText, keywords: "facture impayé", roles: ["client", "manager", "admin"] },
      { to: "/payments", label: "Paiements", icon: Wallet, keywords: "règlement encaissement", roles: ["client", "manager", "admin"] },
    ],
  },
  { label: "Logistique", items: [{ to: "/routes", label: "Tournées", icon: Truck, keywords: "livraison route", roles: ["manager", "admin"] }] },
  {
    label: "IA",
    items: [
      { to: "#assistant", label: "Assistant", icon: Sparkles, keywords: "chat ia", roles: ["client", "supplier", "manager", "admin"] },
      { to: "/voice", label: "Voix", icon: AudioLines, keywords: "agent vocal appel", roles: ["client", "supplier", "manager", "admin"] },
      { to: "/calls", label: "Appels WhatsApp", icon: PhoneIncoming, keywords: "whatsapp voip webrtc appel telephone client", roles: ["manager", "admin"] },
      { to: "/context", label: "Contexte", icon: BookOpen, keywords: "contexte ia fiches connaissances", roles: ["manager", "admin"] },
    ],
  },
  {
    label: "Administration",
    items: [
      { to: "/activity", label: "Activité", icon: Activity, keywords: "journal événements", roles: ["manager", "admin"] },
      { to: "/groups", label: "Groupes", icon: Tags, keywords: "groupes tags étiquettes", roles: ["manager", "admin"] },
      { to: "/settings", label: "Paramètres WA", icon: QrCode, keywords: "whatsapp qr code reglages parametres pairing", roles: ["manager", "admin"] },
      { to: "/accounts", label: "Comptes", icon: ShieldCheck, keywords: "comptes profils utilisateurs admin", roles: ["admin"] },
    ],
  },
];

export const NAV_ITEMS: NavItem[] = NAV.flatMap((g) => g.items);

const CLIENT_LABELS: Record<string, string> = {
  "/orders": "Mes commandes",
  "/clients": "Ma fiche",
  "/prices": "Mes tarifs",
  "/history": "Mon historique",
  "/invoices": "Mes factures",
  "/payments": "Mes paiements",
};

const SUPPLIER_LABELS: Record<string, string> = {
  "/purchase-orders": "Mes bons d'achat",
  "/suppliers": "Ma fiche fournisseur",
};

export function navForRole(role: AuthRole | undefined, entityId?: string | null): NavGroup[] {
  if (!role) return [];
  return NAV.map((g) => ({
    ...g,
    items: g.items
      .filter((it) => !it.roles || it.roles.includes(role))
      .map((it) => {
        if (role === "client") {
          const to = it.to === "/clients" && entityId ? `/clients/${entityId}` : it.to;
          return { ...it, to, label: CLIENT_LABELS[it.to] ?? it.label };
        }
        if (role === "supplier") {
          const to = it.to === "/suppliers" && entityId ? `/suppliers/${entityId}` : it.to;
          return { ...it, to, label: SUPPLIER_LABELS[it.to] ?? it.label };
        }
        return it;
      }),
  })).filter((g) => g.items.length > 0);
}
