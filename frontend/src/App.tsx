import React, { useEffect, useState } from "react";
import {
  MdDashboard, MdKingBed, MdEventNote, MdCalendarMonth, MdPeople, MdCleaningServices, MdAccountBalance, MdAssessment,
  MdVerified, MdAdminPanelSettings, MdMenu, MdLogout, MdPerson, MdSearch, MdSettings, MdMeetingRoom, MdHistory,
  MdPointOfSale, MdSoupKitchen, MdRestaurantMenu, MdInventory2, MdShoppingCart, MdReceiptLong, MdLocalOffer, MdMail, MdLocalLaundryService, MdBadge, MdPayments, MdPersonPin, MdBuild, MdShield, MdCelebration, MdSentimentSatisfied, MdTrendingUp, MdInsights, MdQuestionAnswer, MdFolder, MdGroups, MdBackup, MdHelpOutline, MdChevronRight,
} from "react-icons/md";
import { useAuth, useRoute, navigate } from "./state";
import { get, put } from "./api";
import { useT, LangSelect } from "./i18n";
import Login, { ForgotPassword } from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import RoomBoard from "./pages/RoomBoard";
import Reservations, { ReservationDetail, NewReservation } from "./pages/Reservations";
import Calendar from "./pages/Calendar";
import Folio from "./pages/Folio";
import Guests, { GuestDetail } from "./pages/Guests";
import Housekeeping from "./pages/Housekeeping";
import Accounting from "./pages/Accounting";
import Reports from "./pages/Reports";
import Approvals from "./pages/Approvals";
import { Users, Roles, AuditLog } from "./pages/Admin";
import HotelSettings, { RoomSetup } from "./pages/Settings";
import Profile from "./pages/Profile";
import BookingPortal, { PaymentReturn } from "./pages/BookingPortal";
import Pos, { Kitchen, PosSetup } from "./pages/Pos";
import Inventory, { ItemDetail } from "./pages/Inventory";
import Procurement from "./pages/Procurement";
import Finance from "./pages/Finance";
import Messaging, { NotificationBell, Promotions } from "./pages/Messaging";
import Laundry from "./pages/Laundry";
import HR, { EmployeeDetail, MyHR, Payroll } from "./pages/HR";
import { Events, Maintenance, Security } from "./pages/Operations";
import CRM, { Survey } from "./pages/CRM";
import Revenue from "./pages/Revenue";
import Insights from "./pages/Insights";
import Assistant from "./pages/Assistant";
import Documents from "./pages/Documents";
import Groups, { GroupDetail } from "./pages/Groups";
import { Spinner } from "./ui";
import { Backups, Help } from "./pages/Completion";

declare const __APP_VERSION__: string;
const APP_VERSION = __APP_VERSION__;

type NavItem = { to: string; label: string; icon: React.ReactNode; perm?: string; any?: string[] };
const NAV: { group: string; items: NavItem[] }[] = [
  { group: "Operations", items: [
    { to: "/", label: "Dashboard", icon: <MdDashboard />, perm: "dashboard.view" },
    { to: "/rooms", label: "Room board", icon: <MdKingBed />, perm: "rooms.view" },
    { to: "/reservations", label: "Front desk & reservations", icon: <MdEventNote />, perm: "reservations.view" },
    { to: "/calendar", label: "Availability calendar", icon: <MdCalendarMonth />, perm: "reservations.view" },
    { to: "/groups", label: "Groups & blocks", icon: <MdGroups />, perm: "reservations.view" },
    { to: "/guests", label: "Guests", icon: <MdPeople />, perm: "guests.view" },
    { to: "/housekeeping", label: "Housekeeping", icon: <MdCleaningServices />, perm: "housekeeping.view" },
    { to: "/laundry", label: "Laundry", icon: <MdLocalLaundryService />, perm: "laundry.view" },
    { to: "/maintenance", label: "Maintenance", icon: <MdBuild />, perm: "maintenance.report" },
    { to: "/security", label: "Security", icon: <MdShield />, any: ["security.view", "security.report", "lostfound.manage"] },
    { to: "/events", label: "Events & banqueting", icon: <MdCelebration />, perm: "events.view" },
  ]},
  { group: "Food & beverage", items: [
    { to: "/pos", label: "Point of sale", icon: <MdPointOfSale />, perm: "pos.view" },
    { to: "/kitchen", label: "Kitchen display", icon: <MdSoupKitchen />, perm: "kitchen.view" },
    { to: "/pos-setup", label: "Menu & outlets", icon: <MdRestaurantMenu />, perm: "pos.manage" },
  ]},
  { group: "Supply chain", items: [
    { to: "/inventory", label: "Inventory & stores", icon: <MdInventory2 />, perm: "inventory.view" },
    { to: "/procurement", label: "Procurement", icon: <MdShoppingCart />, perm: "procurement.view" },
  ]},
  { group: "People", items: [
    { to: "/hr", label: "Human resources", icon: <MdBadge />, perm: "hr.view" },
    { to: "/payroll", label: "Payroll", icon: <MdPayments />, perm: "payroll.view" },
    { to: "/my-hr", label: "My HR", icon: <MdPersonPin /> },
  ]},
  { group: "Sales & guests", items: [
    { to: "/crm", label: "Guest relations", icon: <MdSentimentSatisfied />, any: ["crm.view", "crm.complaints"] },
    { to: "/revenue", label: "Sales & revenue", icon: <MdTrendingUp />, perm: "sales.view" },
  ]},
  { group: "Intelligence", items: [
    { to: "/insights", label: "Insights", icon: <MdInsights />, any: ["bi.view", "ai.anomalies.view", "ai.assistant", "bi.schedule", "crm.view", "maintenance.view"] },
    { to: "/assistant", label: "Ask EHMS", icon: <MdQuestionAnswer />, perm: "ai.assistant" },
    { to: "/documents", label: "Documents", icon: <MdFolder />, any: ["documents.view", "documents.upload"] },
  ]},
  { group: "Finance", items: [
    { to: "/accounting", label: "Accounting", icon: <MdAccountBalance />, perm: "accounting.view" },
    { to: "/approvals", label: "Approvals", icon: <MdVerified />, perm: "approvals.view" },
    { to: "/finance", label: "Finance operations", icon: <MdReceiptLong />, any: ["finance.expenses.request", "accounting.reconcile", "accounting.view", "finance.petty_cash"] },
    { to: "/promotions", label: "Promotions", icon: <MdLocalOffer />, perm: "promotions.manage" },
    { to: "/reports", label: "Reports", icon: <MdAssessment />, perm: "reports.view" },
  ]},
  { group: "Administration", items: [
    { to: "/admin/users", label: "Users & access", icon: <MdAdminPanelSettings />, perm: "admin.users.view" },
    { to: "/admin/roles", label: "Roles & permissions", icon: <MdVerified />, perm: "admin.users.view" },
    { to: "/admin/hotel", label: "Hotel settings", icon: <MdSettings />, perm: "admin.settings.manage" },
    { to: "/admin/rooms", label: "Rooms & rates", icon: <MdMeetingRoom />, perm: "rooms.manage" },
    { to: "/admin/audit", label: "Audit trail", icon: <MdHistory />, perm: "admin.audit.view" },
    { to: "/admin/messaging", label: "Messaging", icon: <MdMail />, perm: "admin.notifications.manage" },
    { to: "/admin/backups", label: "Backups", icon: <MdBackup />, perm: "admin.backups" },
  ]},
  { group: "Help", items: [
    { to: "/help", label: "Help & support", icon: <MdHelpOutline /> },
  ]},
];

function Breadcrumb({ path }: { path: string }) {
  const { t } = useT();
  if (path === "/") return null;
  const seg = path.split("/").filter(Boolean);
  let found: { group: string; item: NavItem } | null = null;
  for (const g of NAV) for (const i of g.items) {
    if (i.to !== "/" && (path === i.to || path.startsWith(i.to + "/")) && (!found || i.to.length > found.item.to.length)) found = { group: g.group, item: i };
  }
  const parents: Record<string, [string, string]> = { folio: ["/reservations", "Front desk & reservations"] };
  if (!found && parents[seg[0]]) found = { group: "Operations", item: { to: parents[seg[0]][0], label: parents[seg[0]][1], icon: null } };
  const detail = found && path !== found.item.to ? seg[seg.length - 1] : null;
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      <a href="#/">{t("Home")}</a>
      {found && <><MdChevronRight aria-hidden /><span>{t(found.group)}</span><MdChevronRight aria-hidden />
        {detail ? <a href={"#" + found.item.to}>{t(found.item.label)}</a> : <span aria-current="page">{t(found.item.label)}</span>}</>}
      {detail && <><MdChevronRight aria-hidden /><span aria-current="page">{/^\d+$/.test(detail) ? `#${detail}` : t(detail.charAt(0).toUpperCase() + detail.slice(1))}</span></>}
    </nav>
  );
}

function Shell({ children, path }: { children: React.ReactNode; path: string }) {
  const { user, hotel, setHotelId, can, signOut } = useAuth();
  const { t, lang, setLang } = useT();
  useEffect(() => { if (user?.language && user.language !== lang) setLang(user.language); }, [user?.id]);
  const [collapsed, setCollapsed] = useState(() => window.innerWidth < 900);
  const [menu, setMenu] = useState(false);
  const [search, setSearch] = useState("");
  const [bdate, setBdate] = useState<string>("");
  const [pending, setPending] = useState(0);
  useEffect(() => {
    if (!hotel) return;
    get(`/api/hotels/${hotel.id}`).then(h => setBdate(h.business_date)).catch(() => setBdate(""));
    if (can("approvals.view")) get(`/api/hotels/${hotel.id}/approvals`).then(a => setPending(a.items.length)).catch(() => setPending(0));
  }, [hotel?.id, path]);
  const active = (to: string) => (to === "/" ? path === "/" : path === to || path.startsWith(to + "/"));
  return (
    <div className={`shell ${collapsed ? "collapsed" : ""}`}>
      <aside className="side">
        <div className="brand">{(hotel as any)?.logo_url ? <img className="logo logo-img" src={(hotel as any).logo_url} alt="" /> : <span className="logo">E</span>}<span className="brand-t">EHMS<small>{t("Hotel Management")} · v{APP_VERSION}</small></span></div>
        <nav>
          {NAV.map(g => {
            const items = g.items.filter(i => (!i.perm || can(i.perm)) && (!i.any || i.any.some(p => can(p))));
            if (!items.length) return null;
            return <div key={g.group} className="nav-g"><div className="nav-gt">{t(g.group)}</div>
              {items.map(i => <a key={i.to} href={"#" + i.to} className={active(i.to) ? "on" : ""} title={t(i.label)}
                onClick={() => { if (window.innerWidth < 900) setCollapsed(true); }}>{i.icon}<span>{t(i.label)}</span>
                {i.to === "/approvals" && pending > 0 && <b className="badge">{pending}</b>}</a>)}
            </div>;
          })}
        </nav>
      </aside>
      <div className="main">
        <header className="top">
          <button className="icon-btn" onClick={() => setCollapsed(c => !c)} aria-label={t("Toggle navigation")}><MdMenu /></button>
          {user && user.hotels.length > 1 ? (
            <select className="hotel-sel" value={hotel?.id} onChange={e => setHotelId(Number(e.target.value))} aria-label={t("Select hotel")}>
              {user.hotels.map(h => <option key={h.id} value={h.id}>{h.name}</option>)}
            </select>
          ) : <strong className="hotel-name">{hotel?.name}</strong>}
          {bdate && <span className="bdate" title="Business date (advanced by night audit)">{t("Business date")} <b>{bdate}</b></span>}
          {can("reservations.view") && (
            <form className="gsearch" onSubmit={e => { e.preventDefault(); if (search.trim()) navigate(`/reservations?tab=search&q=${encodeURIComponent(search.trim())}`); }}>
              <MdSearch /><input placeholder={t("Search guest, reference, room, phone…")} value={search} onChange={e => setSearch(e.target.value)} aria-label="Global search" />
            </form>
          )}
          <div className="spacer" />
          <NotificationBell />
          <div className="usermenu">
            <button className="user-btn" onClick={() => setMenu(m => !m)} aria-haspopup="menu">
              <span className="avatar">{user?.full_name.split(" ").map(p => p[0]).slice(0, 2).join("")}</span>
              <span className="user-n">{user?.full_name}<small>{user?.roles.map(r => r.name).join(", ")}</small></span>
            </button>
            {menu && <div className="menu" role="menu" onMouseLeave={() => setMenu(false)}>
              <a href="#/profile" onClick={() => setMenu(false)}><MdPerson /> {t("My profile & security")}</a>
              <a href="#/help" onClick={() => setMenu(false)}><MdHelpOutline /> {t("Help & support")}</a>
              <label className="menu-lang">{t("Language")} <LangSelect onChange={l => put("/api/me/preferences", { language: l }).catch(() => undefined)} /></label>
              <button onClick={() => signOut()}><MdLogout /> {t("Sign out")}</button>
            </div>}
          </div>
        </header>
        <main className="content"><Breadcrumb path={path} />{children}</main>
      </div>
    </div>
  );
}

function Forbidden() {
  const { t } = useT();
  return <div className="empty"><h2>{t("No access")}</h2><p>{t("Your role does not include this area. Contact your administrator if you need access.")}</p></div>;
}

export default function App() {
  const { user, ready, hotel, can } = useAuth();
  const { t } = useT();
  const [path, q] = useRoute();

  if (window.location.pathname === "/payment-return") return <PaymentReturn />;
  if (path.startsWith("/book/")) return <BookingPortal code={path.split("/")[2] || ""} />;
  if (path.startsWith("/survey/")) return <Survey token={path.split("/")[2] || ""} />;
  if (!ready) return <Spinner text={t("Starting EHMS…")} />;
  if (path === "/forgot") return <ForgotPassword />;
  if (!user) return <Login />;
  if (!hotel) return <div className="empty"><h2>No hotel assigned</h2><p>Your account is not assigned to any hotel yet. Ask an administrator to grant access.</p></div>;

  const seg = path.split("/").filter(Boolean);
  const guard = (perm: string, el: React.ReactNode) => (can(perm) ? el : <Forbidden />);
  let page: React.ReactNode;
  switch (true) {
    case path === "/": page = can("dashboard.view") ? <Dashboard /> : can("housekeeping.view") ? <Housekeeping /> : can("pos.view") ? <Pos />
      : can("laundry.view") ? <Laundry /> : can("kitchen.view") ? <Kitchen /> : can("inventory.view") ? <Inventory q={q} /> : can("procurement.view") ? <Procurement q={q} /> : <Profile />; break;
    case path === "/pos": page = guard("pos.view", <Pos />); break;
    case path === "/kitchen": page = guard("kitchen.view", <Kitchen />); break;
    case path === "/pos-setup": page = guard("pos.manage", <PosSetup />); break;
    case seg[0] === "inventory" && seg[1] === "items" && !!seg[2]: page = guard("inventory.view", <ItemDetail id={Number(seg[2])} />); break;
    case path === "/inventory": page = guard("inventory.view", <Inventory q={q} />); break;
    case path === "/procurement": page = guard("procurement.view", <Procurement q={q} />); break;
    case path === "/finance": page = ["finance.expenses.request", "accounting.reconcile", "accounting.view", "finance.petty_cash"].some(can) ? <Finance q={q} /> : <Forbidden />; break;
    case path === "/maintenance": page = guard("maintenance.report", <Maintenance q={q} />); break;
    case path === "/security": page = ["security.view", "security.report", "lostfound.manage"].some(can) ? <Security q={q} /> : <Forbidden />; break;
    case path === "/events": page = guard("events.view", <Events />); break;
    case seg[0] === "groups" && !!seg[1]: page = guard("reservations.view", <GroupDetail id={Number(seg[1])} />); break;
    case path === "/groups": page = guard("reservations.view", <Groups />); break;
    case path === "/insights": page = ["bi.view", "ai.anomalies.view", "ai.assistant", "bi.schedule", "crm.view", "maintenance.view"].some(can) ? <Insights q={q} /> : <Forbidden />; break;
    case path === "/assistant": page = guard("ai.assistant", <Assistant />); break;
    case seg[0] === "documents": page = ["documents.view", "documents.upload"].some(can) ? <Documents q={q} openId={seg[1] ? Number(seg[1]) : undefined} /> : <Forbidden />; break;
    case path === "/crm": page = ["crm.view", "crm.complaints"].some(can) ? <CRM q={q} /> : <Forbidden />; break;
    case path === "/revenue": page = guard("sales.view", <Revenue />); break;
    case path === "/laundry": page = guard("laundry.view", <Laundry />); break;
    case seg[0] === "hr" && seg[1] === "employees" && !!seg[2]: page = guard("hr.view", <EmployeeDetail id={Number(seg[2])} />); break;
    case path === "/hr": page = guard("hr.view", <HR q={q} />); break;
    case path === "/payroll": page = guard("payroll.view", <Payroll />); break;
    case path === "/my-hr": page = <MyHR />; break;
    case path === "/promotions": page = guard("promotions.manage", <Promotions />); break;
    case path === "/admin/messaging": page = guard("admin.notifications.manage", <Messaging />); break;
    case path === "/rooms": page = guard("rooms.view", <RoomBoard />); break;
    case path === "/reservations/new": page = guard("reservations.create", <NewReservation q={q} />); break;
    case seg[0] === "reservations" && !!seg[1]: page = guard("reservations.view", <ReservationDetail id={Number(seg[1])} />); break;
    case path === "/reservations": page = guard("reservations.view", <Reservations q={q} />); break;
    case path === "/calendar": page = guard("reservations.view", <Calendar />); break;
    case seg[0] === "folio": page = guard("folio.view", <Folio id={Number(seg[1])} />); break;
    case seg[0] === "guests" && !!seg[1]: page = guard("guests.view", <GuestDetail id={Number(seg[1])} />); break;
    case path === "/guests": page = guard("guests.view", <Guests />); break;
    case path === "/housekeeping": page = guard("housekeeping.view", <Housekeeping />); break;
    case path === "/accounting": page = guard("accounting.view", <Accounting />); break;
    case path === "/reports": page = guard("reports.view", <Reports />); break;
    case path === "/approvals": page = guard("approvals.view", <Approvals />); break;
    case path === "/admin/users": page = guard("admin.users.view", <Users />); break;
    case path === "/admin/roles": page = guard("admin.users.view", <Roles />); break;
    case path === "/admin/hotel": page = guard("admin.settings.manage", <HotelSettings />); break;
    case path === "/admin/rooms": page = guard("rooms.manage", <RoomSetup />); break;
    case path === "/admin/audit": page = guard("admin.audit.view", <AuditLog />); break;
    case path === "/profile": page = <Profile />; break;
    case path === "/help": page = <Help />; break;
    case path === "/admin/backups": page = guard("admin.backups", <Backups />); break;
    default: page = <div className="empty"><h2>{t("Page not found")}</h2><p><a href="#/">{t("Go to the dashboard")}</a></p></div>;
  }
  return <Shell path={path}>{page}</Shell>;
}
