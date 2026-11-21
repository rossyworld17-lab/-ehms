-- EHMS migration 0002: tamper protection for audit trail and posted ledger
-- Dialect-specific blocks are separated by "-- @dialect <name>" markers.

-- @dialect sqlite
CREATE TRIGGER trg_audit_no_update BEFORE UPDATE ON audit_logs
BEGIN SELECT RAISE(ABORT, 'audit_logs are append-only'); END;
CREATE TRIGGER trg_audit_no_delete BEFORE DELETE ON audit_logs
BEGIN SELECT RAISE(ABORT, 'audit_logs are append-only'); END;
CREATE TRIGGER trg_jl_no_update BEFORE UPDATE ON journal_lines
BEGIN SELECT RAISE(ABORT, 'posted journal lines cannot be changed; post a reversal'); END;
CREATE TRIGGER trg_jl_no_delete BEFORE DELETE ON journal_lines
BEGIN SELECT RAISE(ABORT, 'posted journal lines cannot be deleted; post a reversal'); END;
CREATE TRIGGER trg_je_no_delete BEFORE DELETE ON journal_entries
BEGIN SELECT RAISE(ABORT, 'journal entries cannot be deleted'); END;
CREATE TRIGGER trg_fl_no_delete BEFORE DELETE ON folio_lines
BEGIN SELECT RAISE(ABORT, 'folio lines cannot be deleted; post an adjustment'); END;

-- @dialect postgresql
CREATE OR REPLACE FUNCTION ehms_block_change() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% on % is not permitted (append-only)', TG_OP, TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER trg_audit_no_change BEFORE UPDATE OR DELETE ON audit_logs
FOR EACH ROW EXECUTE FUNCTION ehms_block_change();
CREATE TRIGGER trg_jl_no_change BEFORE UPDATE OR DELETE ON journal_lines
FOR EACH ROW EXECUTE FUNCTION ehms_block_change();
CREATE TRIGGER trg_je_no_delete BEFORE DELETE ON journal_entries
FOR EACH ROW EXECUTE FUNCTION ehms_block_change();
CREATE TRIGGER trg_fl_no_delete BEFORE DELETE ON folio_lines
FOR EACH ROW EXECUTE FUNCTION ehms_block_change();
