-- EHMS migration 0008: document store with access history, scheduled reports, anomaly review queue and
-- AI assistant interaction log.

-- ------------------------------------------------------------------ documents
CREATE TABLE documents (
  id {PK},
  organisation_id {REF} NOT NULL REFERENCES organisations(id),
  hotel_id {REF} REFERENCES hotels(id),
  entity_type VARCHAR(30) NOT NULL,
  entity_id {REF},
  category VARCHAR(40) NOT NULL,
  title VARCHAR(200) NOT NULL,
  filename VARCHAR(200) NOT NULL,
  content_type VARCHAR(100) NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 VARCHAR(64) NOT NULL,
  storage_key VARCHAR(100) NOT NULL UNIQUE,
  confidentiality VARCHAR(20) NOT NULL DEFAULT 'internal' CHECK (confidentiality IN ('internal','confidential','restricted')),
  version INTEGER NOT NULL DEFAULT 1,
  replaces_id {REF} REFERENCES documents(id),
  retention_until {DATE},
  legal_hold INTEGER NOT NULL DEFAULT 0,
  status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded','deleted')),
  notes TEXT,
  uploaded_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL,
  deleted_at {TS},
  deleted_by {REF} REFERENCES users(id),
  delete_reason TEXT
);
CREATE INDEX ix_documents_entity ON documents(organisation_id, entity_type, entity_id);

CREATE TABLE document_access_log (
  id {PK},
  document_id {REF} NOT NULL REFERENCES documents(id),
  user_id {REF} REFERENCES users(id),
  action VARCHAR(20) NOT NULL,
  detail TEXT,
  ip VARCHAR(64),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_doc_access ON document_access_log(document_id);

-- ------------------------------------------------------------------ scheduled reports
CREATE TABLE report_schedules (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  name VARCHAR(150) NOT NULL,
  report_code VARCHAR(50) NOT NULL,
  params TEXT,
  frequency VARCHAR(10) NOT NULL CHECK (frequency IN ('daily','weekly','monthly')),
  weekday INTEGER,
  month_day INTEGER,
  format VARCHAR(5) NOT NULL DEFAULT 'pdf' CHECK (format IN ('pdf','xlsx','csv')),
  recipients TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  last_run_on {DATE},
  last_status VARCHAR(30),
  last_error TEXT,
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);

-- ------------------------------------------------------------------ anomaly review queue
CREATE TABLE anomaly_flags (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  rule VARCHAR(50) NOT NULL,
  severity VARCHAR(10) NOT NULL DEFAULT 'medium' CHECK (severity IN ('low','medium','high')),
  entity_type VARCHAR(30),
  entity_id {REF},
  business_date {DATE},
  amount {MONEY},
  user_id {REF} REFERENCES users(id),
  title VARCHAR(250) NOT NULL,
  explanation TEXT NOT NULL,
  fingerprint VARCHAR(120) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open','reviewing','confirmed','dismissed')),
  reviewed_by {REF} REFERENCES users(id),
  reviewed_at {TS},
  review_note TEXT,
  created_at {TS} NOT NULL,
  UNIQUE (hotel_id, fingerprint)
);

-- ------------------------------------------------------------------ AI assistant audit
CREATE TABLE ai_interactions (
  id {PK},
  hotel_id {REF} REFERENCES hotels(id),
  user_id {REF} NOT NULL REFERENCES users(id),
  question TEXT NOT NULL,
  intents TEXT,
  engine VARCHAR(20) NOT NULL,
  denied TEXT,
  answer TEXT,
  created_at {TS} NOT NULL
);
