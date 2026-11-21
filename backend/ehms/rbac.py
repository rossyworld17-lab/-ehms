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
}

ALL = list(PERMISSIONS)

_FRONT = ["dashboard.view", "rooms.view", "guests.view", "guests.manage", "reservations.view", "reservations.create",
          "reservations.modify", "reservations.cancel", "frontdesk.checkin", "frontdesk.checkout", "frontdesk.room_move",
          "folio.view", "folio.post_charge", "payments.receive", "payments.refund_request", "housekeeping.view", "reports.view"]
_FIN = ["dashboard.view", "folio.view", "accounting.view", "accounting.post_manual", "reports.view", "reports.financial",
        "approvals.view", "guests.view", "reservations.view"]
_VIEW_ALL = [p for p in ALL if p.endswith(".view") or p in ("reports.financial",)]

# code: (name, description, permissions)
DEFAULT_ROLES: dict[str, tuple[str, str, list[str]]] = {
    "super_admin": ("Super Administrator", "Platform-wide administration", ALL),
    "org_owner": ("Organisation Owner", "Organisation-level oversight", ALL),
    "general_manager": ("Managing Director / General Manager", "Overall hotel operations", [p for p in ALL if p not in ("admin.roles.manage",)]),
    "hotel_manager": ("Hotel Manager", "Property operations", [p for p in ALL if not p.startswith("admin.roles") and p != "property.manage"]),
    "front_office_manager": ("Front Office Manager", "Front office supervision",
                             _FRONT + ["reservations.override_rate", "reservations.overbook", "folio.adjust", "payments.refund_approve", "frontdesk.night_audit",
                                       "guests.identity.view", "rooms.block", "rooms.status.update", "approvals.view"]),
    "receptionist": ("Receptionist", "Reception, check-in and check-out", _FRONT + ["guests.identity.view"]),
    "reservations_officer": ("Reservations Officer", "Booking administration",
                             ["dashboard.view", "rooms.view", "guests.view", "guests.manage", "reservations.view", "reservations.create",
                              "reservations.modify", "reservations.cancel", "folio.view", "payments.receive", "reports.view"]),
    "accountant": ("Accountant", "Accounting and payments", _FIN + ["payments.receive"]),
    "finance_manager": ("Finance Manager", "Financial control", _FIN + ["accounting.manage_accounts", "payments.refund_approve",
                                                                         "folio.adjust", "admin.settings.manage", "admin.audit.view"]),
    "auditor": ("Auditor", "Read-only audit access", _VIEW_ALL + ["admin.audit.view"]),
    "hr_manager": ("Human Resources Manager", "Employee administration", ["dashboard.view", "admin.users.view"]),
    "hr_officer": ("HR Officer", "HR administration", ["dashboard.view"]),
    "housekeeping_manager": ("Housekeeping Manager", "Cleaning and room readiness",
                             ["dashboard.view", "rooms.view", "rooms.status.update", "housekeeping.view", "housekeeping.assign",
                              "housekeeping.update", "housekeeping.inspect", "reports.view"]),
    "housekeeping_staff": ("Housekeeping Staff", "Room cleaning", ["rooms.view", "housekeeping.view", "housekeeping.update"]),
    "restaurant_manager": ("Restaurant Manager", "Outlets and POS", ["dashboard.view", "guests.view", "folio.view", "folio.post_charge"]),
    "restaurant_cashier": ("Restaurant Cashier", "POS cashier", ["guests.view", "folio.post_charge"]),
    "waiter": ("Waiter / Waitress", "Food and beverage service", ["dashboard.view"]),
    "chef": ("Chef / Kitchen Staff", "Kitchen operations", ["dashboard.view"]),
    "inventory_manager": ("Inventory Manager", "Inventory control", ["dashboard.view"]),
    "storekeeper": ("Storekeeper", "Stores", ["dashboard.view"]),
    "procurement_officer": ("Procurement Officer", "Purchasing", ["dashboard.view"]),
    "maintenance_manager": ("Maintenance Manager", "Assets and repairs", ["dashboard.view", "rooms.view", "rooms.block"]),
    "maintenance_technician": ("Maintenance Technician", "Repairs", ["rooms.view"]),
    "security_officer": ("Security Officer", "Security and incidents", ["dashboard.view", "rooms.view"]),
    "marketing_manager": ("Marketing Manager", "Marketing", ["dashboard.view", "guests.view", "reports.view"]),
    "sales_manager": ("Sales Manager", "Sales and corporate accounts", ["dashboard.view", "guests.view", "reservations.view", "reservations.create", "reports.view"]),
    "customer_service_officer": ("Customer Service Officer", "Guest service", ["dashboard.view", "guests.view", "reservations.view"]),
    "it_admin": ("IT Administrator", "Technical administration", ["dashboard.view", "admin.users.view", "admin.users.manage",
                                                                   "admin.sessions.manage", "admin.audit.view", "admin.settings.manage"]),
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
