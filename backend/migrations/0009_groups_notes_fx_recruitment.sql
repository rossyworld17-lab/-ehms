-- EHMS migration 0009: exchange rates and foreign-currency payments, cancellation policies and fees, group blocks
-- and rooming lists, additional folios (split billing) and charge transfers, credit / debit notes, FIFO stock
-- costing, recruitment.

-- ------------------------------------------------------------------ exchange rates
CREATE TABLE exchange_rates (
  id {PK},
  organisation_id {REF} NOT NULL REFERENCES organisations(id),
  currency CHAR(3) NOT NULL,
  rate_date {DATE} NOT NULL,
  rate_micro {MONEY} NOT NULL CHECK (rate_micro > 0),   -- base-currency units per 1 foreign unit, x 1,000,000
  source VARCHAR(100),
  created_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL,
  UNIQUE (organisation_id, currency, rate_date)
);
ALTER TABLE payments ADD COLUMN foreign_currency CHAR(3);
ALTER TABLE payments ADD COLUMN foreign_amount {MONEY};
ALTER TABLE payments ADD COLUMN exchange_rate_micro {MONEY};

-- ------------------------------------------------------------------ cancellation policies
CREATE TABLE cancellation_policies (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  name VARCHAR(100) NOT NULL,
  free_until_hours INTEGER NOT NULL DEFAULT 24 CHECK (free_until_hours >= 0),
  fee_type VARCHAR(12) NOT NULL DEFAULT 'first_night' CHECK (fee_type IN ('none','first_night','percent','fixed')),
  fee_value {MONEY} NOT NULL DEFAULT 0,
  no_show_fee_type VARCHAR(12) NOT NULL DEFAULT 'first_night' CHECK (no_show_fee_type IN ('none','first_night','percent','fixed')),
  no_show_fee_value {MONEY} NOT NULL DEFAULT 0,
  is_default INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at {TS} NOT NULL
);
ALTER TABLE reservations ADD COLUMN cancellation_policy_id {REF} REFERENCES cancellation_policies(id);
ALTER TABLE reservations ADD COLUMN cancellation_fee {MONEY};
ALTER TABLE reservations ADD COLUMN fee_waived_by {REF} REFERENCES users(id);
ALTER TABLE reservations ADD COLUMN fee_waive_reason VARCHAR(300);

-- ------------------------------------------------------------------ group blocks
CREATE TABLE group_blocks (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  code VARCHAR(30) NOT NULL,
  name VARCHAR(200) NOT NULL,
  corporate_account_id {REF} REFERENCES corporate_accounts(id),
  contact_guest_id {REF} REFERENCES guests(id),
  arrival {DATE} NOT NULL,
  departure {DATE} NOT NULL,
  cutoff_date {DATE} NOT NULL,
  status VARCHAR(12) NOT NULL DEFAULT 'tentative' CHECK (status IN ('tentative','definite','released','cancelled','completed')),
  billing VARCHAR(12) NOT NULL DEFAULT 'individual' CHECK (billing IN ('individual','master_room','master_all')),
  master_folio_id {REF} REFERENCES folios(id),
  notes TEXT,
  created_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL,
  released_at {TS},
  UNIQUE (hotel_id, code),
  CHECK (departure > arrival)
);
CREATE TABLE group_block_rooms (
  id {PK},
  block_id {REF} NOT NULL REFERENCES group_blocks(id),
  room_type_id {REF} NOT NULL REFERENCES room_types(id),
  rooms INTEGER NOT NULL CHECK (rooms >= 0),
  rate {MONEY} NOT NULL CHECK (rate >= 0),
  UNIQUE (block_id, room_type_id)
);
ALTER TABLE reservations ADD COLUMN group_block_id {REF} REFERENCES group_blocks(id);
CREATE INDEX ix_res_block ON reservations(group_block_id);

-- ------------------------------------------------------------------ additional folios and transfers
ALTER TABLE folios ADD COLUMN linked_reservation_id {REF} REFERENCES reservations(id);
ALTER TABLE folios ADD COLUMN window_name VARCHAR(80);
ALTER TABLE folios ADD COLUMN corporate_account_id {REF} REFERENCES corporate_accounts(id);
ALTER TABLE folios ADD COLUMN group_block_id {REF} REFERENCES group_blocks(id);
ALTER TABLE folio_lines ADD COLUMN transfer_ref VARCHAR(40);

-- ------------------------------------------------------------------ credit / debit notes
CREATE TABLE customer_notes (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  kind VARCHAR(6) NOT NULL CHECK (kind IN ('credit','debit')),
  folio_id {REF} NOT NULL REFERENCES folios(id),
  department VARCHAR(30) NOT NULL,
  description VARCHAR(300) NOT NULL,
  reason TEXT NOT NULL,
  net_amount {MONEY} NOT NULL CHECK (net_amount > 0),
  service_charge {MONEY} NOT NULL DEFAULT 0,
  tax_amount {MONEY} NOT NULL DEFAULT 0,
  total_amount {MONEY} NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'pending_approval' CHECK (status IN ('pending_approval','approved','rejected')),
  requested_by {REF} NOT NULL REFERENCES users(id),
  decided_by {REF} REFERENCES users(id),
  decision_note VARCHAR(300),
  folio_line_id {REF} REFERENCES folio_lines(id),
  journal_entry_id {REF} REFERENCES journal_entries(id),
  created_at {TS} NOT NULL,
  decided_at {TS}
);

-- ------------------------------------------------------------------ FIFO costing
ALTER TABLE stock_batches ADD COLUMN unit_cost {MONEY};

-- ------------------------------------------------------------------ recruitment
CREATE TABLE job_openings (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  reference VARCHAR(30) NOT NULL UNIQUE,
  title VARCHAR(150) NOT NULL,
  department VARCHAR(30) NOT NULL,
  employment_type VARCHAR(20) NOT NULL DEFAULT 'full_time',
  positions INTEGER NOT NULL DEFAULT 1 CHECK (positions > 0),
  salary_min {MONEY},
  salary_max {MONEY},
  description TEXT,
  status VARCHAR(12) NOT NULL DEFAULT 'open' CHECK (status IN ('draft','open','on_hold','filled','closed')),
  closing_date {DATE},
  created_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE TABLE applicants (
  id {PK},
  opening_id {REF} NOT NULL REFERENCES job_openings(id),
  first_name VARCHAR(100) NOT NULL,
  last_name VARCHAR(100) NOT NULL,
  email VARCHAR(200),
  phone VARCHAR(50),
  source VARCHAR(40),
  stage VARCHAR(12) NOT NULL DEFAULT 'applied' CHECK (stage IN ('applied','screening','interview','offer','hired','rejected','withdrawn')),
  rating INTEGER CHECK (rating BETWEEN 1 AND 5),
  expected_salary {MONEY},
  offered_salary {MONEY},
  start_date {DATE},
  employee_id {REF} REFERENCES employees(id),
  consent_to_retain INTEGER NOT NULL DEFAULT 0,
  created_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL,
  updated_at {TS} NOT NULL
);
CREATE TABLE applicant_events (
  id {PK},
  applicant_id {REF} NOT NULL REFERENCES applicants(id),
  kind VARCHAR(12) NOT NULL CHECK (kind IN ('stage','note','interview')),
  from_stage VARCHAR(12),
  to_stage VARCHAR(12),
  note TEXT,
  interview_at {TS},
  score INTEGER,
  created_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL
);
