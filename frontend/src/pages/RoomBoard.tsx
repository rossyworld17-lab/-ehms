import React, { useMemo, useState } from "react";
import { get, post, label } from "../api";
import { useAuth, navigate } from "../state";
import { Button, Card, Field, Loadable, Modal, Pill, Select, Textarea, useAction, useLoad, useToast, errText } from "../ui";

const LEGEND = ["available", "reserved", "occupied", "dirty", "cleaning", "clean", "vip_hold", "maintenance", "out_of_order", "out_of_service", "blocked"];

export default function RoomBoard() {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/rooms`), [hotel?.id]);
  const [filter, setFilter] = useState("");
  const [floor, setFloor] = useState("");
  const [sel, setSel] = useState<any>(null);
  const { busy, run } = useAction();
  const [svc, setSvc] = useState({ service_status: "out_of_order", note: "" });
  const toast = useToast();
  const canAssign = can("reservations.modify") && can("reservations.view");
  const arr = useLoad(() => (canAssign ? get(`/api/hotels/${hotel!.id}/reservations`, { view: "arrivals" }) : Promise.resolve({ items: [] })), [hotel?.id]);
  const unassigned = ((arr.data?.items || []) as any[]).filter(r => !r.room_number);
  const [picked, setPicked] = useState<any>(null);   // arrival chosen by click/keyboard (touch-friendly alternative to dragging)
  const [over, setOver] = useState<number | null>(null);
  const free = (r: any) => r.occupancy === "vacant" && (r.service_status === "in_service" || r.service_status === "vip_hold") && !r.arrival;
  async function assign(resId: number, room: any) {
    const res = unassigned.find(x => x.id === resId);
    if (!res) return;
    if (!free(room)) { toast("error", `Room ${room.number} is not free for an arrival`); return; }
    try {
      const out = await post(`/api/reservations/${resId}/assign-room`, { room_id: room.id });
      toast("success", `${res.first_name} ${res.last_name} assigned to room ${room.number}${room.room_type_code !== res.room_type_code ? " (category changed)" : ""}`);
      (out?.warnings || []).forEach((w: string) => toast("info", w));
      setPicked(null); arr.reload(); st.reload();
    } catch (e) { toast("error", errText(e)); }
  }

  const floors = useMemo(() => Array.from(new Set((st.data?.items || []).map((r: any) => r.floor))).sort(), [st.data]);
  const rooms = (st.data?.items || []).filter((r: any) => (!filter || r.display_status === filter) && (!floor || r.floor === floor));

  async function hk(status: string) {
    if (await run(() => post(`/api/rooms/${sel.id}/housekeeping-status`, { hk_status: status }), `Room ${sel.number} marked ${label(status)}`)) { setSel(null); st.reload(); }
  }
  async function service(status: string, note?: string) {
    if (await run(() => post(`/api/rooms/${sel.id}/service-status`, { service_status: status, note }), `Room ${sel.number} updated`)) { setSel(null); st.reload(); }
  }

  return (
    <div className="page">
      <div className="page-h"><div><h1>Room board</h1><p className="muted">Real-time status — updates automatically from check-in, check-out and housekeeping</p></div>
        <div className="row gap-s">
          <Select value={floor} onChange={e => setFloor(e.target.value)} aria-label="Floor"><option value="">All floors</option>{floors.map((f: any) => <option key={f} value={f}>Floor {f}</option>)}</Select>
          <Button kind="secondary" onClick={st.reload}>Refresh</Button></div></div>
      <Loadable state={st}>{d => (<>
        <div className="legend-row">
          <button className={`chip ${!filter ? "on" : ""}`} onClick={() => setFilter("")}>All <b>{d.items.length}</b></button>
          {LEGEND.filter(s => d.summary[s]).map(s => <button key={s} className={`chip st-${s} ${filter === s ? "on" : ""}`} onClick={() => setFilter(filter === s ? "" : s)}>{label(s)} <b>{d.summary[s]}</b></button>)}
        </div>
        {canAssign && unassigned.length > 0 && <Card title={`Arrivals without a room (${unassigned.length})`}>
          <p className="small muted">Drag a guest onto a free room — or click the guest, then click the room.</p>
          <div className="row gap-s wrap">{unassigned.map(r => <button key={r.id} draggable className={`arrival-chip ${picked?.id === r.id ? "on" : ""}`}
            onDragStart={e => { e.dataTransfer.setData("text/plain", String(r.id)); e.dataTransfer.effectAllowed = "move"; }}
            onClick={() => setPicked(picked?.id === r.id ? null : r)} aria-pressed={picked?.id === r.id}>
            <b>{r.first_name} {r.last_name}</b> <span className="muted small">{r.room_type_code} · {r.reference}</span></button>)}</div>
          {picked && <p className="small mt">Now click a free room for <b>{picked.first_name} {picked.last_name}</b> (or press Esc to cancel).</p>}
        </Card>}
        <div className="roomgrid" onKeyDown={e => { if (e.key === "Escape") setPicked(null); }}>
          {rooms.map((r: any) => (
            <button key={r.id} className={`room st-${r.display_status} ${over === r.id ? (free(r) ? "drop-ok" : "drop-no") : ""} ${picked && free(r) ? "drop-target" : ""}`}
              onClick={() => (picked ? assign(picked.id, r) : setSel(r))} aria-label={`Room ${r.number}, ${label(r.display_status)}`}
              onDragOver={e => { if (canAssign) { e.preventDefault(); e.dataTransfer.dropEffect = free(r) ? "move" : "none"; setOver(r.id); } }}
              onDragLeave={() => setOver(o => (o === r.id ? null : o))}
              onDrop={e => { e.preventDefault(); setOver(null); const id = Number(e.dataTransfer.getData("text/plain")); if (id) assign(id, r); }}>
              <div className="room-n">{r.number}{r.departing_today && <span className="dep" title="Due out today">DUE OUT</span>}</div>
              <div className="room-t">{r.room_type_code}</div>
              <div className="room-s">{label(r.display_status)}</div>
              <div className="room-g">{r.in_house?.guest_name || r.arrival?.guest_name || r.service_note || ""}</div>
            </button>))}
        </div>
      </>)}</Loadable>
      {sel && <Modal title={`Room ${sel.number} — ${sel.room_type_name}`} onClose={() => setSel(null)}>
        <div className="stack">
          <div className="row gap wrap"><Pill s={sel.display_status} /><span className="muted">Floor {sel.floor} · Housekeeping: {label(sel.hk_status)} · {label(sel.occupancy)}</span></div>
          {sel.in_house && <Card title="In-house"><p><b>{sel.in_house.guest_name}</b> · {sel.in_house.reference} · departs {sel.in_house.departure}</p>
            <Button kind="secondary" onClick={() => navigate(`/reservations?tab=search&q=${sel.in_house.reference}`)}>Open reservation</Button></Card>}
          {sel.arrival && <Card title="Arriving today"><p><b>{sel.arrival.guest_name}</b> · {sel.arrival.reference}</p></Card>}
          {sel.service_note && <p className="muted">Note: {sel.service_note}</p>}
          {can("rooms.status.update") && sel.occupancy === "vacant" && <div className="row gap-s wrap">
            {sel.hk_status !== "dirty" && <Button kind="secondary" busy={busy} onClick={() => hk("dirty")}>Mark dirty</Button>}
            {sel.hk_status !== "clean" && sel.hk_status !== "inspected" && <Button kind="secondary" busy={busy} onClick={() => hk("clean")}>Mark cleaned</Button>}
            {can("housekeeping.inspect") && sel.hk_status === "clean" && <Button busy={busy} onClick={() => hk("inspected")}>Pass inspection</Button>}
          </div>}
          {can("rooms.block") && (sel.service_status === "in_service" || sel.service_status === "vip_hold" ? (sel.occupancy === "vacant" && <div className="form-grid">
            <Field label="Take out of service as"><Select value={svc.service_status} onChange={e => setSvc({ ...svc, service_status: e.target.value })}>
              {["out_of_order", "out_of_service", "maintenance", "blocked", "vip_hold"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select></Field>
            <Field label="Reason" wide><Textarea value={svc.note} onChange={e => setSvc({ ...svc, note: e.target.value })} /></Field>
            <Button kind="danger" busy={busy} disabled={!svc.note.trim()} onClick={() => service(svc.service_status, svc.note)}>Update status</Button>
          </div>) : <Button busy={busy} onClick={() => service("in_service")}>Return to service</Button>)}
        </div>
      </Modal>}
    </div>
  );
}
