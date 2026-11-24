// Interface languages (release 1.2). English is the source text; other languages map English → translation.
// Strings without a translation fall back to English, so a partly translated screen never breaks.
// To add a language: add it to LANGS and add its dictionary below (and to /api/me/preferences on the server).
import React, { createContext, useContext, useState } from "react";

export const LANGS: Record<string, string> = { en: "English", fr: "Français" };

const FR: Record<string, string> = {
  // navigation groups and items
  "Operations": "Opérations", "Food & beverage": "Restauration", "Supply chain": "Approvisionnement", "People": "Personnel",
  "Sales & guests": "Ventes et clients", "Intelligence": "Analyse", "Finance": "Finance", "Administration": "Administration", "Help": "Aide",
  "Dashboard": "Tableau de bord", "Room board": "Plan des chambres", "Front desk & reservations": "Réception et réservations",
  "Availability calendar": "Calendrier des disponibilités", "Groups & blocks": "Groupes et allotements", "Guests": "Clients",
  "Housekeeping": "Gouvernance", "Laundry": "Blanchisserie", "Maintenance": "Maintenance", "Security": "Sécurité",
  "Events & banqueting": "Événements et banquets", "Point of sale": "Point de vente", "Kitchen display": "Écran cuisine",
  "Menu & outlets": "Menus et points de vente", "Inventory & stores": "Stocks et magasins", "Procurement": "Achats",
  "Human resources": "Ressources humaines", "Payroll": "Paie", "My HR": "Mon espace RH", "Guest relations": "Relation client",
  "Sales & revenue": "Ventes et revenus", "Insights": "Indicateurs", "Ask EHMS": "Demander à EHMS", "Documents": "Documents",
  "Accounting": "Comptabilité", "Approvals": "Approbations", "Finance operations": "Opérations financières", "Promotions": "Promotions",
  "Reports": "Rapports", "Users & access": "Utilisateurs et accès", "Roles & permissions": "Rôles et autorisations",
  "Hotel settings": "Paramètres de l'hôtel", "Rooms & rates": "Chambres et tarifs", "Audit trail": "Journal d'audit",
  "Messaging": "Messagerie", "Backups": "Sauvegardes", "Help & support": "Aide et assistance",
  // header and shell
  "Business date": "Date d'activité", "Search guest, reference, room, phone…": "Rechercher client, référence, chambre, téléphone…",
  "My profile & security": "Mon profil et sécurité", "Sign out": "Se déconnecter", "Language": "Langue", "Toggle navigation": "Afficher/masquer le menu",
  "Select hotel": "Choisir l'hôtel", "Home": "Accueil", "Hotel Management": "Gestion hôtelière",
  "No access": "Accès refusé", "Your role does not include this area. Contact your administrator if you need access.":
    "Votre rôle n'inclut pas cette section. Contactez votre administrateur si vous en avez besoin.",
  "Page not found": "Page introuvable", "Go to the dashboard": "Aller au tableau de bord", "Starting EHMS…": "Démarrage d'EHMS…",
  // sign-in
  "Sign in": "Connexion", "Email": "E-mail", "Password": "Mot de passe", "Forgot password?": "Mot de passe oublié ?", "Verify": "Vérifier",
  "Two-step verification": "Vérification en deux étapes", "6-digit code from your authenticator app": "Code à 6 chiffres de votre application d'authentification",
  "Use a different account": "Utiliser un autre compte", "Sessions end after inactivity.": "Les sessions expirent après inactivité.",
  "Enterprise Hotel": "Système de gestion", "Management System": "hôtelière d'entreprise",
  "Reservations, front office, housekeeping, folios, payments and accounting in one secure platform.":
    "Réservations, réception, gouvernance, folios, paiements et comptabilité sur une plateforme sécurisée.",
  "Sign-in failed": "Échec de la connexion",
  // common actions
  "Save": "Enregistrer", "Cancel": "Annuler", "Close": "Fermer", "Confirm": "Confirmer", "Search": "Rechercher", "Previous": "Précédent",
  "Next": "Suivant", "Page": "Page", "of": "sur", "results": "résultats",
  // booking portal
  "Book your stay": "Réservez votre séjour", "Arrival": "Arrivée", "Departure": "Départ", "Adults": "Adultes", "Children": "Enfants",
  "Promo code": "Code promo", "Referral code": "Code de parrainage", "Check availability": "Vérifier les disponibilités",
  "per night": "par nuit", "Total": "Total", "Select": "Choisir", "Selected": "Choisi", "Your details": "Vos coordonnées",
  "First name": "Prénom", "Last name": "Nom", "Phone": "Téléphone", "Special requests": "Demandes particulières",
  "I accept the terms and the cancellation policy": "J'accepte les conditions et la politique d'annulation",
  "Book now": "Réserver", "Pay online now": "Payer en ligne", "Pay at the hotel": "Payer à l'hôtel", "Find my booking": "Retrouver ma réservation",
  "Booking reference": "Référence de réservation", "Cancel booking": "Annuler la réservation", "Watch video": "Voir la vidéo",
  "No rooms are available for these dates.": "Aucune chambre disponible pour ces dates.", "Check-in from": "Arrivée à partir de",
  "Check-out by": "Départ avant", "Cancellation policy": "Politique d'annulation", "Amenities": "Équipements", "guests": "personnes",
  "Taxes and service charge included": "Taxes et service inclus", "Download confirmation": "Télécharger la confirmation",
  // public website
  "About": "À propos", "Rooms": "Chambres", "Dining": "Restauration", "Events": "Événements", "Gallery": "Galerie", "Location": "Accès", "Contact": "Contact",
  "Menu": "Menu", "Contact us": "Nous contacter", "up to": "jusqu'à", "from": "à partir de", "Send an event enquiry": "Demande pour un événement",
  "Open in Google Maps": "Ouvrir dans Google Maps", "Staff login": "Espace personnel", "Enquiry about": "Votre demande concerne", "General enquiry": "Demande générale",
  "Event or meeting": "Événement ou réunion", "Your name": "Votre nom", "Event date": "Date de l'événement", "Subject": "Objet", "Number of guests": "Nombre d'invités",
  "Message": "Message", "Send me offers by email (optional)": "Recevoir nos offres par e-mail (facultatif)",
  "We use your details only to answer your enquiry.": "Vos coordonnées servent uniquement à répondre à votre demande.", "Send message": "Envoyer",
  "Preview — form disabled": "Aperçu — formulaire désactivé", "Website": "Site web", "Your booking": "Votre réservation", "Status": "Statut",
};

const DICTS: Record<string, Record<string, string>> = { fr: FR };

type LangCtx = { lang: string; setLang: (l: string) => void; t: (s: string) => string };
const Ctx = createContext<LangCtx>({ lang: "en", setLang: () => {}, t: s => s });

function initial(): string {
  try {
    const v = localStorage.getItem("ehms.lang");
    if (v && LANGS[v]) return v;
  } catch { /* storage unavailable */ }
  const nav = (navigator.language || "en").slice(0, 2);
  return LANGS[nav] ? nav : "en";
}

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState(initial);
  const setLang = (l: string) => {
    if (!LANGS[l]) return;
    setLangState(l);
    try { localStorage.setItem("ehms.lang", l); } catch { /* ignore */ }
    document.documentElement.lang = l;
  };
  const t = (s: string) => (lang === "en" ? s : DICTS[lang]?.[s] ?? s);
  return <Ctx.Provider value={{ lang, setLang, t }}>{children}</Ctx.Provider>;
}

export const useT = () => useContext(Ctx);

export function LangSelect({ onChange, className }: { onChange?: (l: string) => void; className?: string }) {
  const { lang, setLang, t } = useT();
  return (
    <select className={className || "input lang-sel"} value={lang} aria-label={t("Language")}
      onChange={e => { setLang(e.target.value); onChange?.(e.target.value); }}>
      {Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
    </select>
  );
}
