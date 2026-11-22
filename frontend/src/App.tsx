import React, { useEffect, useState } from "react";
import {
  MdDashboard, MdKingBed, MdEventNote, MdCalendarMonth, MdPeople, MdCleaningServices, MdAccountBalance, MdAssessment,
  MdVerified, MdAdminPanelSettings, MdMenu, MdLogout, MdPerson, MdSearch, MdSettings, MdMeetingRoom, MdHistory,
  MdPointOfSale, MdSoupKitchen, MdRestaurantMenu, MdInventory2, MdShoppingCart,
} from "react-icons/md";
import { useAuth, useRoute, navigate } from "./state";
import { get } from "./api";
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
import BookingPortal from "./pages/BookingPortal";
import Pos, { Kitchen, PosSetup } from "./pages/Pos";
import Inventory, { ItemDetail } from "./pages/Inventory";
import Procurement from "./pages/Procurement";
import { Spinner } from "./ui";

type NavItem = { to: string; label: string; icon: React.ReactNode; perm?: string; any?: string[] };
const NAV: { group: string; items: NavItem[] }[] = [
  { group: "Operations", items: [
    { to: "/", label: "Dashboard", icon: <MdDashboard />, perm: "dashboard.view" },
    { to: "/rooms", label: "Room board", icon: <MdKingBed />, perm: "rooms.view" },
    { to: "/reservations", label: "Front desk & reservations", icon: <MdEventNote />, perm: "reservations.view" },
    { to: "/calendar", label: "Availability calendar", icon: <MdCalendarMonth />, perm: "reservations.view" },
    { to: "/guests", label: "Guests", icon: <MdPeople />, perm: "guests.view" },
    { to: "/housekeeping", label: "Housekeeping", icon: <MdCleaningServices />, perm: "housekeeping.view" },
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
  { group: "Finance", items: [
    { to: "/accounting", label: "Accounting", icon: <MdAccountBalance />, perm: "accounting.view" },
    { to: "/approvals", label: "Approvals", icon: <MdVerified />, perm: "approvals.view" },
    { to: "/reports", label: "Reports", icon: <MdAssessment />, perm: "reports.view" },
  ]},
  { group: "Administration", items: [
    { to: "/admin/users", label: "Users & access", icon: <MdAdminPanelSettings />, perm: "admin.users.view" },
    { to: "/admin/roles", label: "Roles & permissions", icon: <MdVerified />, perm: "admin.users.view" },
    { to: "/admin/hotel", label: "Hotel settings", icon: <MdSettings />, perm: "admin.settings.manage" },
    { to: "/admin/rooms", label: "Rooms & rates", icon: <MdMeetingRoom />, perm: "rooms.manage" },
    { to: "/admin/audit", label: "Audit trail", icon: <MdHistory />, perm: "admin.audit.view" },
  ]},
];

function Shell({ children, path }: { children: React.ReactNode; path: string }) {
  const { user, hotel, setHotelId, can, signOut } = useAuth();
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
        <div className="brand"><span className="logo">E</span><span className="brand-t">EHMS<small>Hotel Management</small></span></div>
        <nav>
          {NAV.map(g => {
            const items = g.items.filter(i => !i.perm || can(i.perm));
            if (!items.length) return null;
            return <div key={g.group} className="nav-g"><div className="nav-gt">{g.group}</div>
              {items.map(i => <a key={i.to} href={"#" + i.to} className={active(i.to) ? "on" : ""} title={i.label}
                onClick={() => { if (window.innerWidth < 900) setCollapsed(true); }}>{i.icon}<span>{i.label}</span>
                {i.to === "/approvals" && pending > 0 && <b className="badge">{pending}</b>}</a>)}
            </div>;
          })}
        </nav>
      </aside>
      <div className="main">
        <header className="top">
          <button className="icon-btn" onClick={() => setCollapsed(c => !c)} aria-label="Toggle navigation"><MdMenu /></button>
          {user && user.hotels.length > 1 ? (
            <select className="hotel-sel" value={hotel?.id} onChange={e => setHotelId(Number(e.target.value))} aria-label="Select hotel">
              {user.hotels.map(h => <option key={h.id} value={h.id}>{h.name}</option>)}
            </select>
          ) : <strong className="hotel-name">{hotel?.name}</strong>}
          {bdate && <span className="bdate" title="Business date (advanced by night audit)">Business date <b>{bdate}</b></span>}
          {can("reservations.view") && (
            <form className="gsearch" onSubmit={e => { e.preventDefault(); if (search.trim()) navigate(`/reservations?tab=search&q=${encodeURIComponent(search.trim())}`); }}>
              <MdSearch /><input placeholder="Search guest, reference, room, phone…" value={search} onChange={e => setSearch(e.target.value)} aria-label="Global search" />
            </form>
          )}
          <div className="spacer" />
          <div className="usermenu">
            <button className="user-btn" onClick={() => setMenu(m => !m)} aria-haspopup="menu">
              <span className="avatar">{user?.full_name.split(" ").map(p => p[0]).slice(0, 2).join("")}</span>
              <span className="user-n">{user?.full_name}<small>{user?.roles.map(r => r.name).join(", ")}</small></span>
            </button>
            {menu && <div className="menu" role="menu" onMouseLeave={() => setMenu(false)}>
              <a href="#/profile" onClick={() => setMenu(false)}><MdPerson /> My profile & security</a>
              <button onClick={() => signOut()}><MdLogout /> Sign out</button>
            </div>}
          </div>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}

function Forbidden() {
  return <div className="empty"><h2>No access</h2><p>Your role does not include this area. Contact your administrator if you need access.</p></div>;
}

export default function App() {
  const { user, ready, hotel, can } = useAuth();
  const [path, q] = useRoute();

  if (path.startsWith("/book/")) return <BookingPortal code={path.split("/")[2] || ""} />;
  if (!ready) return <Spinner text="Starting EHMS…" />;
  if (path === "/forgot") return <ForgotPassword />;
  if (!user) return <Login />;
  if (!hotel) return <div className="empty"><h2>No hotel assigned</h2><p>Your account is not assigned to any hotel yet. Ask an administrator to grant access.</p></div>;

  const seg = path.split("/").filter(Boolean);
  const guard = (perm: string, el: React.ReactNode) => (can(perm) ? el : <Forbidden />);
  let page: React.ReactNode;
  switch (true) {
    case path === "/": page = can("dashboard.view") ? <Dashboard /> : can("housekeeping.view") ? <Housekeeping /> : can("pos.view") ? <Pos />
      : can("kitchen.view") ? <Kitchen /> : can("inventory.view") ? <Inventory q={q} /> : can("procurement.view") ? <Procurement q={q} /> : <Profile />; break;
    case path === "/pos": page = guard("pos.view", <Pos />); break;
    case path === "/kitchen": page = guard("kitchen.view", <Kitchen />); break;
    case path === "/pos-setup": page = guard("pos.manage", <PosSetup />); break;
    case seg[0] === "inventory" && seg[1] === "items" && !!seg[2]: page = guard("inventory.view", <ItemDetail id={Number(seg[2])} />); break;
    case path === "/inventory": page = guard("inventory.view", <Inventory q={q} />); break;
    case path === "/procurement": page = guard("procurement.view", <Procurement q={q} />); break;
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
    default: page = <div className="empty"><h2>Page not found</h2><p><a href="#/">Go to the dashboard</a></p></div>;
  }
  return <Shell path={path}>{page}</Shell>;
}
