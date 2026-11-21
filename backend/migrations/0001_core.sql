-- EHMS migration 0001: core schema
-- Tokens rendered per dialect by ehms/migrate.py:
--   {PK} primary key, {REF} foreign-key integer, {DATE} date, {TS} timestamp, {MONEY} integer minor units

CREATE TABLE organisations (
  id {PK},
  code VARCHAR(30) NOT NULL UNIQUE,
  name VARCHAR(200) NOT NULL,
  created_at {TS} NOT NULL
);

CREATE TABLE hotels (
  id {PK},
  organisation_id {REF} NOT NULL REFERENCES organisations(id),
  code VARCHAR(30) NOT NULL,
  name VARCHAR(200) NOT NULL,
  legal_name VARCHAR(200),
  registration_number VARCHAR(100),
  category VARCHAR(50) DEFAULT 'hotel',
  star_rating INTEGER,
  address TEXT,
  city VARCHAR(100),
  state VARCHAR(100),
  country VARCHAR(100) DEFAULT 'Nigeria',
  phone VARCHAR(50),
  email VARCHAR(200),
  website VARCHAR(200),
  emergency_contact VARCHAR(200),
  floors INTEGER,
  timezone VARCHAR(64) NOT NULL DEFAULT 'Africa/Lagos',
  currency CHAR(3) NOT NULL DEFAULT 'NGN',
  check_in_time VARCHAR(5) NOT NULL DEFAULT '14:00',
  check_out_time VARCHAR(5) NOT NULL DEFAULT '12:00',
  cancellation_policy TEXT,
  reservation_policy TEXT,
  terms TEXT,
  amenities TEXT,
  service_charge_bp INTEGER NOT NULL DEFAULT 0,
  business_date {DATE},
  active INTEGER NOT NULL DEFAULT 1,
  created_at {TS} NOT NULL,
  UNIQUE (organisation_id, code)
);

CREATE TABLE departments (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  code VARCHAR(30) NOT NULL,
  name VARCHAR(100) NOT NULL,
  UNIQUE (hotel_id, code)
);

CREATE TABLE users (
  id {PK},
  organisation_id {REF} REFERENCES organisations(id),
  email VARCHAR(200) NOT NULL UNIQUE,
  full_name VARCHAR(200) NOT NULL,
  phone VARCHAR(50),
  department_id {REF} REFERENCES departments(id),
  password_hash VARCHAR(300) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','deactivated')),
  all_hotels INTEGER NOT NULL DEFAULT 0,
  mfa_enabled INTEGER NOT NULL DEFAULT 0,
  mfa_secret VARCHAR(64),
  failed_logins INTEGER NOT NULL DEFAULT 0,
  locked_until {TS},
  last_login_at {TS},
  password_changed_at {TS},
  must_change_password INTEGER NOT NULL DEFAULT 0,
  created_at {TS} NOT NULL
);

CREATE TABLE user_hotels (
  user_id {REF} NOT NULL REFERENCES users(id),
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  PRIMARY KEY (user_id, hotel_id)
);

CREATE TABLE permissions (
  code VARCHAR(80) PRIMARY KEY,
  module VARCHAR(50) NOT NULL,
  description VARCHAR(200) NOT NULL
);

CREATE TABLE roles (
  id {PK},
  organisation_id {REF} REFERENCES organisations(id),
  code VARCHAR(60) NOT NULL,
  name VARCHAR(100) NOT NULL,
  description VARCHAR(300),
  is_system INTEGER NOT NULL DEFAULT 0,
  UNIQUE (organisation_id, code)
);

CREATE TABLE role_permissions (
  role_id {REF} NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  permission_code VARCHAR(80) NOT NULL REFERENCES permissions(code),
  PRIMARY KEY (role_id, permission_code)
);

CREATE TABLE user_roles (
  user_id {REF} NOT NULL REFERENCES users(id),
  role_id {REF} NOT NULL REFERENCES roles(id),
  PRIMARY KEY (user_id, role_id)
);

CREATE TABLE sessions (
  id {PK},
  user_id {REF} NOT NULL REFERENCES users(id),
  jti VARCHAR(64) NOT NULL UNIQUE,
  ip VARCHAR(64),
  user_agent VARCHAR(300),
  created_at {TS} NOT NULL,
  last_seen_at {TS} NOT NULL,
  expires_at {TS} NOT NULL,
  revoked_at {TS},
  mfa_pending INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX ix_sessions_user ON sessions(user_id);

CREATE TABLE password_resets (
  id {PK},
  user_id {REF} NOT NULL REFERENCES users(id),
  token_hash VARCHAR(128) NOT NULL UNIQUE,
  expires_at {TS} NOT NULL,
  used_at {TS},
  created_at {TS} NOT NULL
);

CREATE TABLE login_attempts (
  id {PK},
  email VARCHAR(200),
  user_id {REF} REFERENCES users(id),
  success INTEGER NOT NULL,
  reason VARCHAR(100),
  ip VARCHAR(64),
  user_agent VARCHAR(300),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_login_attempts_email ON login_attempts(email);

CREATE TABLE audit_logs (
  id {PK},
  organisation_id {REF},
  hotel_id {REF},
  user_id {REF},
  action VARCHAR(80) NOT NULL,
  entity VARCHAR(60),
  entity_id VARCHAR(60),
  reference VARCHAR(80),
  old_value TEXT,
  new_value TEXT,
  ip VARCHAR(64),
  user_agent VARCHAR(300),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_audit_entity ON audit_logs(entity, entity_id);
CREATE INDEX ix_audit_created ON audit_logs(created_at);

CREATE TABLE sequences (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  name VARCHAR(40) NOT NULL,
  next_value INTEGER NOT NULL DEFAULT 1,
  UNIQUE (hotel_id, name)
);

CREATE TABLE tax_rules (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  code VARCHAR(30) NOT NULL,
  name VARCHAR(100) NOT NULL,
  rate_bp INTEGER NOT NULL CHECK (rate_bp >= 0 AND rate_bp <= 10000),
  applies_to VARCHAR(30) NOT NULL DEFAULT 'all',
  is_inclusive INTEGER NOT NULL DEFAULT 0,
  effective_from {DATE} NOT NULL,
  effective_to {DATE},
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE accounts (
  id {PK},
  organisation_id {REF} NOT NULL REFERENCES organisations(id),
  code VARCHAR(20) NOT NULL,
  name VARCHAR(150) NOT NULL,
  type VARCHAR(20) NOT NULL CHECK (type IN ('asset','liability','equity','revenue','expense')),
  parent_id {REF} REFERENCES accounts(id),
  is_postable INTEGER NOT NULL DEFAULT 1,
  system_key VARCHAR(40),
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE (organisation_id, code)
);

CREATE TABLE payment_methods (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  code VARCHAR(30) NOT NULL,
  name VARCHAR(100) NOT NULL,
  kind VARCHAR(20) NOT NULL CHECK (kind IN ('cash','bank_transfer','card_pos','online','city_ledger')),
  account_id {REF} NOT NULL REFERENCES accounts(id),
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE (hotel_id, code)
);

CREATE TABLE room_types (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  code VARCHAR(20) NOT NULL,
  name VARCHAR(100) NOT NULL,
  description TEXT,
  max_occupancy INTEGER NOT NULL DEFAULT 2 CHECK (max_occupancy > 0),
  beds INTEGER NOT NULL DEFAULT 1,
  bed_config VARCHAR(100),
  size_sqm INTEGER,
  amenities TEXT,
  base_rate {MONEY} NOT NULL CHECK (base_rate >= 0),
  weekend_rate {MONEY},
  corporate_rate {MONEY},
  extra_person_charge {MONEY} NOT NULL DEFAULT 0,
  image_url VARCHAR(300),
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE (hotel_id, code)
);

CREATE TABLE rooms (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  room_type_id {REF} NOT NULL REFERENCES room_types(id),
  number VARCHAR(20) NOT NULL,
  name VARCHAR(100),
  floor VARCHAR(20),
  wing VARCHAR(50),
  occupancy VARCHAR(20) NOT NULL DEFAULT 'vacant' CHECK (occupancy IN ('vacant','occupied')),
  hk_status VARCHAR(20) NOT NULL DEFAULT 'clean' CHECK (hk_status IN ('clean','dirty','in_progress','inspected')),
  service_status VARCHAR(20) NOT NULL DEFAULT 'in_service' CHECK (service_status IN ('in_service','out_of_order','out_of_service','maintenance','blocked','vip_hold')),
  service_note VARCHAR(300),
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE (hotel_id, number)
);

CREATE TABLE guests (
  id {PK},
  organisation_id {REF} NOT NULL REFERENCES organisations(id),
  first_name VARCHAR(100) NOT NULL,
  last_name VARCHAR(100) NOT NULL,
  email VARCHAR(200),
  phone VARCHAR(50),
  nationality VARCHAR(100),
  address TEXT,
  date_of_birth {DATE},
  id_type VARCHAR(50),
  id_number VARCHAR(100),
  company VARCHAR(200),
  preferences TEXT,
  vip INTEGER NOT NULL DEFAULT 0,
  marketing_consent INTEGER NOT NULL DEFAULT 0,
  notes TEXT,
  created_at {TS} NOT NULL
);
CREATE INDEX ix_guests_name ON guests(last_name, first_name);
CREATE INDEX ix_guests_email ON guests(email);
CREATE INDEX ix_guests_phone ON guests(phone);

CREATE TABLE reservations (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  reference VARCHAR(30) NOT NULL UNIQUE,
  guest_id {REF} NOT NULL REFERENCES guests(id),
  status VARCHAR(20) NOT NULL CHECK (status IN ('enquiry','tentative','confirmed','checked_in','checked_out','cancelled','no_show','waitlisted')),
  booking_type VARCHAR(20) NOT NULL DEFAULT 'individual' CHECK (booking_type IN ('individual','group','corporate','walk_in','travel_agent','vip','event')),
  source VARCHAR(30) NOT NULL DEFAULT 'front_desk',
  arrival {DATE} NOT NULL,
  departure {DATE} NOT NULL,
  adults INTEGER NOT NULL DEFAULT 1 CHECK (adults > 0),
  children INTEGER NOT NULL DEFAULT 0 CHECK (children >= 0),
  room_type_id {REF} NOT NULL REFERENCES room_types(id),
  room_id {REF} REFERENCES rooms(id),
  nightly_rate {MONEY} NOT NULL CHECK (nightly_rate >= 0),
  rate_overridden INTEGER NOT NULL DEFAULT 0,
  discount_amount {MONEY} NOT NULL DEFAULT 0,
  deposit_required {MONEY} NOT NULL DEFAULT 0,
  company_name VARCHAR(200),
  group_name VARCHAR(200),
  special_requests TEXT,
  notes TEXT,
  created_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL,
  updated_at {TS} NOT NULL,
  cancelled_at {TS},
  cancel_reason VARCHAR(300),
  checked_in_at {TS},
  checked_out_at {TS},
  CHECK (departure > arrival)
);
CREATE INDEX ix_res_hotel_dates ON reservations(hotel_id, arrival, departure);
CREATE INDEX ix_res_room ON reservations(room_id);
CREATE INDEX ix_res_guest ON reservations(guest_id);

CREATE TABLE folios (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  reservation_id {REF} REFERENCES reservations(id),
  guest_id {REF} NOT NULL REFERENCES guests(id),
  status VARCHAR(10) NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
  opened_at {TS} NOT NULL,
  closed_at {TS}
);
CREATE UNIQUE INDEX ux_folio_reservation ON folios(reservation_id);

CREATE TABLE journal_entries (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  entry_date {DATE} NOT NULL,
  description VARCHAR(300) NOT NULL,
  source VARCHAR(30) NOT NULL,
  source_ref VARCHAR(80),
  reversal_of {REF} REFERENCES journal_entries(id),
  created_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL
);

CREATE TABLE journal_lines (
  id {PK},
  entry_id {REF} NOT NULL REFERENCES journal_entries(id),
  account_id {REF} NOT NULL REFERENCES accounts(id),
  debit {MONEY} NOT NULL DEFAULT 0,
  credit {MONEY} NOT NULL DEFAULT 0,
  department VARCHAR(30),
  memo VARCHAR(300),
  CHECK (debit >= 0 AND credit >= 0 AND (debit = 0 OR credit = 0) AND (debit + credit) > 0)
);
CREATE INDEX ix_jl_entry ON journal_lines(entry_id);
CREATE INDEX ix_jl_account ON journal_lines(account_id);

CREATE TABLE payments (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  folio_id {REF} NOT NULL REFERENCES folios(id),
  method_id {REF} NOT NULL REFERENCES payment_methods(id),
  kind VARCHAR(10) NOT NULL DEFAULT 'payment' CHECK (kind IN ('payment','refund')),
  amount {MONEY} NOT NULL CHECK (amount > 0),
  currency CHAR(3) NOT NULL DEFAULT 'NGN',
  status VARCHAR(20) NOT NULL CHECK (status IN ('completed','pending','failed')),
  reference VARCHAR(100),
  idempotency_key VARCHAR(100) UNIQUE,
  gateway VARCHAR(30),
  gateway_reference VARCHAR(100),
  note VARCHAR(300),
  received_by {REF} REFERENCES users(id),
  journal_entry_id {REF} REFERENCES journal_entries(id),
  created_at {TS} NOT NULL
);

CREATE TABLE folio_lines (
  id {PK},
  folio_id {REF} NOT NULL REFERENCES folios(id),
  business_date {DATE} NOT NULL,
  kind VARCHAR(12) NOT NULL CHECK (kind IN ('charge','payment','refund','adjustment')),
  department VARCHAR(30) NOT NULL,
  description VARCHAR(300) NOT NULL,
  quantity INTEGER NOT NULL DEFAULT 1,
  net_amount {MONEY} NOT NULL,
  tax_amount {MONEY} NOT NULL DEFAULT 0,
  service_charge {MONEY} NOT NULL DEFAULT 0,
  total_amount {MONEY} NOT NULL,
  reference VARCHAR(80),
  payment_id {REF} REFERENCES payments(id),
  journal_entry_id {REF} REFERENCES journal_entries(id),
  reverses_line_id {REF} REFERENCES folio_lines(id),
  posted_by {REF} REFERENCES users(id),
  posted_at {TS} NOT NULL
);
CREATE INDEX ix_fl_folio ON folio_lines(folio_id);

CREATE TABLE approvals (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  kind VARCHAR(40) NOT NULL,
  entity VARCHAR(40) NOT NULL,
  entity_id {REF},
  payload TEXT NOT NULL,
  amount {MONEY},
  reason VARCHAR(300),
  status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  requested_by {REF} NOT NULL REFERENCES users(id),
  decided_by {REF} REFERENCES users(id),
  decision_note VARCHAR(300),
  created_at {TS} NOT NULL,
  decided_at {TS}
);

CREATE TABLE housekeeping_tasks (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  room_id {REF} NOT NULL REFERENCES rooms(id),
  task_type VARCHAR(20) NOT NULL CHECK (task_type IN ('checkout_clean','stayover','deep_clean','inspection','turndown')),
  status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','in_progress','completed','inspected','rejected')),
  priority INTEGER NOT NULL DEFAULT 2,
  assigned_to {REF} REFERENCES users(id),
  notes TEXT,
  issues TEXT,
  business_date {DATE} NOT NULL,
  created_at {TS} NOT NULL,
  started_at {TS},
  completed_at {TS},
  inspected_by {REF} REFERENCES users(id),
  inspected_at {TS}
);
CREATE INDEX ix_hk_room ON housekeeping_tasks(room_id);

CREATE TABLE notifications (
  id {PK},
  hotel_id {REF} REFERENCES hotels(id),
  channel VARCHAR(20) NOT NULL CHECK (channel IN ('email','sms','whatsapp','in_app')),
  recipient VARCHAR(200) NOT NULL,
  subject VARCHAR(200),
  body TEXT NOT NULL,
  status VARCHAR(20) NOT NULL CHECK (status IN ('queued','sent','failed','not_configured')),
  error VARCHAR(300),
  related_entity VARCHAR(40),
  related_id VARCHAR(40),
  created_at {TS} NOT NULL,
  sent_at {TS}
);

CREATE TABLE system_settings (
  id {PK},
  hotel_id {REF} REFERENCES hotels(id),
  key VARCHAR(80) NOT NULL,
  value TEXT,
  UNIQUE (hotel_id, key)
);
