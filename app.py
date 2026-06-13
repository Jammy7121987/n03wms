import os
import sqlite3
import bcrypt
import functools
from datetime import datetime
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, g, jsonify)

import os

os.makedirs("instance", exist_ok=True)


app = Flask(__name__)
app.secret_key = "n03wms-secret-change-in-production-2024"
DATABASE = "instance/n03wms.db"


# ─────────────────────────── DB HELPERS ──────────────────────────────────────

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db:
        db.close()


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rv = cur.fetchall()
    return (rv[0] if rv else None) if one else rv


def execute(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


# ─────────────────────────── AUDIT HELPER ─────────────────────────────────────

def audit(action, entity, entity_id=None):
    user_id = session.get("user_id")
    execute(
        "INSERT INTO audit_logs (user_id, action, entity, entity_id, timestamp) VALUES (?,?,?,?,?)",
        (user_id, action, entity, entity_id, datetime.utcnow())
    )


# ─────────────────────────── AUTH DECORATORS ─────────────────────────────────

def login_required(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            if session.get("role") not in roles:
                flash("Access denied.", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return wrapped
    return decorator


# ─────────────────────────── DB INIT ─────────────────────────────────────────

def init_db():
    db = sqlite3.connect(DATABASE)
    db.executescript("""
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        phone TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin','treasurer','member')),
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
        status TEXT DEFAULT 'active' CHECK(status IN ('active','inactive')),
        joined_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS contributions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL REFERENCES members(id),
        amount REAL NOT NULL,
        payment_method TEXT DEFAULT 'cash' CHECK(payment_method IN ('cash','mpesa','manual')),
        reference_code TEXT,
        period TEXT NOT NULL,
        recorded_by INTEGER NOT NULL REFERENCES users(id),
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amount REAL NOT NULL,
        purpose TEXT NOT NULL,
        status TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
        requested_by INTEGER NOT NULL REFERENCES users(id),
        approved_by INTEGER REFERENCES users(id),
        approved_at TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL CHECK(type IN ('IN','OUT')),
        reference_id INTEGER NOT NULL,
        description TEXT NOT NULL,
        amount REAL NOT NULL,
        balance_after REAL NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER REFERENCES users(id),
        action TEXT NOT NULL,
        entity TEXT NOT NULL,
        entity_id INTEGER,
        timestamp TEXT DEFAULT (datetime('now'))
    );
    """)

    # Seed admin if not exists
# Seed admin safely (idempotent)
pw_hash = bcrypt.hashpw(b"admin1234", bcrypt.gensalt()).decode()

db.execute("""
INSERT OR IGNORE INTO users (id, full_name, phone, password_hash, role)
VALUES (1, 'Chairperson Admin', '0700000001', ?, 'admin')
""", (pw_hash,))

db.execute("""
INSERT OR IGNORE INTO members (user_id)
VALUES (1)
""")

db.commit()


# ─────────────────────────── LEDGER ENGINE ───────────────────────────────────

def get_balance():
    row = query("SELECT MAX(id), balance_after FROM ledger ORDER BY id DESC LIMIT 1", one=True)
    if row and row[1] is not None:
        return row[1]
    return 0.0


def post_ledger_entry(tx_type, ref_id, description, amount):
    balance = get_balance()
    new_balance = balance + amount if tx_type == "IN" else balance - amount
    execute(
        "INSERT INTO ledger (type, reference_id, description, amount, balance_after) VALUES (?,?,?,?,?)",
        (tx_type, ref_id, description, amount, new_balance)
    )
    return new_balance


# ─────────────────────────── AUTH ROUTES ─────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        phone = request.form["phone"].strip()
        password = request.form["password"].encode()
        user = query("SELECT * FROM users WHERE phone=? AND is_active=1", (phone,), one=True)
        if not user:
            flash("Invalid phone number or password.", "danger")
            return render_template("login.html")
        session.update({"user_id": user["id"], "full_name": user["full_name"], "role": user["role"]})
        audit("LOGIN", "users", user["id"])
        flash(f"Welcome back, {user['full_name']}!", "success")
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    audit("LOGOUT", "users", session.get("user_id"))
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ─────────────────────────── DASHBOARD ───────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    role = session["role"]
    balance = get_balance()
    total_contributions = query("SELECT COALESCE(SUM(amount),0) as t FROM contributions", one=True)["t"]
    total_expenses = query("SELECT COALESCE(SUM(amount),0) as t FROM expenses WHERE status='approved'", one=True)["t"]
    total_members = query("SELECT COUNT(*) as c FROM members WHERE status='active'", one=True)["c"]
    pending_expenses = query("SELECT COUNT(*) as c FROM expenses WHERE status='pending'", one=True)["c"]
    recent_ledger = query("SELECT * FROM ledger ORDER BY id DESC LIMIT 8")

    ctx = dict(balance=balance, total_contributions=total_contributions,
               total_expenses=total_expenses, total_members=total_members,
               pending_expenses=pending_expenses, recent_ledger=recent_ledger)

    if role == "member":
        member = query("SELECT m.id FROM members m WHERE m.user_id=?", (session["user_id"],), one=True)
        if member:
            my_contributions = query(
                "SELECT c.*, u.full_name as recorder FROM contributions c "
                "JOIN users u ON c.recorded_by=u.id WHERE c.member_id=? ORDER BY c.created_at DESC",
                (member["id"],))
            ctx["my_contributions"] = my_contributions
        return render_template("member_dashboard.html", **ctx)

    elif role == "treasurer":
        members = query("SELECT m.id, u.full_name, u.phone, m.status FROM members m JOIN users u ON m.user_id=u.id WHERE m.status='active' ORDER BY u.full_name")
        ctx["members"] = members
        return render_template("treasurer_dashboard.html", **ctx)

    else:  # admin
        recent_audit = query(
            "SELECT a.*, u.full_name FROM audit_logs a LEFT JOIN users u ON a.user_id=u.id "
            "ORDER BY a.id DESC LIMIT 10")
        ctx["recent_audit"] = recent_audit
        all_expenses_pending = query(
            "SELECT e.*, u.full_name as requester FROM expenses e "
            "JOIN users u ON e.requested_by=u.id WHERE e.status='pending' ORDER BY e.created_at")
        ctx["pending_list"] = all_expenses_pending
        return render_template("admin_dashboard.html", **ctx)


# ─────────────────────────── MEMBERS ─────────────────────────────────────────

@app.route("/members")
@login_required
@roles_required("admin", "treasurer")
def members_list():
    members = query(
        "SELECT m.id, u.id as user_id, u.full_name, u.phone, u.role, m.status, m.joined_at "
        "FROM members m JOIN users u ON m.user_id=u.id ORDER BY u.full_name")
    return render_template("members.html", members=members)


@app.route("/members/add", methods=["GET", "POST"])
@login_required
@roles_required("admin")
def add_member():
    if request.method == "POST":
        full_name = request.form["full_name"].strip()
        phone = request.form["phone"].strip()
        role = request.form.get("role", "member")
        password = request.form["password"]
        if not all([full_name, phone, password]):
            flash("All fields are required.", "danger")
            return render_template("member_form.html", action="Add")
        existing = query("SELECT id FROM users WHERE phone=?", (phone,), one=True)
        if existing:
            flash("A user with that phone number already exists.", "danger")
            return render_template("member_form.html", action="Add")
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        user_id = execute(
            "INSERT INTO users (full_name, phone, password_hash, role) VALUES (?,?,?,?)",
            (full_name, phone, pw_hash, role))
        member_id = execute("INSERT INTO members (user_id) VALUES (?)", (user_id,))
        audit("CREATE", "members", member_id)
        flash(f"Member '{full_name}' added successfully.", "success")
        return redirect(url_for("members_list"))
    return render_template("member_form.html", action="Add")


@app.route("/members/<int:member_id>/edit", methods=["GET", "POST"])
@login_required
@roles_required("admin")
def edit_member(member_id):
    member = query(
        "SELECT m.id, u.id as user_id, u.full_name, u.phone, u.role, m.status "
        "FROM members m JOIN users u ON m.user_id=u.id WHERE m.id=?", (member_id,), one=True)
    if not member:
        flash("Member not found.", "danger")
        return redirect(url_for("members_list"))
    if request.method == "POST":
        full_name = request.form["full_name"].strip()
        phone = request.form["phone"].strip()
        role = request.form.get("role", member["role"])
        status = request.form.get("status", member["status"])
        execute("UPDATE users SET full_name=?, phone=?, role=? WHERE id=?",
                (full_name, phone, role, member["user_id"]))
        execute("UPDATE members SET status=? WHERE id=?", (status, member_id))
        audit("UPDATE", "members", member_id)
        flash("Member updated.", "success")
        return redirect(url_for("members_list"))
    return render_template("member_form.html", action="Edit", member=member)


# ─────────────────────────── CONTRIBUTIONS ───────────────────────────────────

@app.route("/contributions")
@login_required
@roles_required("admin", "treasurer")
def contributions_list():
    contribs = query(
        "SELECT c.*, u.full_name as member_name, r.full_name as recorder_name "
        "FROM contributions c "
        "JOIN members m ON c.member_id=m.id "
        "JOIN users u ON m.user_id=u.id "
        "JOIN users r ON c.recorded_by=r.id "
        "ORDER BY c.created_at DESC")
    members = query("SELECT m.id, u.full_name FROM members m JOIN users u ON m.user_id=u.id WHERE m.status='active' ORDER BY u.full_name")
    return render_template("contributions.html", contributions=contribs, members=members)


@app.route("/contributions/add", methods=["POST"])
@login_required
@roles_required("admin", "treasurer")
def add_contribution():
    member_id = request.form["member_id"]
    amount = float(request.form.get("amount", 200))
    method = request.form.get("payment_method", "cash")
    ref = request.form.get("reference_code", "").strip() or None
    period = request.form.get("period", "").strip()

    if not period:
        flash("Period (e.g. January 2025) is required.", "danger")
        return redirect(url_for("contributions_list"))

    # Duplicate check: same member + same period
    dup = query("SELECT id FROM contributions WHERE member_id=? AND period=?", (member_id, period), one=True)
    if dup:
        flash(f"Contribution for this member in period '{period}' already recorded.", "warning")
        return redirect(url_for("contributions_list"))

    contrib_id = execute(
        "INSERT INTO contributions (member_id, amount, payment_method, reference_code, period, recorded_by) VALUES (?,?,?,?,?,?)",
        (member_id, amount, method, ref, period, session["user_id"]))

    member = query("SELECT u.full_name FROM members m JOIN users u ON m.user_id=u.id WHERE m.id=?", (member_id,), one=True)
    desc = f"Contribution – {member['full_name']} ({period})"
    post_ledger_entry("IN", contrib_id, desc, amount)
    audit("CREATE", "contributions", contrib_id)
    flash(f"Contribution of KES {amount:,.0f} recorded successfully.", "success")
    return redirect(url_for("contributions_list"))


# ─────────────────────────── EXPENSES ────────────────────────────────────────

@app.route("/expenses")
@login_required
def expenses_list():
    expenses = query(
        "SELECT e.*, u.full_name as requester, a.full_name as approver "
        "FROM expenses e "
        "JOIN users u ON e.requested_by=u.id "
        "LEFT JOIN users a ON e.approved_by=a.id "
        "ORDER BY e.created_at DESC")
    return render_template("expenses.html", expenses=expenses, role=session["role"])


@app.route("/expenses/add", methods=["POST"])
@login_required
@roles_required("admin", "treasurer")
def add_expense():
    amount = float(request.form["amount"])
    purpose = request.form["purpose"].strip()
    if amount <= 0 or not purpose:
        flash("Amount and purpose are required.", "danger")
        return redirect(url_for("expenses_list"))
    exp_id = execute(
        "INSERT INTO expenses (amount, purpose, requested_by) VALUES (?,?,?)",
        (amount, purpose, session["user_id"]))
    audit("CREATE", "expenses", exp_id)
    flash(f"Expense request of KES {amount:,.0f} submitted for approval.", "success")
    return redirect(url_for("expenses_list"))


@app.route("/expenses/<int:exp_id>/approve", methods=["POST"])
@login_required
@roles_required("admin")
def approve_expense(exp_id):
    expense = query("SELECT * FROM expenses WHERE id=? AND status='pending'", (exp_id,), one=True)
    if not expense:
        flash("Expense not found or already processed.", "warning")
        return redirect(url_for("expenses_list"))
    balance = get_balance()
    if expense["amount"] > balance:
        flash(f"Cannot approve: expense (KES {expense['amount']:,.0f}) exceeds current balance (KES {balance:,.0f}).", "danger")
        return redirect(url_for("expenses_list"))
    execute(
        "UPDATE expenses SET status='approved', approved_by=?, approved_at=? WHERE id=?",
        (session["user_id"], datetime.utcnow(), exp_id))
    post_ledger_entry("OUT", exp_id, f"Expense – {expense['purpose']}", expense["amount"])
    audit("APPROVE", "expenses", exp_id)
    flash(f"Expense approved. New balance: KES {get_balance():,.0f}", "success")
    return redirect(url_for("expenses_list"))


@app.route("/expenses/<int:exp_id>/reject", methods=["POST"])
@login_required
@roles_required("admin")
def reject_expense(exp_id):
    execute("UPDATE expenses SET status='rejected', approved_by=?, approved_at=? WHERE id=?",
            (session["user_id"], datetime.utcnow(), exp_id))
    audit("REJECT", "expenses", exp_id)
    flash("Expense rejected.", "info")
    return redirect(url_for("expenses_list"))


# ─────────────────────────── LEDGER ──────────────────────────────────────────

@app.route("/ledger")
@login_required
@roles_required("admin", "treasurer")
def ledger_view():
    entries = query("SELECT * FROM ledger ORDER BY id DESC")
    balance = get_balance()
    return render_template("ledger.html", entries=entries, balance=balance)


# ─────────────────────────── AUDIT LOGS ──────────────────────────────────────

@app.route("/audit")
@login_required
@roles_required("admin")
def audit_logs():
    logs = query(
        "SELECT a.*, u.full_name FROM audit_logs a "
        "LEFT JOIN users u ON a.user_id=u.id ORDER BY a.id DESC LIMIT 200")
    return render_template("audit.html", logs=logs)


# ─────────────────────────── REPORTS ─────────────────────────────────────────

@app.route("/reports")
@login_required
@roles_required("admin", "treasurer")
def reports():
    # Monthly contributions summary
    monthly = query(
        "SELECT period, COUNT(*) as count, SUM(amount) as total "
        "FROM contributions GROUP BY period ORDER BY period DESC")
    # Member payment status (last 3 periods)
    periods = query("SELECT DISTINCT period FROM contributions ORDER BY period DESC LIMIT 3")
    members_status = query(
        "SELECT m.id, u.full_name, u.phone FROM members m "
        "JOIN users u ON m.user_id=u.id WHERE m.status='active' ORDER BY u.full_name")
    for m in members_status:
        paid_periods = [
            r["period"] for r in query(
                "SELECT period FROM contributions WHERE member_id=?", (m["id"],))
        ]
        m = dict(m)
    balance = get_balance()
    total_contributions = query("SELECT COALESCE(SUM(amount),0) as t FROM contributions", one=True)["t"]
    total_expenses = query("SELECT COALESCE(SUM(amount),0) as t FROM expenses WHERE status='approved'", one=True)["t"]
    return render_template("reports.html", monthly=monthly, periods=periods,
                           members_status=members_status, balance=balance,
                           total_contributions=total_contributions, total_expenses=total_expenses)


# ─────────────────────────── MAIN ────────────────────────────────────────────
if __name__ == "__main__":
    import os

    os.makedirs("instance", exist_ok=True)

    port = int(os.environ.get("PORT", 5000))

    with app.app_context():
        init_db()

    app.run(host="0.0.0.0", port=port, debug=False)
