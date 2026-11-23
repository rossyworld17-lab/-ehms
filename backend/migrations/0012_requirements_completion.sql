-- EHMS migration 0012: requirements completion — backups with history and verification, wake-up calls, early check-in /
-- late check-out, table reservations, purchase returns, guest referrals, staff welfare, petty cash with payment vouchers,
-- room-type photo gallery and videos, CCTV clip links on access events, per-user language.

CREATE TABLE backups (
  id {PK},
  filename VARCHAR(200) NOT NULL,
  kind VARCHAR(10) NOT NULL CHECK (kind IN ('manual','scheduled')),
  status VARCHAR(10) NOT NULL CHECK (status IN ('ok','failed')),
  size_bytes INTEGER,
  tables_count INTEGER,
  rows_count INTEGER,
  checksum VARCHAR(64),
  verified INTEGER NOT NULL DEFAULT 0,
  error VARCHAR(500),
  created_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL
);

CREATE TABLE wake_up_calls (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  reservation_id {REF} NOT NULL REFERENCES reservations(id),
  call_date {DATE} NOT NULL,
  call_time VARCHAR(5) NOT NULL,
  note VARCHAR(200),
  status VARCHAR(10) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done','missed','cancelled')),
  done_by {REF} REFERENCES users(id),
  done_at {TS},
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_wakeup ON wake_up_calls(hotel_id, call_date, status);

ALTER TABLE reservations ADD COLUMN early_check_in INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reservations ADD COLUMN late_check_out_until VARCHAR(5);

CREATE TABLE table_reservations (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  outlet_id {REF} NOT NULL REFERENCES outlets(id),
  table_id {REF} REFERENCES pos_tables(id),
  guest_name VARCHAR(150) NOT NULL,
  phone VARCHAR(50),
  party_size INTEGER NOT NULL CHECK (party_size > 0),
  reserved_date {DATE} NOT NULL,
  reserved_time VARCHAR(5) NOT NULL,
  duration_min INTEGER NOT NULL DEFAULT 90,
  reservation_id {REF} REFERENCES reservations(id),
  status VARCHAR(10) NOT NULL DEFAULT 'booked' CHECK (status IN ('booked','seated','completed','cancelled','no_show')),
  notes VARCHAR(300),
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_table_res ON table_reservations(outlet_id, reserved_date);

CREATE TABLE purchase_returns (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  grn_id {REF} NOT NULL REFERENCES goods_receipts(id),
  po_id {REF} NOT NULL REFERENCES purchase_orders(id),
  supplier_id {REF} NOT NULL REFERENCES suppliers(id),
  invoice_id {REF} REFERENCES supplier_invoices(id),
  settlement VARCHAR(15) NOT NULL CHECK (settlement IN ('grni','invoice_credit')),
  value {MONEY} NOT NULL CHECK (value > 0),
  reason VARCHAR(300) NOT NULL,
  journal_entry_id {REF} REFERENCES journal_entries(id),
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE TABLE purchase_return_lines (
  id {PK},
  return_id {REF} NOT NULL REFERENCES purchase_returns(id),
  grn_line_id {REF} NOT NULL REFERENCES goods_receipt_lines(id),
  item_id {REF} REFERENCES inventory_items(id),
  quantity_milli INTEGER NOT NULL CHECK (quantity_milli > 0),
  unit_cost {MONEY} NOT NULL,
  value {MONEY} NOT NULL
);

CREATE TABLE referral_codes (
  id {PK},
  guest_id {REF} NOT NULL UNIQUE REFERENCES guests(id),
  code VARCHAR(20) NOT NULL UNIQUE,
  created_at {TS} NOT NULL
);
CREATE TABLE referrals (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  referrer_guest_id {REF} NOT NULL REFERENCES guests(id),
  referred_guest_id {REF} NOT NULL REFERENCES guests(id),
  reservation_id {REF} NOT NULL UNIQUE REFERENCES reservations(id),
  status VARCHAR(10) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','rewarded','void')),
  points INTEGER NOT NULL DEFAULT 0,
  created_at {TS} NOT NULL,
  rewarded_at {TS}
);

CREATE TABLE welfare_records (
  id {PK},
  employee_id {REF} NOT NULL REFERENCES employees(id),
  kind VARCHAR(20) NOT NULL CHECK (kind IN ('medical','bereavement','wedding','childbirth','hardship','wellbeing','other')),
  support_date {DATE} NOT NULL,
  amount {MONEY} NOT NULL DEFAULT 0,
  description VARCHAR(300) NOT NULL,
  confidential INTEGER NOT NULL DEFAULT 1,
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_welfare_emp ON welfare_records(employee_id);

CREATE TABLE petty_cash_funds (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  name VARCHAR(100) NOT NULL,
  account_id {REF} NOT NULL REFERENCES accounts(id),
  custodian_id {REF} NOT NULL REFERENCES users(id),
  imprest {MONEY} NOT NULL CHECK (imprest > 0),
  voucher_limit {MONEY} NOT NULL CHECK (voucher_limit > 0),
  active INTEGER NOT NULL DEFAULT 1,
  created_at {TS} NOT NULL
);
CREATE TABLE petty_cash_entries (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  fund_id {REF} NOT NULL REFERENCES petty_cash_funds(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  kind VARCHAR(10) NOT NULL CHECK (kind IN ('voucher','top_up')),
  payee VARCHAR(150),
  description VARCHAR(300) NOT NULL,
  expense_account_id {REF} REFERENCES accounts(id),
  source_account_id {REF} REFERENCES accounts(id),
  department VARCHAR(30),
  amount {MONEY} NOT NULL CHECK (amount > 0),
  status VARCHAR(10) NOT NULL CHECK (status IN ('pending','approved','rejected','posted')),
  requested_by {REF} NOT NULL REFERENCES users(id),
  decided_by {REF} REFERENCES users(id),
  decision_note VARCHAR(300),
  journal_entry_id {REF} REFERENCES journal_entries(id),
  created_at {TS} NOT NULL,
  decided_at {TS}
);
CREATE INDEX ix_petty_fund ON petty_cash_entries(fund_id, status);

CREATE TABLE room_type_media (
  id {PK},
  room_type_id {REF} NOT NULL REFERENCES room_types(id),
  kind VARCHAR(10) NOT NULL CHECK (kind IN ('photo','video')),
  filename VARCHAR(200),
  content_type VARCHAR(50),
  url VARCHAR(500),
  caption VARCHAR(150),
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_rt_media ON room_type_media(room_type_id, sort_order);

ALTER TABLE access_events ADD COLUMN clip_url VARCHAR(500);
ALTER TABLE users ADD COLUMN language VARCHAR(5) NOT NULL DEFAULT 'en';
