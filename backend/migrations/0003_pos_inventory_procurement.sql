-- EHMS migration 0003: inventory & stores, restaurant/bar POS with kitchen display, procurement.
-- Quantities are stored as integer thousandths of the item's base unit ("_milli" columns) so that
-- 0.25 kg or 1.5 litres are exact on both SQLite and PostgreSQL. Money is integer minor units (kobo).

-- ------------------------------------------------------------------ inventory & stores
CREATE TABLE stores (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  code VARCHAR(30) NOT NULL,
  name VARCHAR(100) NOT NULL,
  kind VARCHAR(20) NOT NULL DEFAULT 'main' CHECK (kind IN ('main','kitchen','bar','housekeeping','laundry','maintenance','other')),
  allow_negative INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE (hotel_id, code)
);

CREATE TABLE inventory_items (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  code VARCHAR(40) NOT NULL,
  barcode VARCHAR(60),
  name VARCHAR(150) NOT NULL,
  category VARCHAR(30) NOT NULL,
  unit VARCHAR(20) NOT NULL,
  last_cost {MONEY} NOT NULL DEFAULT 0,
  sale_price {MONEY},
  reorder_level_milli INTEGER NOT NULL DEFAULT 0,
  reorder_qty_milli INTEGER NOT NULL DEFAULT 0,
  track_expiry INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at {TS} NOT NULL,
  UNIQUE (hotel_id, code)
);
CREATE INDEX ix_inv_items_hotel ON inventory_items(hotel_id, category);

-- Running balance per item per store. value is the carrying value (weighted average cost x quantity).
CREATE TABLE stock_levels (
  id {PK},
  item_id {REF} NOT NULL REFERENCES inventory_items(id),
  store_id {REF} NOT NULL REFERENCES stores(id),
  quantity_milli INTEGER NOT NULL DEFAULT 0,
  value {MONEY} NOT NULL DEFAULT 0,
  UNIQUE (item_id, store_id)
);

CREATE TABLE stock_batches (
  id {PK},
  item_id {REF} NOT NULL REFERENCES inventory_items(id),
  store_id {REF} NOT NULL REFERENCES stores(id),
  batch_no VARCHAR(60),
  expiry_date {DATE},
  quantity_milli INTEGER NOT NULL,
  received_at {TS} NOT NULL
);
CREATE INDEX ix_batches_item ON stock_batches(item_id, store_id);

CREATE TABLE stock_movements (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  item_id {REF} NOT NULL REFERENCES inventory_items(id),
  store_id {REF} NOT NULL REFERENCES stores(id),
  movement_type VARCHAR(20) NOT NULL CHECK (movement_type IN ('receipt','issue','transfer_in','transfer_out','adjustment','consumption','wastage','count','return','opening')),
  quantity_milli INTEGER NOT NULL,
  value {MONEY} NOT NULL,
  balance_milli INTEGER NOT NULL,
  balance_value {MONEY} NOT NULL,
  source VARCHAR(30) NOT NULL,
  source_ref VARCHAR(60),
  department VARCHAR(30),
  reason VARCHAR(300),
  batch_no VARCHAR(60),
  expiry_date {DATE},
  journal_entry_id {REF} REFERENCES journal_entries(id),
  business_date {DATE} NOT NULL,
  created_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_moves_item ON stock_movements(item_id, store_id);
CREATE INDEX ix_moves_hotel_date ON stock_movements(hotel_id, business_date);

CREATE TABLE stock_requisitions (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  from_store_id {REF} NOT NULL REFERENCES stores(id),
  to_store_id {REF} REFERENCES stores(id),
  department VARCHAR(30),
  status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','issued','rejected','cancelled')),
  note VARCHAR(300),
  requested_by {REF} NOT NULL REFERENCES users(id),
  approved_by {REF} REFERENCES users(id),
  issued_by {REF} REFERENCES users(id),
  decision_note VARCHAR(300),
  created_at {TS} NOT NULL,
  approved_at {TS},
  issued_at {TS}
);

CREATE TABLE stock_requisition_lines (
  id {PK},
  requisition_id {REF} NOT NULL REFERENCES stock_requisitions(id),
  item_id {REF} NOT NULL REFERENCES inventory_items(id),
  requested_milli INTEGER NOT NULL CHECK (requested_milli > 0),
  issued_milli INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE stock_counts (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  store_id {REF} NOT NULL REFERENCES stores(id),
  status VARCHAR(20) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','posted','cancelled')),
  note VARCHAR(300),
  created_by {REF} NOT NULL REFERENCES users(id),
  posted_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL,
  posted_at {TS}
);

CREATE TABLE stock_count_lines (
  id {PK},
  count_id {REF} NOT NULL REFERENCES stock_counts(id),
  item_id {REF} NOT NULL REFERENCES inventory_items(id),
  system_milli INTEGER NOT NULL,
  counted_milli INTEGER,
  UNIQUE (count_id, item_id)
);

-- ------------------------------------------------------------------ restaurant & bar POS
CREATE TABLE outlets (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  code VARCHAR(30) NOT NULL,
  name VARCHAR(100) NOT NULL,
  kind VARCHAR(20) NOT NULL DEFAULT 'restaurant' CHECK (kind IN ('restaurant','bar','room_service','cafe','pool_bar','banquet')),
  store_id {REF} REFERENCES stores(id),
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE (hotel_id, code)
);

CREATE TABLE pos_tables (
  id {PK},
  outlet_id {REF} NOT NULL REFERENCES outlets(id),
  code VARCHAR(20) NOT NULL,
  area VARCHAR(60),
  seats INTEGER NOT NULL DEFAULT 4,
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE (outlet_id, code)
);

CREATE TABLE menu_categories (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  name VARCHAR(80) NOT NULL,
  kind VARCHAR(20) NOT NULL DEFAULT 'food' CHECK (kind IN ('food','beverage','other')),
  sort_order INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE (hotel_id, name)
);

CREATE TABLE menu_items (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  category_id {REF} NOT NULL REFERENCES menu_categories(id),
  outlet_id {REF} REFERENCES outlets(id),
  code VARCHAR(30) NOT NULL,
  name VARCHAR(120) NOT NULL,
  description VARCHAR(300),
  price {MONEY} NOT NULL CHECK (price >= 0),
  station VARCHAR(20) NOT NULL DEFAULT 'kitchen' CHECK (station IN ('kitchen','bar','pastry','grill','none')),
  issue_store_id {REF} REFERENCES stores(id),
  image_url VARCHAR(300),
  available INTEGER NOT NULL DEFAULT 1,
  active INTEGER NOT NULL DEFAULT 1,
  UNIQUE (hotel_id, code)
);

CREATE TABLE recipe_lines (
  id {PK},
  menu_item_id {REF} NOT NULL REFERENCES menu_items(id),
  item_id {REF} NOT NULL REFERENCES inventory_items(id),
  quantity_milli INTEGER NOT NULL CHECK (quantity_milli > 0),
  UNIQUE (menu_item_id, item_id)
);

CREATE TABLE cashier_shifts (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  outlet_id {REF} NOT NULL REFERENCES outlets(id),
  user_id {REF} NOT NULL REFERENCES users(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  status VARCHAR(10) NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
  opening_float {MONEY} NOT NULL DEFAULT 0,
  expected_cash {MONEY},
  counted_cash {MONEY},
  variance {MONEY},
  note VARCHAR(300),
  opened_at {TS} NOT NULL,
  closed_at {TS}
);
CREATE INDEX ix_shift_user ON cashier_shifts(user_id, status);

CREATE TABLE pos_orders (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  outlet_id {REF} NOT NULL REFERENCES outlets(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  order_type VARCHAR(20) NOT NULL CHECK (order_type IN ('dine_in','takeaway','room_service')),
  table_id {REF} REFERENCES pos_tables(id),
  reservation_id {REF} REFERENCES reservations(id),
  guest_name VARCHAR(150),
  covers INTEGER NOT NULL DEFAULT 1,
  waiter_id {REF} REFERENCES users(id),
  status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open','settled','voided','merged')),
  discount_amount {MONEY} NOT NULL DEFAULT 0,
  discount_reason VARCHAR(200),
  discount_by {REF} REFERENCES users(id),
  net_amount {MONEY},
  service_charge {MONEY},
  tax_amount {MONEY},
  total_amount {MONEY},
  merged_into {REF} REFERENCES pos_orders(id),
  split_from {REF} REFERENCES pos_orders(id),
  shift_id {REF} REFERENCES cashier_shifts(id),
  journal_entry_id {REF} REFERENCES journal_entries(id),
  cogs_entry_id {REF} REFERENCES journal_entries(id),
  void_reason VARCHAR(300),
  business_date {DATE} NOT NULL,
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL,
  settled_at {TS},
  settled_by {REF} REFERENCES users(id)
);
CREATE INDEX ix_pos_orders_outlet ON pos_orders(outlet_id, status);

CREATE TABLE pos_order_items (
  id {PK},
  order_id {REF} NOT NULL REFERENCES pos_orders(id),
  menu_item_id {REF} NOT NULL REFERENCES menu_items(id),
  name VARCHAR(120) NOT NULL,
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price {MONEY} NOT NULL,
  notes VARCHAR(200),
  station VARCHAR(20) NOT NULL,
  priority INTEGER NOT NULL DEFAULT 2,
  kitchen_status VARCHAR(20) NOT NULL DEFAULT 'new' CHECK (kitchen_status IN ('new','sent','preparing','ready','served','void')),
  sent_at {TS},
  started_at {TS},
  ready_at {TS},
  served_at {TS},
  void_reason VARCHAR(200),
  voided_by {REF} REFERENCES users(id),
  added_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL
);
CREATE INDEX ix_poi_order ON pos_order_items(order_id);
CREATE INDEX ix_poi_kitchen ON pos_order_items(kitchen_status, station);

CREATE TABLE pos_payments (
  id {PK},
  order_id {REF} NOT NULL REFERENCES pos_orders(id),
  shift_id {REF} REFERENCES cashier_shifts(id),
  tender VARCHAR(20) NOT NULL CHECK (tender IN ('method','room')),
  method_id {REF} REFERENCES payment_methods(id),
  folio_id {REF} REFERENCES folios(id),
  folio_line_id {REF} REFERENCES folio_lines(id),
  amount {MONEY} NOT NULL CHECK (amount > 0),
  reference VARCHAR(100),
  received_by {REF} REFERENCES users(id),
  created_at {TS} NOT NULL
);

-- ------------------------------------------------------------------ procurement
CREATE TABLE suppliers (
  id {PK},
  organisation_id {REF} NOT NULL REFERENCES organisations(id),
  code VARCHAR(30) NOT NULL,
  name VARCHAR(200) NOT NULL,
  category VARCHAR(60),
  contact_name VARCHAR(150),
  phone VARCHAR(50),
  email VARCHAR(200),
  address TEXT,
  tax_id VARCHAR(50),
  bank_name VARCHAR(100),
  bank_account_name VARCHAR(150),
  bank_account_number VARCHAR(30),
  payment_terms_days INTEGER NOT NULL DEFAULT 30,
  wht_bp INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at {TS} NOT NULL,
  UNIQUE (organisation_id, code)
);

CREATE TABLE purchase_requisitions (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  department VARCHAR(30) NOT NULL,
  store_id {REF} REFERENCES stores(id),
  status VARCHAR(20) NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted','approved','rejected','ordered','cancelled')),
  needed_by {DATE},
  justification VARCHAR(500),
  estimated_total {MONEY} NOT NULL DEFAULT 0,
  requested_by {REF} NOT NULL REFERENCES users(id),
  approved_by {REF} REFERENCES users(id),
  decision_note VARCHAR(300),
  created_at {TS} NOT NULL,
  decided_at {TS}
);

CREATE TABLE purchase_requisition_lines (
  id {PK},
  requisition_id {REF} NOT NULL REFERENCES purchase_requisitions(id),
  item_id {REF} REFERENCES inventory_items(id),
  description VARCHAR(200) NOT NULL,
  quantity_milli INTEGER NOT NULL CHECK (quantity_milli > 0),
  est_unit_cost {MONEY} NOT NULL DEFAULT 0
);

CREATE TABLE supplier_quotes (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  requisition_id {REF} NOT NULL REFERENCES purchase_requisitions(id),
  supplier_id {REF} NOT NULL REFERENCES suppliers(id),
  reference VARCHAR(60),
  valid_until {DATE},
  delivery_days INTEGER,
  total {MONEY} NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'received' CHECK (status IN ('received','selected','rejected')),
  note VARCHAR(300),
  created_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);

CREATE TABLE supplier_quote_lines (
  id {PK},
  quote_id {REF} NOT NULL REFERENCES supplier_quotes(id),
  requisition_line_id {REF} NOT NULL REFERENCES purchase_requisition_lines(id),
  unit_cost {MONEY} NOT NULL CHECK (unit_cost >= 0)
);

CREATE TABLE purchase_orders (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  supplier_id {REF} NOT NULL REFERENCES suppliers(id),
  requisition_id {REF} REFERENCES purchase_requisitions(id),
  quote_id {REF} REFERENCES supplier_quotes(id),
  store_id {REF} NOT NULL REFERENCES stores(id),
  status VARCHAR(20) NOT NULL DEFAULT 'pending_approval' CHECK (status IN ('pending_approval','approved','partially_received','received','closed','cancelled','rejected')),
  order_date {DATE} NOT NULL,
  expected_date {DATE},
  total {MONEY} NOT NULL DEFAULT 0,
  approval_level VARCHAR(10) NOT NULL DEFAULT 'standard' CHECK (approval_level IN ('standard','high')),
  note VARCHAR(500),
  created_by {REF} NOT NULL REFERENCES users(id),
  approved_by {REF} REFERENCES users(id),
  decision_note VARCHAR(300),
  created_at {TS} NOT NULL,
  approved_at {TS}
);

CREATE TABLE purchase_order_lines (
  id {PK},
  po_id {REF} NOT NULL REFERENCES purchase_orders(id),
  item_id {REF} REFERENCES inventory_items(id),
  description VARCHAR(200) NOT NULL,
  expense_key VARCHAR(40),
  quantity_milli INTEGER NOT NULL CHECK (quantity_milli > 0),
  unit_cost {MONEY} NOT NULL CHECK (unit_cost >= 0),
  received_milli INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE goods_receipts (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  po_id {REF} NOT NULL REFERENCES purchase_orders(id),
  supplier_id {REF} NOT NULL REFERENCES suppliers(id),
  store_id {REF} NOT NULL REFERENCES stores(id),
  delivery_note VARCHAR(60),
  value {MONEY} NOT NULL,
  note VARCHAR(300),
  journal_entry_id {REF} REFERENCES journal_entries(id),
  received_by {REF} NOT NULL REFERENCES users(id),
  received_at {TS} NOT NULL,
  business_date {DATE} NOT NULL
);

CREATE TABLE goods_receipt_lines (
  id {PK},
  grn_id {REF} NOT NULL REFERENCES goods_receipts(id),
  po_line_id {REF} NOT NULL REFERENCES purchase_order_lines(id),
  item_id {REF} REFERENCES inventory_items(id),
  received_milli INTEGER NOT NULL CHECK (received_milli >= 0),
  rejected_milli INTEGER NOT NULL DEFAULT 0,
  unit_cost {MONEY} NOT NULL,
  value {MONEY} NOT NULL,
  batch_no VARCHAR(60),
  expiry_date {DATE}
);

CREATE TABLE supplier_invoices (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  supplier_id {REF} NOT NULL REFERENCES suppliers(id),
  po_id {REF} REFERENCES purchase_orders(id),
  invoice_no VARCHAR(60) NOT NULL,
  invoice_date {DATE} NOT NULL,
  due_date {DATE} NOT NULL,
  amount {MONEY} NOT NULL CHECK (amount > 0),
  received_value {MONEY} NOT NULL DEFAULT 0,
  variance {MONEY} NOT NULL DEFAULT 0,
  match_status VARCHAR(20) NOT NULL CHECK (match_status IN ('matched','variance','no_po')),
  expense_key VARCHAR(40),
  status VARCHAR(20) NOT NULL DEFAULT 'pending_approval' CHECK (status IN ('pending_approval','approved','part_paid','paid','rejected')),
  amount_paid {MONEY} NOT NULL DEFAULT 0,
  note VARCHAR(300),
  journal_entry_id {REF} REFERENCES journal_entries(id),
  created_by {REF} NOT NULL REFERENCES users(id),
  approved_by {REF} REFERENCES users(id),
  decision_note VARCHAR(300),
  created_at {TS} NOT NULL,
  approved_at {TS},
  UNIQUE (supplier_id, invoice_no)
);

CREATE TABLE supplier_payments (
  id {PK},
  hotel_id {REF} NOT NULL REFERENCES hotels(id),
  number VARCHAR(30) NOT NULL UNIQUE,
  supplier_id {REF} NOT NULL REFERENCES suppliers(id),
  invoice_id {REF} NOT NULL REFERENCES supplier_invoices(id),
  method_id {REF} NOT NULL REFERENCES payment_methods(id),
  gross_amount {MONEY} NOT NULL CHECK (gross_amount > 0),
  wht_amount {MONEY} NOT NULL DEFAULT 0,
  net_amount {MONEY} NOT NULL,
  reference VARCHAR(100),
  idempotency_key VARCHAR(100) UNIQUE,
  journal_entry_id {REF} REFERENCES journal_entries(id),
  paid_by {REF} NOT NULL REFERENCES users(id),
  created_at {TS} NOT NULL
);

-- stock movement history is append-only (corrections are new movements)
-- @dialect sqlite
CREATE TRIGGER trg_sm_no_update BEFORE UPDATE ON stock_movements
BEGIN SELECT RAISE(ABORT, 'stock movements cannot be changed; post an adjustment'); END;
CREATE TRIGGER trg_sm_no_delete BEFORE DELETE ON stock_movements
BEGIN SELECT RAISE(ABORT, 'stock movements cannot be deleted; post an adjustment'); END;

-- @dialect postgresql
CREATE TRIGGER trg_sm_no_change BEFORE UPDATE OR DELETE ON stock_movements
FOR EACH ROW EXECUTE FUNCTION ehms_block_change();
