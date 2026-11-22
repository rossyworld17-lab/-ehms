-- EHMS migration 0010: indexes for the busiest queries (found with EXPLAIN on the dashboard, front desk, folio,
-- ledger, report, worker and BI queries during the release 1.0 performance review).
CREATE INDEX ix_res_hotel_status ON reservations(hotel_id, status, arrival);
CREATE INDEX ix_res_hotel_created ON reservations(hotel_id, created_at);
CREATE INDEX ix_folios_hotel_status ON folios(hotel_id, status);
CREATE INDEX ix_folios_linked ON folios(linked_reservation_id);
CREATE INDEX ix_fl_date_dept ON folio_lines(business_date, department);
CREATE INDEX ix_fl_reference ON folio_lines(folio_id, reference);
CREATE INDEX ix_payments_folio ON payments(folio_id);
CREATE INDEX ix_payments_hotel_created ON payments(hotel_id, created_at);
CREATE INDEX ix_je_hotel_date ON journal_entries(hotel_id, entry_date);
CREATE INDEX ix_je_source ON journal_entries(source, source_ref);
CREATE INDEX ix_pos_orders_hotel_date ON pos_orders(hotel_id, business_date, status);
CREATE INDEX ix_audit_hotel_created ON audit_logs(hotel_id, created_at);
CREATE INDEX ix_approvals_hotel_status ON approvals(hotel_id, status);
CREATE INDEX ix_notif_status ON notifications(status, channel);
CREATE INDEX ix_hk_hotel_status ON housekeeping_tasks(hotel_id, status);
CREATE INDEX ix_notes_hotel_status ON customer_notes(hotel_id, status);
CREATE INDEX ix_applicants_opening ON applicants(opening_id, stage);
CREATE INDEX ix_attendance_date ON attendance(work_date);
CREATE INDEX ix_leave_dates ON leave_requests(employee_id, start_date, end_date);
CREATE INDEX ix_login_attempts_time ON login_attempts(created_at);
