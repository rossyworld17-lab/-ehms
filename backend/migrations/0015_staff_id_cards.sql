-- EHMS migration 0015 (release 1.4): staff ID cards.
-- A card is generated automatically when an employee is registered (directly or by hiring an applicant) and waits in
-- the print queue; HR prints it (A4 sheet or card printer), hands it over, and reissues it when details change or a
-- card is lost. Each card carries a random verification token printed as a QR code.
ALTER TABLE employees ADD COLUMN photo_filename VARCHAR(100);
ALTER TABLE employees ADD COLUMN photo_content_type VARCHAR(40);
ALTER TABLE employees ADD COLUMN blood_group VARCHAR(5);

CREATE TABLE staff_id_cards (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  employee_id {REF} NOT NULL REFERENCES employees(id),
  card_no VARCHAR(40) NOT NULL UNIQUE,
  version INTEGER NOT NULL DEFAULT 1,
  reason VARCHAR(20) NOT NULL DEFAULT 'new_hire' CHECK (reason IN ('new_hire','details_changed','lost','damaged','renewal','other')),
  status VARCHAR(12) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','printed','issued','revoked')),
  verify_token VARCHAR(48) NOT NULL UNIQUE,
  issue_date {DATE},
  expiry_date {DATE} NOT NULL,
  print_count INTEGER NOT NULL DEFAULT 0,
  printed_at {TS},
  printed_by {REF} REFERENCES users(id),
  issued_at {TS},
  issued_by {REF} REFERENCES users(id),
  revoked_at {TS},
  revoked_by {REF} REFERENCES users(id),
  revoke_reason VARCHAR(200),
  created_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_id_cards_hotel_status ON staff_id_cards(hotel_id, status);
CREATE INDEX ix_id_cards_employee ON staff_id_cards(employee_id);
