-- EHMS migration 0011: full HR suite — line managers, probation and contract dates, job history, training and
-- certifications, appraisals, staff requests (advances, loans, letters, detail changes, shift swaps, grievances),
-- public holidays and leave adjustments.

ALTER TABLE employees ADD COLUMN line_manager_id {REF} REFERENCES employees(id);
ALTER TABLE employees ADD COLUMN probation_end_date {DATE};
ALTER TABLE employees ADD COLUMN contract_end_date {DATE};
ALTER TABLE leave_requests ADD COLUMN cancelled_at {TS};
ALTER TABLE leave_requests ADD COLUMN cancel_reason VARCHAR(300);

CREATE TABLE employee_history (
  id {PK},
  employee_id {REF} NOT NULL REFERENCES employees(id),
  kind VARCHAR(20) NOT NULL CHECK (kind IN ('promotion','transfer','salary_change','confirmation','title_change','demotion')),
  effective_date {DATE} NOT NULL,
  from_value VARCHAR(200),
  to_value VARCHAR(200),
  note VARCHAR(300),
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_emp_history ON employee_history(employee_id, effective_date);

CREATE TABLE trainings (
  id {PK},
  employee_id {REF} NOT NULL REFERENCES employees(id),
  kind VARCHAR(15) NOT NULL DEFAULT 'training' CHECK (kind IN ('training','certification','licence','induction')),
  title VARCHAR(200) NOT NULL,
  provider VARCHAR(150),
  completed_on {DATE},
  expires_on {DATE},
  notes VARCHAR(300),
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_trainings_emp ON trainings(employee_id);
CREATE INDEX ix_trainings_expiry ON trainings(expires_on);

CREATE TABLE appraisals (
  id {PK},
  employee_id {REF} NOT NULL REFERENCES employees(id),
  period VARCHAR(30) NOT NULL,
  reviewer_id {REF} NOT NULL REFERENCES users(id),
  status VARCHAR(15) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','shared','acknowledged')),
  criteria TEXT NOT NULL,
  overall_rating INTEGER CHECK (overall_rating BETWEEN 1 AND 5),
  strengths TEXT,
  improvements TEXT,
  goals TEXT,
  employee_comment TEXT,
  created_at {TS} NOT NULL,
  shared_at {TS},
  acknowledged_at {TS}
);
CREATE INDEX ix_appraisals_emp ON appraisals(employee_id);

CREATE TABLE staff_requests (
  id {PK},
  employee_id {REF} NOT NULL REFERENCES employees(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  kind VARCHAR(20) NOT NULL CHECK (kind IN ('salary_advance','loan','letter','data_change','shift_swap','grievance','other')),
  subject VARCHAR(200) NOT NULL,
  details TEXT,
  amount {MONEY},
  months INTEGER,
  data TEXT,
  confidential INTEGER NOT NULL DEFAULT 0,
  status VARCHAR(12) NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted','approved','rejected','cancelled','completed')),
  decided_by {REF} REFERENCES users(id),
  decision_note VARCHAR(300),
  decided_at {TS},
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_staff_requests ON staff_requests(employee_id, status);

CREATE TABLE public_holidays (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  holiday_date {DATE} NOT NULL,
  name VARCHAR(100) NOT NULL,
  UNIQUE (hotel_id, holiday_date)
);

CREATE TABLE leave_adjustments (
  id {PK},
  employee_id {REF} NOT NULL REFERENCES employees(id),
  leave_type_id {REF} NOT NULL REFERENCES leave_types(id),
  year INTEGER NOT NULL,
  days INTEGER NOT NULL CHECK (days <> 0),
  reason VARCHAR(300) NOT NULL,
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_leave_adj ON leave_adjustments(employee_id, year);
