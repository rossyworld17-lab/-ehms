import React, { useEffect, useState } from "react";
import { addDays, get } from "../api";
import { navigate, useAuth } from "../state";
import { Button, Card, Loadable, Select, useLoad } from "../ui";

export default function Calendar() {
  const { hotel } = useAuth();
  const [start, setStart] = useState("");
  const [days, setDays] = useState(14);
  useEffect(() => { get(`/api/hotels/${hotel!.id}`).then(h => setStart(h.business_date)); }, [hotel?.id]);
  const st = useLoad(() => (start ? get(`/api/hotels/${hotel!.id}/calendar`, { start, days }) : Promise.resolve(null)), [hotel?.id, start, days]);
  const dates = start ? Array.from({ length: days }, (_, i) => addDays(start, i)) : [];
  return (
    <div className="page">
      <div className="page-h"><div><h1>Availability calendar</h1><p className="muted">Room-by-day view. Click a booking to open it.</p></div>
        <div className="row gap-s">
          <Button kind="secondary" onClick={() => setStart(addDays(start, -days))}>← Earlier</Button>
          <input type="date" className="input" value={start} onChange={e => setStart(e.target.value)} aria-label="Start date" />
          <Select value={days} onChange={e => setDays(Number(e.target.value))} aria-label="Days shown">{[7, 14, 21, 31].map(d => <option key={d} value={d}>{d} days</option>)}</Select>
          <Button kind="secondary" onClick={() => setStart(addDays(start, days))}>Later →</Button>
        </div></div>
      <Card pad={false}><Loadable state={st as any}>{(d: any) => {
        if (!d) return null;
        const col = (iso: string) => dates.indexOf(iso);
        return <div className="tape" style={{ gridTemplateColumns: `90px repeat(${days}, minmax(44px, 1fr))` }}>
          <div className="tape-h sticky">Room</div>
          {dates.map(x => { const dt = new Date(x + "T00:00:00"); const we = [5, 6].includes(dt.getDay()); return <div key={x} className={`tape-h ${we ? "we" : ""}`}>{dt.toLocaleDateString("en-GB", { weekday: "short" })}<b>{dt.getDate()}</b></div>; })}
          {d.rooms.map((room: any, ri: number) => {
            const bookings = d.reservations.filter((r: any) => r.room_id === room.id);
            return <React.Fragment key={room.id}>
              <div className="tape-r sticky" style={{ gridRow: ri + 2 }}><b>{room.number}</b><small>{room.room_type_code}</small></div>
              {dates.map((x, ci) => <div key={x} className={`tape-c ${room.service_status !== "in_service" && room.service_status !== "vip_hold" ? "ooo" : ""}`} style={{ gridRow: ri + 2, gridColumn: ci + 2 }} />)}
              {bookings.map((b: any) => {
                const s = Math.max(0, col(b.arrival) === -1 ? (b.arrival < dates[0] ? 0 : -1) : col(b.arrival));
                const eIdx = col(b.departure);
                const e = eIdx === -1 ? (b.departure > dates[dates.length - 1] ? days : -1) : eIdx;
                if (s < 0 || e <= s) return null;
                return <button key={b.id} className={`tape-b tb-${b.status}`} style={{ gridRow: ri + 2, gridColumn: `${s + 2} / ${e + 2}` }}
                  title={`${b.reference} · ${b.guest_name} · ${b.arrival} → ${b.departure}`} onClick={() => navigate(`/reservations/${b.id}`)}>{b.guest_name}</button>;
              })}
            </React.Fragment>;
          })}
        </div>;
      }}</Loadable></Card>
      {st.data && (st.data as any).unassigned.length > 0 && <Card title={`Unassigned reservations (${(st.data as any).unassigned.length})`}>
        <div className="row gap-s wrap">{(st.data as any).unassigned.map((u: any) => <a key={u.id} className="chip" href={`#/reservations/${u.id}`}>{u.reference} · {u.guest_name} · {u.arrival}</a>)}</div>
      </Card>}
    </div>
  );
}
