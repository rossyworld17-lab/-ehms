-- EHMS migration 0014 (release 1.4): encrypted fields need room for the AES-256-GCM envelope
-- ("enc:v1:" + base64(nonce | ciphertext | tag)), so the sensitive columns become unbounded text.
-- SQLite does not enforce VARCHAR lengths, so only PostgreSQL needs changing.

-- @dialect sqlite
SELECT 1;

-- @dialect postgresql
ALTER TABLE guests ALTER COLUMN id_number TYPE TEXT;
ALTER TABLE visitors ALTER COLUMN id_number TYPE TEXT;
ALTER TABLE employees ALTER COLUMN bank_account_number TYPE TEXT;
ALTER TABLE employees ALTER COLUMN tax_id TYPE TEXT;
ALTER TABLE employees ALTER COLUMN pension_pin TYPE TEXT;
ALTER TABLE employees ALTER COLUMN nhf_number TYPE TEXT;
ALTER TABLE suppliers ALTER COLUMN bank_account_number TYPE TEXT;
ALTER TABLE users ALTER COLUMN mfa_secret TYPE TEXT;
