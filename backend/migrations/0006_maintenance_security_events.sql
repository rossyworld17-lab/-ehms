-- EHMS migration 0006: maintenance & assets, security & lost property, events & banqueting.

-- ------------------------------------------------------------------ assets & maintenance
CREATE TABLE assets (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  code VARCHAR(40) NOT NULL,
  name VARCHAR(150) NOT NULL,
  category VARCHAR(30) NOT NULL,
  location VARCHAR(150),
  room_id {REF} REFERENCES rooms(id),
  serial_no VARCHAR(80),
  manufacturer VARCHAR(100),
  supplier_id {REF} REFERENCES suppliers(id),
  purchase_date {DATE},
  purchase_cost {MONEY} NOT NULL DEFAULT 0,
  salvage_value {MONEY} NOT NULL DEFAULT 0,
  useful_life_months INTEGER NOT NULL DEFAULT 60,
  capitalised INTEGER NOT NULL DEFAULT 0,
  accumulated_depreciation {MONEY} NOT NULL DEFAULT 0,
  warranty_until {DATE},
  status VARCHAR(20) NOT NULL DEFAULT 'operational' CHECK (status IN ('operational','under_repair','out_of_service','retired')),
  notes TEXT,
  created_at {TS} NOT NULL,
  UNIQUE (hotel_id, code)
);

CREATE TABLE asset_depreciation (
  id {PK},
  asset_id {REF} NOT NULL REFERENCES assets(id),
  period CHAR(7) NOT NULL,
  amount {MONEY} NOT NULL,
  journal_entry_id {REF} REFERENCES journal_entries(id),
  UNIQUE (asset_id, period)
);

CREATE TABLE maintenance_schedules (
  id {PK},
  asset_id {REF} NOT NULL REFERENCES assets(id),
  title VARCHAR(150) NOT NULL,
  frequency_days INTEGER NOT NULL CHECK (frequency_days > 0),
  next_due {DATE} NOT NULL,
  last_done {DATE},
  checklist TEXT,
  assigned_to {REF} REFERENCES users(id),
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE work_orders (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  asset_id {REF} REFERENCES assets(id),
  room_id {REF} REFERENCES rooms(id),
  schedule_id {REF} REFERENCES maintenance_schedules(id),
  title VARCHAR(200) NOT NULL,
  description TEXT,
  kind VARCHAR(20) NOT NULL DEFAULT 'corrective' CHECK (kind IN ('corrective','preventive','inspection')),
  priority VARCHAR(10) NOT NULL DEFAULT 'normal' CHECK (priority IN ('urgent','high','normal','low')),
  status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open','assigned','in_progress','on_hold','completed','verified','cancelled')),
  blocks_room INTEGER NOT NULL DEFAULT 0,
  reported_by {REF} NOT NULL REFERENCES users(id),
  assigned_to {REF} REFERENCES users(id),
  service_provider_id {REF} REFERENCES suppliers(id),
  resolution TEXT,
  labour_hours INTEGER NOT NULL DEFAULT 0,
  parts_cost {MONEY} NOT NULL DEFAULT 0,
  vendor_cost {MONEY} NOT NULL DEFAULT 0,
  due_date {DATE},
  created_at {TS} NOT NULL,
  started_at {TS},
  completed_at {TS},
  verified_by {REF} REFERENCES users(id),
  verified_at {TS}
);
CREATE INDEX ix_wo_status ON work_orders(hotel_id, status);

CREATE TABLE work_order_parts (
  id {PK},
  work_order_id {REF} NOT NULL REFERENCES work_orders(id),
  item_id {REF} NOT NULL REFERENCES inventory_items(id),
  store_id {REF} NOT NULL REFERENCES stores(id),
  quantity_milli INTEGER NOT NULL CHECK (quantity_milli > 0),
  value {MONEY} NOT NULL,
  journal_entry_id {REF} REFERENCES journal_entries(id),
  issued_by {REF} NOT NULL REFERENCES users(id),
  issued_at {TS} NOT NULL
);

CREATE TABLE work_order_notes (
  id {PK},
  work_order_id {REF} NOT NULL REFERENCES work_orders(id),
  note TEXT NOT NULL,
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);

-- ------------------------------------------------------------------ security
CREATE TABLE security_incidents (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  occurred_at {TS} NOT NULL,
  location VARCHAR(150) NOT NULL,
  category VARCHAR(20) NOT NULL,
  severity VARCHAR(10) NOT NULL CHECK (severity IN ('low','medium','high','critical')),
  description TEXT NOT NULL,
  persons_involved TEXT,
  actions_taken TEXT,
  police_reference VARCHAR(80),
  guest_id {REF} REFERENCES guests(id),
  room_id {REF} REFERENCES rooms(id),
  restricted INTEGER NOT NULL DEFAULT 0,
  status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open','investigating','resolved','closed')),
  assigned_to {REF} REFERENCES users(id),
  resolution TEXT,
  reported_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL,
  resolved_at {TS}
);

CREATE TABLE incident_notes (
  id {PK},
  incident_id {REF} NOT NULL REFERENCES security_incidents(id),
  note TEXT NOT NULL,
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);

CREATE TABLE visitors (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  kind VARCHAR(12) NOT NULL CHECK (kind IN ('visitor','contractor','delivery')),
  name VARCHAR(150) NOT NULL,
  phone VARCHAR(50),
  company VARCHAR(150),
  id_type VARCHAR(30),
  id_number VARCHAR(60),
  host VARCHAR(150),
  purpose VARCHAR(200),
  badge_no VARCHAR(30),
  vehicle_plate VARCHAR(20),
  time_in {TS} NOT NULL,
  time_out {TS},
  recorded_by {REF} NOT NULL REFERENCES users(id)
);
CREATE INDEX ix_visitors_open ON visitors(hotel_id, time_out);

CREATE TABLE lost_found (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  found_at {TS} NOT NULL,
  location VARCHAR(150) NOT NULL,
  room_id {REF} REFERENCES rooms(id),
  description VARCHAR(300) NOT NULL,
  category VARCHAR(30) NOT NULL,
  valuable INTEGER NOT NULL DEFAULT 0,
  stored_location VARCHAR(100),
  found_by {REF} NOT NULL REFERENCES users(id),
  guest_id {REF} REFERENCES guests(id),
  status VARCHAR(20) NOT NULL DEFAULT 'stored' CHECK (status IN ('stored','returned','disposed','donated')),
  claimant_name VARCHAR(150),
  claimant_contact VARCHAR(150),
  claimant_id_checked INTEGER NOT NULL DEFAULT 0,
  released_by {REF} REFERENCES users(id),
  released_at {TS},
  dispose_after {DATE} NOT NULL,
  notes VARCHAR(300)
);

CREATE TABLE emergency_contacts (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  name VARCHAR(150) NOT NULL,
  role VARCHAR(100) NOT NULL,
  phone VARCHAR(50) NOT NULL,
  notes VARCHAR(200),
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE access_events (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  source VARCHAR(40) NOT NULL,
  door VARCHAR(80) NOT NULL,
  credential VARCHAR(80),
  person VARCHAR(150),
  event VARCHAR(30) NOT NULL,
  occurred_at {TS} NOT NULL,
  received_at {TS} NOT NULL
);
CREATE INDEX ix_access_events ON access_events(hotel_id, occurred_at);

-- ------------------------------------------------------------------ events & banqueting
CREATE TABLE venues (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  code VARCHAR(20) NOT NULL,
  name VARCHAR(100) NOT NULL,
  capacity_theatre INTEGER NOT NULL DEFAULT 0,
  capacity_banquet INTEGER NOT NULL DEFAULT 0,
  capacity_classroom INTEGER NOT NULL DEFAULT 0,
  area_sqm INTEGER,
  hourly_rate {MONEY} NOT NULL DEFAULT 0,
  daily_rate {MONEY} NOT NULL DEFAULT 0,
  facilities TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE (hotel_id, code)
);

CREATE TABLE events (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  title VARCHAR(200) NOT NULL,
  event_type VARCHAR(20) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'enquiry' CHECK (status IN ('enquiry','tentative','confirmed','completed','cancelled')),
  client_name VARCHAR(150) NOT NULL,
  client_phone VARCHAR(50),
  client_email VARCHAR(200),
  company VARCHAR(150),
  guest_id {REF} REFERENCES guests(id),
  folio_id {REF} REFERENCES folios(id),
  start_at {TS} NOT NULL,
  end_at {TS} NOT NULL,
  expected_guests INTEGER NOT NULL DEFAULT 0,
  layout VARCHAR(20),
  deposit_required {MONEY} NOT NULL DEFAULT 0,
  notes TEXT,
  sales_owner {REF} REFERENCES users(id),
  invoiced_at {TS},
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL,
  cancel_reason VARCHAR(300)
);

CREATE TABLE event_venues (
  id {PK},
  event_id {REF} NOT NULL REFERENCES events(id),
  venue_id {REF} NOT NULL REFERENCES venues(id),
  start_at {TS} NOT NULL,
  end_at {TS} NOT NULL
);
CREATE INDEX ix_event_venues ON event_venues(venue_id, start_at);

CREATE TABLE event_items (
  id {PK},
  event_id {REF} NOT NULL REFERENCES events(id),
  kind VARCHAR(20) NOT NULL CHECK (kind IN ('venue','catering','beverage','equipment','decoration','accommodation','service','other')),
  description VARCHAR(200) NOT NULL,
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price {MONEY} NOT NULL CHECK (unit_price >= 0),
  folio_line_id {REF} REFERENCES folio_lines(id)
);

CREATE TABLE event_costs (
  id {PK},
  event_id {REF} NOT NULL REFERENCES events(id),
  description VARCHAR(200) NOT NULL,
  amount {MONEY} NOT NULL CHECK (amount > 0),
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);

CREATE TABLE event_staff (
  id {PK},
  event_id {REF} NOT NULL REFERENCES events(id),
  employee_id {REF} NOT NULL REFERENCES employees(id),
  role VARCHAR(100) NOT NULL,
  UNIQUE (event_id, employee_id)
);
