"""Permission catalogue and default role templates.

Permissions follow the pattern <module>.<action>. Roles are seeded per organisation
and remain fully editable (custom roles are supported through the admin API).
"""
from __future__ import annotations

PERMISSIONS: dict[str, tuple[str, str]] = {
    # code: (module, description)
    "dashboard.view": ("dashboard", "View dashboards and KPIs"),
    "admin.users.view": ("admin", "View user accounts"),
    "admin.users.manage": ("admin", "Create, edit, suspend and deactivate users"),
    "admin.roles.manage": ("admin", "Create and edit roles and permissions"),
    "admin.sessions.manage": ("admin", "View and revoke user sessions"),
    "admin.settings.manage": ("admin", "Configure hotel settings, taxes and payment methods"),
    "admin.audit.view": ("admin", "View audit trail and login history"),
    "property.manage": ("property", "Register and edit hotels and branches"),
    "rooms.view": ("rooms", "View rooms and room status board"),
    "rooms.manage": ("rooms", "Create and edit room types and rooms"),
    "rooms.status.update": ("rooms", "Change room housekeeping status"),
    "rooms.block": ("rooms", "Block rooms / set out of order or out of service"),
    "guests.view": ("guests", "View guest profiles"),
    "guests.manage": ("guests", "Create and edit guest profiles"),
    "guests.identity.view": ("guests", "View guest identification details (sensitive)"),
    "reservations.view": ("reservations", "View reservations and availability"),
    "reservations.create": ("reservations", "Create reservations"),
    "reservations.modify": ("reservations", "Modify reservations and assign rooms"),
    "reservations.cancel": ("reservations", "Cancel reservations and mark no-shows"),
    "reservations.override_rate": ("reservations", "Override room rates and apply discounts"),
    "reservations.overbook": ("reservations", "Authorise overlapping room allocation"),
    "frontdesk.checkin": ("frontdesk", "Check guests in"),
    "frontdesk.checkout": ("frontdesk", "Check guests out"),
    "frontdesk.room_move": ("frontdesk", "Move in-house guests between rooms"),
    "frontdesk.night_audit": ("frontdesk", "Run night audit (post room charges, roll business date)"),
    "folio.view": ("folio", "View guest folios and invoices"),
    "folio.post_charge": ("folio", "Post charges to guest folios"),
    "folio.adjust": ("folio", "Post folio adjustments / reversals"),
    "payments.receive": ("payments", "Record payments and deposits"),
    "payments.refund_request": ("payments", "Request refunds"),
    "payments.refund_approve": ("payments", "Approve or reject refund requests"),
    "accounting.view": ("accounting", "View ledger, journals and financial statements"),
    "accounting.post_manual": ("accounting", "Post manual journal entries"),
    "accounting.manage_accounts": ("accounting", "Maintain chart of accounts"),
    "housekeeping.view": ("housekeeping", "View housekeeping tasks"),
    "housekeeping.assign": ("housekeeping", "Create and assign housekeeping tasks"),
    "housekeeping.update": ("housekeeping", "Start and complete assigned cleaning tasks"),
    "housekeeping.inspect": ("housekeeping", "Inspect and approve cleaned rooms"),
    "reports.view": ("reports", "View operational reports"),
    "reports.financial": ("reports", "View financial reports and exports"),
    "approvals.view": ("approvals", "View approval requests"),
    # --- release 0.4: restaurant & bar POS, kitchen display
    "pos.view": ("pos", "View POS outlets, open orders and menus"),
    "pos.order": ("pos", "Open orders, add items and send them to the kitchen"),
    "pos.settle": ("pos", "Take payment and settle orders"),
    "pos.post_to_room": ("pos", "Charge orders to an in-house guest's room folio"),
    "pos.discount": ("pos", "Apply discounts to orders"),
    "pos.void": ("pos", "Void order items or whole orders"),
    "pos.shift": ("pos", "Open and close a cashier shift"),
    "pos.manage": ("pos", "Configure outlets, tables, menus and recipes"),
    "kitchen.view": ("kitchen", "View the kitchen display"),
    "kitchen.update": ("kitchen", "Update preparation status of kitchen orders"),
    # --- release 0.4: inventory & stores
    "inventory.view": ("inventory", "View stock balances, movements and items"),
    "inventory.manage": ("inventory", "Maintain the item catalogue and stores"),
    "inventory.requisition": ("inventory", "Request stock from a store"),
    "inventory.approve": ("inventory", "Approve or reject stock requisitions"),
    "inventory.issue": ("inventory", "Issue and transfer stock"),
    "inventory.adjust": ("inventory", "Post stock adjustments, wastage and stock counts"),
    # --- release 0.4: procurement
    "procurement.view": ("procurement", "View suppliers, requisitions, purchase orders and invoices"),
    "procurement.suppliers": ("procurement", "Create and edit supplier records"),
    "procurement.requisition": ("procurement", "Raise purchase requisitions"),
    "procurement.order": ("procurement", "Record quotations and raise purchase orders"),
    "procurement.approve": ("procurement", "Approve requisitions and purchase orders up to the high-value threshold"),
    "procurement.approve_high": ("procurement", "Approve purchase orders above the high-value threshold"),
    "procurement.receive": ("procurement", "Receive goods against purchase orders (GRN)"),
    "procurement.invoice": ("procurement", "Record supplier invoices"),
    "procurement.invoice_approve": ("procurement", "Approve supplier invoices for payment"),
    "procurement.pay": ("procurement", "Record supplier payments"),
    # --- release 0.5: finance operations, promotions, messaging
    "finance.expenses.request": ("finance", "Submit expense claims"),
    "finance.expenses.approve": ("finance", "Approve or reject expense claims"),
    "finance.expenses.pay": ("finance", "Pay approved expense claims"),
    "accounting.reconcile": ("accounting", "Import bank statements and reconcile accounts"),
    "accounting.budgets": ("accounting", "Set budgets"),
    "accounting.close_period": ("accounting", "Close and reopen accounting periods"),
    "promotions.manage": ("sales", "Create and manage promotional codes"),
    "admin.notifications.manage": ("admin", "Manage notification templates and the message delivery log"),
    # --- release 0.6: laundry, HR, payroll
    "laundry.view": ("laundry", "View laundry orders and price list"),
    "laundry.manage": ("laundry", "Take, process and deliver laundry orders; maintain prices"),
    "hr.view": ("hr", "View employees, rosters, attendance and leave"),
    "hr.manage": ("hr", "Register and edit employees, salary structures and leave types"),
    "hr.records": ("hr", "View and add confidential HR records (appraisals, disciplinary…)"),
    "hr.attendance": ("hr", "Maintain rosters and record attendance"),
    "hr.leave.approve": ("hr", "Approve or reject leave requests"),
    "payroll.view": ("payroll", "View payroll runs and payslips"),
    "payroll.run": ("payroll", "Prepare payroll runs and adjustments"),
    "payroll.approve": ("payroll", "Approve payroll runs and statutory rules"),
    "payroll.pay": ("payroll", "Pay salaries, remit statutory deductions, grant staff loans"),
    # --- release 0.7: maintenance, security, events
    "maintenance.view": ("maintenance", "View assets and work orders"),
    "maintenance.report": ("maintenance", "Report faults (raise work orders)"),
    "maintenance.work": ("maintenance", "Work on assigned work orders and issue spare parts"),
    "maintenance.manage": ("maintenance", "Manage assets, schedules, assignment and verification"),
    "security.view": ("security", "View incidents, visitor log and access events"),
    "security.report": ("security", "Record security incidents"),
    "security.manage": ("security", "Investigate incidents, sign visitors in/out, emergency contacts"),
    "security.sensitive": ("security", "View restricted incidents (assault, harassment, sensitive cases)"),
    "lostfound.manage": ("security", "Log, return and dispose of lost property"),
    "events.view": ("events", "View venues, events and quotations"),
    "events.manage": ("events", "Create and manage events, venues, quotations and costs"),
    "events.invoice": ("events", "Invoice events to the event folio"),
}

ALL = list(PERMISSIONS)

_FRONT = ["dashboard.view", "rooms.view", "guests.view", "guests.manage", "reservations.view", "reservations.create",
          "reservations.modify", "reservations.cancel", "frontdesk.checkin", "frontdesk.checkout", "frontdesk.room_move",
          "folio.view", "folio.post_charge", "payments.receive", "payments.refund_request", "housekeeping.view", "reports.view"]
_FIN = ["dashboard.view", "folio.view", "accounting.view", "accounting.post_manual", "reports.view", "reports.financial",
        "approvals.view", "guests.view", "reservations.view"]
_POS_ALL = [p for p in PERMISSIONS if p.startswith("pos.")]
_INV_ALL = [p for p in PERMISSIONS if p.startswith("inventory.")]
_VIEW_ALL = [p for p in ALL if p.endswith(".view") or p in ("reports.financial",)]

# code: (name, description, permissions)
DEFAULT_ROLES: dict[str, tuple[str, str, list[str]]] = {
    "super_admin": ("Super Administrator", "Platform-wide administration", ALL),
    "org_owner": ("Organisation Owner", "Organisation-level oversight", ALL),
    "general_manager": ("Managing Director / General Manager", "Overall hotel operations", [p for p in ALL if p not in ("admin.roles.manage",)]),
    "hotel_manager": ("Hotel Manager", "Property operations", [p for p in ALL if not p.startswith("admin.roles") and p != "property.manage"]),
    "front_office_manager": ("Front Office Manager", "Front office supervision",
                             _FRONT + ["laundry.view", "laundry.manage", "hr.view", "hr.attendance", "hr.leave.approve", "maintenance.view", "maintenance.report",
                                       "lostfound.manage", "security.report", "security.view", "events.view", "reservations.override_rate", "reservations.overbook", "folio.adjust", "payments.refund_approve", "frontdesk.night_audit",
                                       "guests.identity.view", "rooms.block", "rooms.status.update", "approvals.view"]),
    "receptionist": ("Receptionist", "Reception, check-in and check-out", _FRONT + ["guests.identity.view", "laundry.view", "laundry.manage",
                                                                                 "maintenance.report", "lostfound.manage", "security.report"]),
    "reservations_officer": ("Reservations Officer", "Booking administration",
                             ["dashboard.view", "rooms.view", "guests.view", "guests.manage", "reservations.view", "reservations.create",
                              "reservations.modify", "reservations.cancel", "folio.view", "payments.receive", "reports.view"]),
    "accountant": ("Accountant", "Accounting and payments", _FIN + ["payments.receive", "payroll.view", "payroll.pay", "finance.expenses.request", "finance.expenses.pay", "accounting.reconcile", "procurement.view", "procurement.invoice",
                                                                    "procurement.pay", "inventory.view", "pos.view"]),
    "finance_manager": ("Finance Manager", "Financial control", _FIN + ["accounting.manage_accounts", "payments.refund_approve",
                                                                         "folio.adjust", "admin.settings.manage", "admin.audit.view",
                                                                         "procurement.view", "procurement.approve", "procurement.approve_high",
                                                                         "procurement.invoice_approve", "inventory.view", "pos.view", "payroll.view", "payroll.approve", "events.view", "events.invoice",
                                                                         "finance.expenses.request", "finance.expenses.approve", "accounting.reconcile",
                                                                         "accounting.budgets", "accounting.close_period", "promotions.manage"]),
    "auditor": ("Auditor", "Read-only audit access", _VIEW_ALL + ["admin.audit.view"]),
    "hr_manager": ("Human Resources Manager", "Employee administration", ["dashboard.view", "admin.users.view", "hr.view", "hr.manage", "hr.records",
                                                                    "hr.attendance", "hr.leave.approve", "payroll.view", "payroll.run", "reports.view",
                                                                    "finance.expenses.request"]),
    "hr_officer": ("HR Officer", "HR administration", ["dashboard.view", "hr.view", "hr.manage", "hr.attendance"]),
    "housekeeping_manager": ("Housekeeping Manager", "Cleaning and room readiness",
                             ["dashboard.view", "rooms.view", "rooms.status.update", "housekeeping.view", "housekeeping.assign",
                              "housekeeping.update", "housekeeping.inspect", "reports.view",
                              "inventory.view", "inventory.requisition", "finance.expenses.request",
                              "laundry.view", "laundry.manage", "hr.view", "hr.attendance", "hr.leave.approve",
                              "maintenance.view", "maintenance.report", "lostfound.manage", "security.report"]),
    "housekeeping_staff": ("Housekeeping Staff", "Room cleaning", ["rooms.view", "housekeeping.view", "housekeeping.update", "laundry.view", "laundry.manage",
                                                                     "maintenance.report", "lostfound.manage"]),
    "restaurant_manager": ("Restaurant Manager", "Outlets and POS", ["dashboard.view", "guests.view", "folio.view", "folio.post_charge"] + _POS_ALL
                           + ["kitchen.view", "inventory.view", "inventory.requisition", "reports.view", "finance.expenses.request",
                              "hr.view", "hr.attendance", "hr.leave.approve", "maintenance.report", "events.view"]),
    "restaurant_cashier": ("Restaurant Cashier", "POS cashier", ["guests.view", "folio.post_charge", "pos.view", "pos.order", "pos.settle",
                                                                 "pos.post_to_room", "pos.shift"]),
    "waiter": ("Waiter / Waitress", "Food and beverage service", ["pos.view", "pos.order", "kitchen.view"]),
    "chef": ("Chef / Kitchen Staff", "Kitchen operations", ["kitchen.view", "kitchen.update", "inventory.view", "inventory.requisition", "maintenance.report"]),
    "inventory_manager": ("Inventory Manager", "Inventory control", ["dashboard.view", "reports.view", "procurement.view", "procurement.requisition",
                                                                     "procurement.receive"] + _INV_ALL),
    "storekeeper": ("Storekeeper", "Stores", ["inventory.view", "inventory.requisition", "inventory.issue", "procurement.view", "procurement.receive"]),
    "procurement_officer": ("Procurement Officer", "Purchasing", ["dashboard.view", "inventory.view", "procurement.view", "procurement.suppliers",
                                                                  "procurement.requisition", "procurement.order", "procurement.receive", "reports.view"]),
    "maintenance_manager": ("Maintenance Manager", "Assets and repairs", ["dashboard.view", "rooms.view", "rooms.block", "maintenance.view", "maintenance.report",
                                                                      "maintenance.work", "maintenance.manage", "reports.view",
                                                                      "inventory.view", "inventory.requisition", "procurement.requisition", "finance.expenses.request",
                                                                      "hr.view", "hr.attendance", "hr.leave.approve"]),
    "maintenance_technician": ("Maintenance Technician", "Repairs", ["rooms.view", "maintenance.view", "maintenance.report", "maintenance.work", "inventory.view"]),
    "security_officer": ("Security Officer", "Security and incidents", ["dashboard.view", "rooms.view", "security.view", "security.report", "security.manage",
                                                                  "security.sensitive", "lostfound.manage", "maintenance.view", "maintenance.report"]),
    "marketing_manager": ("Marketing Manager", "Marketing", ["dashboard.view", "guests.view", "reports.view", "promotions.manage", "finance.expenses.request"]),
    "sales_manager": ("Sales Manager", "Sales and corporate accounts", ["dashboard.view", "guests.view", "reservations.view", "reservations.create", "reports.view",
                                                                        "promotions.manage", "events.view", "events.manage"]),
    "customer_service_officer": ("Customer Service Officer", "Guest service", ["dashboard.view", "guests.view", "reservations.view", "lostfound.manage", "security.report"]),
    "it_admin": ("IT Administrator", "Technical administration", ["dashboard.view", "admin.users.view", "admin.users.manage",
                                                                   "admin.sessions.manage", "admin.audit.view", "admin.settings.manage",
                                                                   "admin.notifications.manage"]),
    "guest": ("Guest / Customer", "Guest self-service", []),
}


def seed_permissions_and_roles(c, organisation_id: int) -> dict[str, int]:
    """Insert permission catalogue (idempotent) and default roles for an organisation."""
    existing = {r["code"] for r in c.all("SELECT code FROM permissions")}
    for code, (module, desc) in PERMISSIONS.items():
        if code not in existing:
            c.execute("INSERT INTO permissions (code, module, description) VALUES (?, ?, ?)", [code, module, desc])
    role_ids: dict[str, int] = {}
    for code, (name, desc, perms) in DEFAULT_ROLES.items():
        row = c.one("SELECT id FROM roles WHERE organisation_id = ? AND code = ?", [organisation_id, code])
        if row:
            role_ids[code] = row["id"]
            continue
        rid = c.insert("roles", {"organisation_id": organisation_id, "code": code, "name": name, "description": desc, "is_system": 1})
        for p in dict.fromkeys(perms):
            c.execute("INSERT INTO role_permissions (role_id, permission_code) VALUES (?, ?)", [rid, p])
        role_ids[code] = rid
    return role_ids


# Permissions added after the first release. On upgrade they are granted once to the system roles whose
# default template includes them; afterwards administrators stay in full control of every role.
INTRODUCED: dict[str, list[str]] = {
    "0.4": [p for p in PERMISSIONS if p.split(".")[0] in ("pos", "kitchen", "inventory", "procurement")],
    "0.5": ["finance.expenses.request", "finance.expenses.approve", "finance.expenses.pay", "accounting.reconcile", "accounting.budgets",
            "accounting.close_period", "promotions.manage", "admin.notifications.manage"],
    "0.6": [p for p in PERMISSIONS if p.split(".")[0] in ("laundry", "hr", "payroll")],
    "0.7": [p for p in PERMISSIONS if p.split(".")[0] in ("maintenance", "security", "lostfound", "events")],
}


def apply_permission_upgrades(c, organisation_id: int) -> list[str]:
    """Grant permissions introduced in later releases to existing system roles (runs once per release)."""
    seed_permissions_and_roles(c, organisation_id)
    applied = []
    for version, perms in INTRODUCED.items():
        key = f"rbac.upgrade.{version}.org{organisation_id}"
        if c.one("SELECT id FROM system_settings WHERE hotel_id IS NULL AND key = ?", [key]):
            continue
        for code, (_, _, defaults) in DEFAULT_ROLES.items():
            role = c.one("SELECT id FROM roles WHERE organisation_id = ? AND code = ? AND is_system = 1", [organisation_id, code])
            if not role:
                continue
            have = {r["permission_code"] for r in c.all("SELECT permission_code FROM role_permissions WHERE role_id = ?", [role["id"]])}
            for p in perms:
                if p in defaults and p not in have:
                    c.execute("INSERT INTO role_permissions (role_id, permission_code) VALUES (?, ?)", [role["id"], p])
        c.execute("INSERT INTO system_settings (hotel_id, key, value) VALUES (NULL, ?, ?)", [key, "applied"])
        applied.append(version)
    return applied
