-- EHMS migration 0005: laundry (guest & internal linen), HR (employees, rosters, attendance, leave, records)
-- and payroll (configurable statutory rules, runs, payslips, loans).

-- ------------------------------------------------------------------ laundry
CREATE TABLE laundry_prices (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  item VARCHAR(80) NOT NULL,
  service VARCHAR(20) NOT NULL CHECK (service IN ('wash_iron','dry_clean','iron_only','wash_only')),
  price {MONEY} NOT NULL CHECK (price >= 0),
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE (hotel_id, item, service)
);

CREATE TABLE laundry_orders (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  kind VARCHAR(10) NOT NULL CHECK (kind IN ('guest','internal')),
  reservation_id {REF} REFERENCES reservations(id),
  department VARCHAR(30),
  status VARCHAR(20) NOT NULL DEFAULT 'received' CHECK (status IN ('received','washing','drying','ironing','quality_check','ready','delivered','cancelled')),
  express INTEGER NOT NULL DEFAULT 0,
  total {MONEY} NOT NULL DEFAULT 0,
  notes VARCHAR(300),
  due_at {TS},
  folio_line_id {REF} REFERENCES folio_lines(id),
  received_by {REF} NOT NULL REFERENCES users(id),
  delivered_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL,
  delivered_at {TS},
  business_date {DATE} NOT NULL
);
CREATE INDEX ix_laundry_status ON laundry_orders(hotel_id, status);

CREATE TABLE laundry_order_items (
  id {PK},
  order_id {REF} NOT NULL REFERENCES laundry_orders(id),
  price_id {REF} REFERENCES laundry_prices(id),
  description VARCHAR(120) NOT NULL,
  service VARCHAR(20) NOT NULL,
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price {MONEY} NOT NULL DEFAULT 0,
  condition_note VARCHAR(200),
  outcome VARCHAR(10) NOT NULL DEFAULT 'ok' CHECK (outcome IN ('ok','damaged','lost')),
  outcome_note VARCHAR(200)
);

-- ------------------------------------------------------------------ HR
CREATE TABLE employees (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  employee_no VARCHAR(30) NOT NULL UNIQUE,
  user_id {REF} REFERENCES users(id),
  first_name VARCHAR(100) NOT NULL,
  last_name VARCHAR(100) NOT NULL,
  gender VARCHAR(10),
  date_of_birth {DATE},
  phone VARCHAR(50),
  email VARCHAR(200),
  address TEXT,
  department VARCHAR(30) NOT NULL,
  position VARCHAR(100) NOT NULL,
  employment_type VARCHAR(20) NOT NULL DEFAULT 'full_time' CHECK (employment_type IN ('full_time','part_time','contract','casual','intern')),
  hire_date {DATE} NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','terminated','resigned','retired')),
  exit_date {DATE},
  exit_reason VARCHAR(300),
  basic_salary {MONEY} NOT NULL DEFAULT 0,
  housing_allowance {MONEY} NOT NULL DEFAULT 0,
  transport_allowance {MONEY} NOT NULL DEFAULT 0,
  other_allowance {MONEY} NOT NULL DEFAULT 0,
  annual_rent {MONEY} NOT NULL DEFAULT 0,
  bank_name VARCHAR(100),
  bank_account_number VARCHAR(30),
  tax_id VARCHAR(50),
  pension_pfa VARCHAR(100),
  pension_pin VARCHAR(50),
  nhf_number VARCHAR(50),
  next_of_kin VARCHAR(200),
  emergency_contact VARCHAR(200),
  qualifications TEXT,
  created_at {TS} NOT NULL
);
CREATE UNIQUE INDEX ux_employee_user ON employees(user_id);

CREATE TABLE shift_templates (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  name VARCHAR(60) NOT NULL,
  start_time VARCHAR(5) NOT NULL,
  end_time VARCHAR(5) NOT NULL,
  UNIQUE (hotel_id, name)
);

CREATE TABLE shift_assignments (
  id {PK},
  employee_id {REF} NOT NULL REFERENCES employees(id),
  work_date {DATE} NOT NULL,
  shift_id {REF} NOT NULL REFERENCES shift_templates(id),
  UNIQUE (employee_id, work_date)
);

CREATE TABLE attendance (
  id {PK},
  employee_id {REF} NOT NULL REFERENCES employees(id),
  work_date {DATE} NOT NULL,
  status VARCHAR(10) NOT NULL CHECK (status IN ('present','late','absent','leave','off')),
  clock_in VARCHAR(5),
  clock_out VARCHAR(5),
  overtime_minutes INTEGER NOT NULL DEFAULT 0,
  note VARCHAR(200),
  recorded_by {REF} REFERENCES users(id),
  recorded_at {TS} NOT NULL,
  UNIQUE (employee_id, work_date)
);

CREATE TABLE leave_types (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  code VARCHAR(20) NOT NULL,
  name VARCHAR(60) NOT NULL,
  days_per_year INTEGER NOT NULL,
  paid INTEGER NOT NULL DEFAULT 1,
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE (hotel_id, code)
);

CREATE TABLE leave_requests (
  id {PK},
  employee_id {REF} NOT NULL REFERENCES employees(id),
  leave_type_id {REF} NOT NULL REFERENCES leave_types(id),
  start_date {DATE} NOT NULL,
  end_date {DATE} NOT NULL,
  days INTEGER NOT NULL CHECK (days > 0),
  reason VARCHAR(300),
  status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','cancelled')),
  requested_by {REF} NOT NULL REFERENCES users(id),
  decided_by {REF} REFERENCES users(id),
  decision_note VARCHAR(300),
  created_at {TS} NOT NULL,
  decided_at {TS}
);

CREATE TABLE hr_records (
  id {PK},
  employee_id {REF} NOT NULL REFERENCES employees(id),
  kind VARCHAR(20) NOT NULL CHECK (kind IN ('training','appraisal','disciplinary','commendation','transfer','promotion','onboarding','exit','document')),
  record_date {DATE} NOT NULL,
  title VARCHAR(200) NOT NULL,
  details TEXT,
  rating INTEGER,
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);

-- ------------------------------------------------------------------ payroll
CREATE TABLE employee_loans (
  id {PK},
  employee_id {REF} NOT NULL REFERENCES employees(id),
  description VARCHAR(200) NOT NULL,
  principal {MONEY} NOT NULL CHECK (principal > 0),
  monthly_deduction {MONEY} NOT NULL CHECK (monthly_deduction > 0),
  balance {MONEY} NOT NULL,
  status VARCHAR(10) NOT NULL DEFAULT 'active' CHECK (status IN ('active','repaid')),
  journal_entry_id {REF} REFERENCES journal_entries(id),
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);

CREATE TABLE payroll_runs (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  period CHAR(7) NOT NULL,
  status VARCHAR(10) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','approved','paid')),
  employees INTEGER NOT NULL DEFAULT 0,
  gross {MONEY} NOT NULL DEFAULT 0,
  net {MONEY} NOT NULL DEFAULT 0,
  paye {MONEY} NOT NULL DEFAULT 0,
  employer_cost {MONEY} NOT NULL DEFAULT 0,
  rules TEXT NOT NULL,
  created_by {REF} NOT NULL REFERENCES users(id),
  approved_by {REF} REFERENCES users(id),
  paid_by {REF} REFERENCES users(id),
  journal_entry_id {REF} REFERENCES journal_entries(id),
  payment_journal_id {REF} REFERENCES journal_entries(id),
  created_at {TS} NOT NULL,
  approved_at {TS},
  paid_at {TS},
  UNIQUE (hotel_id, period)
);

CREATE TABLE payslips (
  id {PK},
  run_id {REF} NOT NULL REFERENCES payroll_runs(id),
  employee_id {REF} NOT NULL REFERENCES employees(id),
  days_in_period INTEGER NOT NULL,
  days_absent INTEGER NOT NULL DEFAULT 0,
  basic {MONEY} NOT NULL,
  housing {MONEY} NOT NULL,
  transport {MONEY} NOT NULL,
  other_allowance {MONEY} NOT NULL,
  overtime {MONEY} NOT NULL DEFAULT 0,
  bonus {MONEY} NOT NULL DEFAULT 0,
  absence_deduction {MONEY} NOT NULL DEFAULT 0,
  gross {MONEY} NOT NULL,
  pension_employee {MONEY} NOT NULL DEFAULT 0,
  nhf {MONEY} NOT NULL DEFAULT 0,
  paye {MONEY} NOT NULL DEFAULT 0,
  loan_deduction {MONEY} NOT NULL DEFAULT 0,
  other_deduction {MONEY} NOT NULL DEFAULT 0,
  net {MONEY} NOT NULL,
  pension_employer {MONEY} NOT NULL DEFAULT 0,
  employer_other {MONEY} NOT NULL DEFAULT 0,
  details TEXT,
  UNIQUE (run_id, employee_id)
);

CREATE TABLE payroll_adjustments (
  id {PK},
  run_id {REF} NOT NULL REFERENCES payroll_runs(id),
  employee_id {REF} NOT NULL REFERENCES employees(id),
  kind VARCHAR(10) NOT NULL CHECK (kind IN ('bonus','deduction')),
  amount {MONEY} NOT NULL CHECK (amount > 0),
  note VARCHAR(200) NOT NULL,
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);
