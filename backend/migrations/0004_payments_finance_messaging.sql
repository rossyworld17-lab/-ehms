-- EHMS migration 0004: online payment gateways, promo codes, finance operations (bank reconciliation,
-- period close, budgets, expense claims), notification templates and scheduled jobs.

CREATE TABLE gateway_transactions (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  provider VARCHAR(20) NOT NULL CHECK (provider IN ('paystack','flutterwave')),
  reference VARCHAR(80) NOT NULL UNIQUE,
  purpose VARCHAR(20) NOT NULL CHECK (purpose IN ('folio','booking')),
  folio_id {REF} REFERENCES folios(id),
  reservation_id {REF} REFERENCES reservations(id),
  amount {MONEY} NOT NULL CHECK (amount > 0),
  currency CHAR(3) NOT NULL,
  email VARCHAR(200),
  status VARCHAR(20) NOT NULL DEFAULT 'initialized' CHECK (status IN ('initialized','success','failed','amount_mismatch')),
  authorization_url VARCHAR(500),
  gateway_status VARCHAR(40),
  payment_id {REF} REFERENCES payments(id),
  created_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL,
  verified_at {TS}
);

CREATE TABLE integration_logs (
  id {PK},
  hotel_id {REF} REFERENCES hotels(id),
  integration VARCHAR(30) NOT NULL,
  direction VARCHAR(10) NOT NULL CHECK (direction IN ('outbound','inbound')),
  endpoint VARCHAR(300) NOT NULL,
  status_code INTEGER,
  attempt INTEGER NOT NULL DEFAULT 1,
  ok INTEGER NOT NULL DEFAULT 0,
  summary VARCHAR(500),
  error VARCHAR(500),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_intlog ON integration_logs(integration, created_at);

CREATE TABLE promo_codes (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  code VARCHAR(40) NOT NULL,
  description VARCHAR(200),
  discount_type VARCHAR(10) NOT NULL CHECK (discount_type IN ('percent','amount')),
  value INTEGER NOT NULL CHECK (value > 0),
  valid_from {DATE} NOT NULL,
  valid_to {DATE} NOT NULL,
  min_nights INTEGER NOT NULL DEFAULT 1,
  max_uses INTEGER,
  uses INTEGER NOT NULL DEFAULT 0,
  room_type_id {REF} REFERENCES room_types(id),
  active INTEGER NOT NULL DEFAULT 1,
  created_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL,
  UNIQUE (hotel_id, code)
);
ALTER TABLE reservations ADD COLUMN promo_code VARCHAR(40);

CREATE TABLE accounting_periods (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  period CHAR(7) NOT NULL,
  status VARCHAR(10) NOT NULL CHECK (status IN ('closed','open')),
  closed_by {REF} REFERENCES users(id),
  closed_at {TS},
  note VARCHAR(300),
  UNIQUE (hotel_id, period)
);

CREATE TABLE bank_statement_lines (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  account_id {REF} NOT NULL REFERENCES accounts(id),
  txn_date {DATE} NOT NULL,
  description VARCHAR(300),
  reference VARCHAR(100),
  amount {MONEY} NOT NULL,
  status VARCHAR(10) NOT NULL DEFAULT 'unmatched' CHECK (status IN ('unmatched','matched','ignored')),
  journal_line_id {REF} REFERENCES journal_lines(id),
  imported_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE UNIQUE INDEX ux_bsl_jl ON bank_statement_lines(journal_line_id);
CREATE INDEX ix_bsl_acct ON bank_statement_lines(hotel_id, account_id, status);

CREATE TABLE budget_lines (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  account_id {REF} NOT NULL REFERENCES accounts(id),
  period CHAR(7) NOT NULL,
  amount {MONEY} NOT NULL,
  UNIQUE (hotel_id, account_id, period)
);

CREATE TABLE expense_claims (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  department VARCHAR(30) NOT NULL,
  account_id {REF} NOT NULL REFERENCES accounts(id),
  description VARCHAR(300) NOT NULL,
  payee VARCHAR(150),
  amount {MONEY} NOT NULL CHECK (amount > 0),
  receipt_ref VARCHAR(100),
  status VARCHAR(20) NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted','approved','rejected','paid')),
  requested_by {REF} NOT NULL REFERENCES users(id),
  approved_by {REF} REFERENCES users(id),
  decision_note VARCHAR(300),
  paid_by {REF} REFERENCES users(id),
  method_id {REF} REFERENCES payment_methods(id),
  payment_reference VARCHAR(100),
  journal_entry_id {REF} REFERENCES journal_entries(id),
  expense_date {DATE} NOT NULL,
  created_at {TS} NOT NULL,
  decided_at {TS},
  paid_at {TS}
);

CREATE TABLE notification_templates (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  code VARCHAR(40) NOT NULL,
  channel VARCHAR(20) NOT NULL CHECK (channel IN ('email','sms','whatsapp','in_app')),
  subject VARCHAR(200),
  body TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  updated_by {REF} REFERENCES users(id),
  updated_at {TS},
  UNIQUE (hotel_id, code, channel)
);
ALTER TABLE notifications ADD COLUMN read_at {TS};
ALTER TABLE notifications ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
CREATE INDEX ix_notif_recipient ON notifications(channel, recipient, read_at);

CREATE TABLE job_runs (
  id {PK},
  job VARCHAR(40) NOT NULL,
  run_key VARCHAR(120) NOT NULL,
  created_at {TS} NOT NULL,
  UNIQUE (job, run_key)
);
