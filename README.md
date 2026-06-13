# Ngobit 03 Welfare Group Management System (N03-WMS)

A web-based financial transparency and governance platform for small community welfare groups.

---

## Features

- **Role-based access**: Admin (Chairperson), Treasurer, Member
- **Member management**: Add, edit, activate/deactivate members
- **Contributions ledger**: Record monthly contributions with duplicate prevention
- **Expense workflow**: Submit → Pending → Approved/Rejected
- **Immutable ledger**: Every transaction logged; no deletions allowed
- **Balance integrity**: Expenses cannot be approved if they exceed available balance
- **Audit trail**: Every system action is permanently recorded
- **Three dashboards**: Tailored views per role

---

## Requirements

- Python 3.8+
- pip

---

## Quick Setup (Windows or Linux)

### 1. Install dependencies

```bash
pip install flask bcrypt
```

### 2. Run the application

```bash
python app.py
```

The system will:
- Create `instance/n03wms.db` (SQLite database) automatically
- Seed a default admin account
- Start on http://localhost:5000

---

## Default Login

| Role  | Phone        | Password   |
|-------|-------------|------------|
| Admin | 0700000001  | admin1234  |

**Change the admin password immediately after first login** by editing the database directly or using the edit-member page.

---

## User Roles

| Action                        | Admin | Treasurer | Member |
|-------------------------------|-------|-----------|--------|
| View dashboard                | ✅    | ✅        | ✅     |
| Add/edit members              | ✅    | ❌        | ❌     |
| Record contributions          | ✅    | ✅        | ❌     |
| Submit expense request        | ✅    | ✅        | ❌     |
| Approve/reject expenses       | ✅    | ❌        | ❌     |
| View ledger                   | ✅    | ✅        | ❌     |
| View full audit logs          | ✅    | ❌        | ❌     |
| View own contributions        | ✅    | ✅        | ✅     |
| View group balance            | ✅    | ✅        | ✅     |

---

## Business Rules

1. **No deletion**: Transactions and audit logs are permanent
2. **Approval gate**: Expenses only affect balance after admin approval
3. **Balance check**: Expense approval blocked if `expense > balance`
4. **Duplicate guard**: Same member cannot be recorded twice for same period
5. **Audit everything**: Login, create, update, approve, reject — all logged

---

## Project Structure

```
n03wms/
├── app.py              # Main Flask app (routes, DB, ledger engine)
├── instance/
│   └── n03wms.db      # SQLite database (auto-created)
└── templates/
    ├── base.html
    ├── login.html
    ├── admin_dashboard.html
    ├── treasurer_dashboard.html
    ├── member_dashboard.html
    ├── members.html
    ├── member_form.html
    ├── contributions.html
    ├── expenses.html
    ├── ledger.html
    ├── audit.html
    └── reports.html
```

---

## Deployment to VPS (Later)

1. Install `gunicorn`: `pip install gunicorn`
2. Run: `gunicorn -w 4 -b 0.0.0.0:5000 app:app`
3. Point Nginx to port 5000
4. Change `app.secret_key` to a long random string in production
5. For PostgreSQL: replace `sqlite3` calls with SQLAlchemy (optional upgrade)

---

## Security Notes

- Passwords hashed with bcrypt (never stored in plain text)
- Session-based authentication
- Role checks on every protected route
- Audit log cannot be modified by any role including admin

---

*Built for Ngobit 03 Welfare Group, Kenya — Transparency First.*
