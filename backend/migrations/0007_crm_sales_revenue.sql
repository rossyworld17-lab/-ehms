-- EHMS migration 0007: CRM (loyalty, complaints, feedback & surveys, campaigns), sales (corporate & travel-agent
-- accounts, negotiated rates, targets) and revenue management (seasons, dynamic rules, competitor rates).

-- ------------------------------------------------------------------ sales accounts & rates
CREATE TABLE corporate_accounts (
  id {PK},
  organisation_id {REF} NOT NULL REFERENCES organisations(id),
  code VARCHAR(30) NOT NULL,
  kind VARCHAR(20) NOT NULL DEFAULT 'corporate' CHECK (kind IN ('corporate','travel_agent','government','ngo')),
  name VARCHAR(200) NOT NULL,
  contact_name VARCHAR(150),
  email VARCHAR(200),
  phone VARCHAR(50),
  address TEXT,
  tax_id VARCHAR(50),
  credit_limit {MONEY} NOT NULL DEFAULT 0,
  payment_terms_days INTEGER NOT NULL DEFAULT 30,
  commission_bp INTEGER NOT NULL DEFAULT 0,
  status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('lead','prospect','active','suspended')),
  account_manager {REF} REFERENCES users(id),
  notes TEXT,
  created_at {TS} NOT NULL,
  UNIQUE (organisation_id, code)
);

CREATE TABLE corporate_rates (
  id {PK},
  account_id {REF} NOT NULL REFERENCES corporate_accounts(id),
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  room_type_id {REF} NOT NULL REFERENCES room_types(id),
  rate {MONEY} NOT NULL CHECK (rate >= 0),
  valid_from {DATE} NOT NULL,
  valid_to {DATE} NOT NULL
);
CREATE INDEX ix_corp_rates ON corporate_rates(account_id, room_type_id);

ALTER TABLE reservations ADD COLUMN corporate_account_id {REF} REFERENCES corporate_accounts(id);
ALTER TABLE reservations ADD COLUMN locked_rates TEXT;

CREATE TABLE sales_targets (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  period CHAR(7) NOT NULL,
  metric VARCHAR(20) NOT NULL CHECK (metric IN ('room_revenue','rooms_sold','fnb_revenue','event_revenue','total_revenue')),
  target {MONEY} NOT NULL,
  owner_id {REF} REFERENCES users(id),
  UNIQUE (hotel_id, period, metric)
);

-- ------------------------------------------------------------------ revenue management
CREATE TABLE rate_seasons (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  name VARCHAR(100) NOT NULL,
  start_date {DATE} NOT NULL,
  end_date {DATE} NOT NULL,
  room_type_id {REF} REFERENCES room_types(id),
  adjustment_bp INTEGER NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_by {REF} REFERENCES users(id)
);

CREATE TABLE rate_rules (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  name VARCHAR(100) NOT NULL,
  room_type_id {REF} REFERENCES room_types(id),
  min_occupancy_pct INTEGER NOT NULL CHECK (min_occupancy_pct BETWEEN 0 AND 100),
  max_occupancy_pct INTEGER NOT NULL DEFAULT 100 CHECK (max_occupancy_pct BETWEEN 0 AND 100),
  adjustment_bp INTEGER NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'pending_approval' CHECK (status IN ('pending_approval','active','inactive','rejected')),
  created_by {REF} NOT NULL REFERENCES users(id),
  approved_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL,
  approved_at {TS}
);

CREATE TABLE competitor_rates (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  competitor VARCHAR(150) NOT NULL,
  stay_date {DATE} NOT NULL,
  room_category VARCHAR(100) NOT NULL,
  rate {MONEY} NOT NULL CHECK (rate >= 0),
  source VARCHAR(60),
  recorded_by {REF} NOT NULL REFERENCES users(id),
  recorded_at {TS} NOT NULL
);
CREATE INDEX ix_comp_rates ON competitor_rates(hotel_id, stay_date);

-- ------------------------------------------------------------------ CRM: loyalty
CREATE TABLE loyalty_accounts (
  id {PK},
  guest_id {REF} NOT NULL UNIQUE REFERENCES guests(id),
  member_no VARCHAR(30) NOT NULL UNIQUE,
  points_balance INTEGER NOT NULL DEFAULT 0,
  lifetime_points INTEGER NOT NULL DEFAULT 0,
  tier VARCHAR(20) NOT NULL DEFAULT 'bronze',
  active INTEGER NOT NULL DEFAULT 1,
  enrolled_at {TS} NOT NULL,
  enrolled_by {REF} REFERENCES users(id)
);

CREATE TABLE loyalty_transactions (
  id {PK},
  account_id {REF} NOT NULL REFERENCES loyalty_accounts(id),
  hotel_id {REF} REFERENCES hotels(id),
  kind VARCHAR(10) NOT NULL CHECK (kind IN ('earn','redeem','adjust','bonus')),
  points INTEGER NOT NULL,
  balance_after INTEGER NOT NULL,
  reference VARCHAR(60),
  description VARCHAR(200),
  folio_line_id {REF} REFERENCES folio_lines(id),
  created_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_loyalty_tx ON loyalty_transactions(account_id);

-- ------------------------------------------------------------------ CRM: complaints & feedback
CREATE TABLE complaints (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  guest_id {REF} REFERENCES guests(id),
  reservation_id {REF} REFERENCES reservations(id),
  room_id {REF} REFERENCES rooms(id),
  channel VARCHAR(20) NOT NULL DEFAULT 'in_person' CHECK (channel IN ('in_person','phone','email','online_review','survey','social_media','other')),
  category VARCHAR(20) NOT NULL,
  department VARCHAR(30) NOT NULL,
  priority VARCHAR(10) NOT NULL DEFAULT 'normal' CHECK (priority IN ('urgent','high','normal','low')),
  description TEXT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','resolved','closed')),
  assigned_to {REF} REFERENCES users(id),
  escalation_level INTEGER NOT NULL DEFAULT 0,
  due_at {TS} NOT NULL,
  first_response_at {TS},
  resolved_at {TS},
  resolution TEXT,
  compensation {MONEY} NOT NULL DEFAULT 0,
  guest_satisfied INTEGER,
  reported_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_complaints ON complaints(hotel_id, status);

CREATE TABLE complaint_updates (
  id {PK},
  complaint_id {REF} NOT NULL REFERENCES complaints(id),
  note TEXT NOT NULL,
  created_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL
);

CREATE TABLE feedback (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  guest_id {REF} REFERENCES guests(id),
  reservation_id {REF} REFERENCES reservations(id),
  token VARCHAR(64) UNIQUE,
  source VARCHAR(20) NOT NULL DEFAULT 'survey' CHECK (source IN ('survey','manual','online_review')),
  platform VARCHAR(60),
  overall INTEGER CHECK (overall BETWEEN 1 AND 5),
  cleanliness INTEGER CHECK (cleanliness BETWEEN 1 AND 5),
  service INTEGER CHECK (service BETWEEN 1 AND 5),
  food INTEGER CHECK (food BETWEEN 1 AND 5),
  value_for_money INTEGER CHECK (value_for_money BETWEEN 1 AND 5),
  nps INTEGER CHECK (nps BETWEEN 0 AND 10),
  comments TEXT,
  sentiment VARCHAR(10),
  themes VARCHAR(200),
  sent_at {TS},
  submitted_at {TS},
  created_at {TS} NOT NULL
);
CREATE INDEX ix_feedback ON feedback(hotel_id, submitted_at);

-- ------------------------------------------------------------------ CRM: campaigns
CREATE TABLE campaigns (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  name VARCHAR(150) NOT NULL,
  channel VARCHAR(10) NOT NULL CHECK (channel IN ('email','sms','whatsapp')),
  segment TEXT NOT NULL,
  subject VARCHAR(200),
  body TEXT NOT NULL,
  promo_code VARCHAR(40),
  status VARCHAR(20) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','cancelled')),
  recipients INTEGER NOT NULL DEFAULT 0,
  created_by {REF} NOT NULL REFERENCES users(id),
  sent_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL,
  sent_at {TS}
);

CREATE TABLE campaign_recipients (
  id {PK},
  campaign_id {REF} NOT NULL REFERENCES campaigns(id),
  guest_id {REF} NOT NULL REFERENCES guests(id),
  notification_id {REF} REFERENCES notifications(id),
  UNIQUE (campaign_id, guest_id)
);
