from flask import Flask, request, redirect, url_for, session, render_template_string, flash
import sqlite3
import os
import secrets
from datetime import date, timedelta
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

# CareRoute demo prototype.
# IMPORTANT: Uses synthetic demo data only. Not for real patient information.
app = Flask(__name__)
app.secret_key = os.environ.get("CAREROUTE_SECRET_KEY", secrets.token_hex(32))
DB_PATH = os.path.join(os.path.dirname(__file__), "careroute_demo.db")

# Demo accounts are created automatically. Change these before any shared demo.
DEMO_USERS = {
    "worker": {"password": "worker123", "role": "worker"},
    "supervisor": {"password": "super123", "role": "supervisor"},
}

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('worker', 'supervisor'))
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                demo_code TEXT UNIQUE NOT NULL,
                age_band TEXT NOT NULL,
                area TEXT NOT NULL,
                observation TEXT NOT NULL,
                followup_date TEXT NOT NULL,
                followup_status TEXT NOT NULL DEFAULT 'Scheduled'
                    CHECK(followup_status IN ('Scheduled', 'Completed', 'Missed')),
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                destination TEXT NOT NULL,
                reason TEXT NOT NULL,
                priority TEXT NOT NULL CHECK(priority IN ('Routine', 'Prompt review')),
                status TEXT NOT NULL DEFAULT 'Open'
                    CHECK(status IN ('Open', 'Accepted', 'Completed', 'Cancelled')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
            )
        """)

        for username, info in DEMO_USERS.items():
            existing = db.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            if not existing:
                db.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                    (username, generate_password_hash(info["password"]), info["role"])
                )

        # Seed examples only if the database has no cases.
        count = db.execute("SELECT COUNT(*) AS n FROM cases").fetchone()["n"]
        if count == 0:
            today = date.today()
            examples = [
                ("DEMO-1001", "30-44", "North community", "Routine screening recorded; follow-up requested.", (today + timedelta(days=2)).isoformat(), "worker"),
                ("DEMO-1002", "45-59", "East community", "Follow-up contact was not completed.", (today - timedelta(days=2)).isoformat(), "worker"),
                ("DEMO-1003", "18-29", "West community", "Observation recorded; review requested by worker.", (today + timedelta(days=5)).isoformat(), "worker"),
            ]
            db.executemany("""
                INSERT INTO cases (demo_code, age_band, area, observation, followup_date, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
            """, examples)
            case_id = db.execute(
                "SELECT id FROM cases WHERE demo_code = 'DEMO-1003'"
            ).fetchone()["id"]
            db.execute("""
                INSERT INTO referrals (case_id, destination, reason, priority, status)
                VALUES (?, ?, ?, ?, ?)
            """, (case_id, "Community clinic", "Worker-requested review", "Routine", "Open"))

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if session.get("role") not in roles:
                flash("You do not have permission to perform that action.", "error")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return decorator
    return decorator

def csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    return session["_csrf_token"]

app.jinja_env.globals["csrf_token"] = csrf_token

def validate_csrf():
    sent = request.form.get("_csrf_token", "")
    saved = session.get("_csrf_token", "")
    if not sent or not saved or not secrets.compare_digest(sent, saved):
        flash("Security check failed. Please try again.", "error")
        return False
    return True

BASE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} · CareRoute</title>
<style>
:root { --navy:#16324f; --blue:#2463a6; --bg:#f3f6fa; --ink:#172435; --muted:#5c6b7a; --line:#dbe3ec; --green:#e2f5e9; --amber:#fff0cc; --red:#ffe3e3; }
* { box-sizing:border-box; }
body { margin:0; font-family:Arial,Helvetica,sans-serif; color:var(--ink); background:var(--bg); }
header { background:var(--navy); color:white; padding:16px 22px; }
.top { max-width:1100px; margin:auto; display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; }
.brand { font-size:22px; font-weight:700; }
.brand small { display:block; font-size:12px; font-weight:400; opacity:.8; margin-top:3px; }
nav { display:flex; gap:14px; flex-wrap:wrap; align-items:center; }
nav a { color:white; text-decoration:none; font-size:14px; }
main { max-width:1100px; margin:24px auto; padding:0 16px 40px; }
h1 { font-size:28px; margin:0 0 8px; }
h2 { font-size:19px; margin:0 0 14px; }
p { line-height:1.5; }
.muted { color:var(--muted); }
.banner { background:#fff8df; border:1px solid #e8d48c; padding:12px 14px; border-radius:10px; margin:16px 0; font-size:14px; }
.flash { padding:11px 14px; background:#e8f2ff; border-radius:8px; margin:12px 0; }
.flash.error { background:var(--red); }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:14px; margin:20px 0; }
.card, .panel { background:white; border:1px solid var(--line); border-radius:12px; padding:17px; box-shadow:0 2px 8px #1b36500b; }
.metric { font-size:30px; font-weight:700; margin-top:8px; }
.panel { margin:16px 0; }
.grid2 { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:16px; }
label { display:block; font-size:14px; font-weight:700; margin:12px 0 6px; }
input, select, textarea { width:100%; border:1px solid #b9c7d5; border-radius:8px; padding:10px; font:inherit; background:white; }
textarea { min-height:88px; resize:vertical; }
button, .button { display:inline-block; background:var(--blue); color:white; border:0; border-radius:8px; padding:10px 14px; font-weight:700; text-decoration:none; cursor:pointer; margin-top:12px; }
button.secondary, .button.secondary { background:#e7edf4; color:var(--ink); }
table { border-collapse:collapse; width:100%; background:white; }
th, td { border-bottom:1px solid var(--line); text-align:left; padding:11px 9px; font-size:14px; vertical-align:top; }
th { background:#f7f9fc; }
.table-wrap { overflow-x:auto; border:1px solid var(--line); border-radius:10px; }
.pill { display:inline-block; padding:4px 8px; border-radius:20px; background:#e8eef5; font-size:12px; white-space:nowrap; }
.pill.good { background:var(--green); } .pill.warn { background:var(--amber); } .pill.bad { background:var(--red); }
.actions { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
.actions form { margin:0; }
.actions button { margin:0; padding:7px 9px; font-size:12px; }
.small { font-size:12px; }
footer { text-align:center; padding:20px; color:var(--muted); font-size:12px; }
@media(max-width:600px) { h1{font-size:23px} th,td{font-size:12px;padding:8px 6px} }
</style>
</head>
<body>
<header><div class="top">
  <div class="brand">CareRoute <small>Community Health Follow-Up Coordination</small></div>
  {% if session.get('user_id') %}
  <nav>
    <a href="{{ url_for('dashboard') }}">Dashboard</a>
    <a href="{{ url_for('new_case') }}">Add demo case</a>
    <a href="{{ url_for('referrals') }}">Referrals</a>
    <span class="small">{{ session.get('username') }} · {{ session.get('role') }}</span>
    <a href="{{ url_for('logout') }}">Sign out</a>
  </nav>
  {% endif %}
</div></header>
<main>
<div class="banner"><strong>Demo safety notice:</strong> Synthetic data only. This prototype does not diagnose, triage, or recommend treatment. Referral priority is entered by an authorized worker under local procedures.</div>
{% with messages = get_flashed_messages(with_categories=true) %}
  {% for category, message in messages %}<div class="flash {{ category }}">{{ message }}</div>{% endfor %}
{% endwith %}
{{ body|safe }}
</main>
<footer>CareRoute prototype · Use fictional records only · Not for clinical decision-making</footer>
</body></html>
"""

def page(title, body, **context):
    return render_template_string(BASE, title=title, body=render_template_string(body, **context))

@app.route("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if not validate_csrf():
            return redirect(url_for("login"))
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            csrf_token()
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    body = """
    <div class="panel" style="max-width:480px;margin:35px auto">
      <h1>Sign in</h1><p class="muted">Use a demo account to explore the prototype.</p>
      <form method="post">
        <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
        <label>Username</label><input name="username" required autocomplete="username">
        <label>Password</label><input name="password" type="password" required autocomplete="current-password">
        <button type="submit">Sign in</button>
      </form>
      <hr style="border:0;border-top:1px solid #dbe3ec;margin:20px 0">
      <p><strong>Demo worker</strong><br>Username: <code>worker</code> · Password: <code>worker123</code></p>
      <p><strong>Demo supervisor</strong><br>Username: <code>supervisor</code> · Password: <code>super123</code></p>
      <p class="small muted">Demo credentials only. Do not use these passwords in a deployed system.</p>
    </div>
    """
    return page("Sign in", body)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    today = date.today().isoformat()
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) n FROM cases").fetchone()["n"]
        upcoming = db.execute("""
            SELECT COUNT(*) n FROM cases
            WHERE followup_status='Scheduled' AND followup_date >= ?
        """, (today,)).fetchone()["n"]
        missed = db.execute("""
            SELECT COUNT(*) n FROM cases
            WHERE followup_status='Missed'
               OR (followup_status='Scheduled' AND followup_date < ?)
        """, (today,)).fetchone()["n"]
        open_refs = db.execute("SELECT COUNT(*) n FROM referrals WHERE status='Open'").fetchone()["n"]
        cases = db.execute("""
            SELECT c.*, 
              CASE WHEN c.followup_status='Scheduled' AND c.followup_date < ? THEN 'Overdue' ELSE c.followup_status END AS display_status
            FROM cases c ORDER BY c.followup_date ASC, c.id DESC LIMIT 100
        """, (today,)).fetchall()
    body = """
    <h1>Health-worker dashboard</h1>
    <p class="muted">Track administrative follow-up activity. These counts do not indicate medical urgency.</p>
    <div class="cards">
      <div class="card">Total demo cases<div class="metric">{{ total }}</div></div>
      <div class="card">Upcoming follow-ups<div class="metric">{{ upcoming }}</div></div>
      <div class="card">Missed / overdue<div class="metric">{{ missed }}</div></div>
      <div class="card">Open referrals<div class="metric">{{ open_refs }}</div></div>
    </div>
    <div class="actions">
      <a class="button" href="{{ url_for('new_case') }}">+ Add demo case</a>
      <a class="button secondary" href="{{ url_for('referrals') }}">View referrals</a>
    </div>
    <div class="panel"><h2>Follow-up register</h2>
    <div class="table-wrap"><table><thead><tr><th>Demo code</th><th>Age band</th><th>Area</th><th>Follow-up date</th><th>Status</th><th>Actions</th></tr></thead><tbody>
    {% for c in cases %}
      <tr>
        <td><strong>{{ c['demo_code'] }}</strong><br><span class="small muted">{{ c['observation'] }}</span></td>
        <td>{{ c['age_band'] }}</td><td>{{ c['area'] }}</td><td>{{ c['followup_date'] }}</td>
        <td><span class="pill {% if c['display_status']=='Completed' %}good{% elif c['display_status'] in ['Missed','Overdue'] %}bad{% else %}warn{% endif %}">{{ c['display_status'] }}</span></td>
        <td>
          <div class="actions">
          {% if c['followup_status'] != 'Completed' %}
          <form method="post" action="{{ url_for('update_followup', case_id=c['id']) }}">
            <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
            <input type="hidden" name="status" value="Completed"><button type="submit">Complete</button>
          </form>
          {% endif %}
          {% if c['followup_status'] == 'Scheduled' %}
          <form method="post" action="{{ url_for('update_followup', case_id=c['id']) }}">
            <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
            <input type="hidden" name="status" value="Missed"><button class="secondary" type="submit">Mark missed</button>
          </form>
          {% endif %}
          <a class="button secondary" href="{{ url_for('new_referral', case_id=c['id']) }}">Referral</a>
          </div>
        </td>
      </tr>
    {% else %}<tr><td colspan="6">No cases yet.</td></tr>{% endfor %}
    </tbody></table></div></div>
    """
    return page("Dashboard", body, total=total, upcoming=upcoming, missed=missed,
                open_refs=open_refs, cases=cases)

@app.route("/case/new", methods=["GET", "POST"])
@role_required("worker", "supervisor")
def new_case():
    if request.method == "POST":
        if not validate_csrf():
            return redirect(url_for("new_case"))
        demo_code = request.form.get("demo_code", "").strip().upper()
        age_band = request.form.get("age_band", "").strip()
        area = request.form.get("area", "").strip()
        observation = request.form.get("observation", "").strip()
        followup_date = request.form.get("followup_date", "").strip()
        allowed_age = {"Under 18", "18-29", "30-44", "45-59", "60+"}
        if not all([demo_code, age_band, area, observation, followup_date]):
            flash("Please complete every field.", "error")
        elif age_band not in allowed_age:
            flash("Select a valid age band.", "error")
        elif len(demo_code) > 30 or len(area) > 80 or len(observation) > 500:
            flash("One or more fields are too long.", "error")
        else:
            try:
                date.fromisoformat(followup_date)
                with get_db() as db:
                    db.execute("""
                        INSERT INTO cases (demo_code, age_band, area, observation, followup_date, created_by)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (demo_code, age_band, area, observation, followup_date, session["username"]))
                flash("Demo case added.", "success")
                return redirect(url_for("dashboard"))
            except ValueError:
                flash("Enter a valid follow-up date.", "error")
            except sqlite3.IntegrityError:
                flash("That demo code already exists. Use a unique code.", "error")
    body = """
    <div class="panel"><h1>Add a synthetic demo case</h1>
    <p class="muted">Use a fictional code such as DEMO-1004. Do not enter real names, phone numbers, addresses, or medical records.</p>
    <form method="post">
      <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
      <label>Demo case code</label><input name="demo_code" placeholder="DEMO-1004" maxlength="30" required>
      <div class="grid2">
        <div><label>Age band</label><select name="age_band" required>
          <option value="">Choose...</option><option>Under 18</option><option>18-29</option><option>30-44</option><option>45-59</option><option>60+</option>
        </select></div>
        <div><label>Community area (fictional)</label><input name="area" placeholder="North community" maxlength="80" required></div>
      </div>
      <label>Basic screening observation (non-diagnostic)</label>
      <textarea name="observation" maxlength="500" placeholder="Example: Routine screening recorded; follow-up requested." required></textarea>
      <label>Follow-up date</label><input type="date" name="followup_date" min="{{ today }}" required>
      <button type="submit">Save demo case</button> <a class="button secondary" href="{{ url_for('dashboard') }}">Cancel</a>
    </form></div>
    """
    return page("Add demo case", body, today=date.today().isoformat())

@app.route("/case/<int:case_id>/followup", methods=["POST"])
@role_required("worker", "supervisor")
def update_followup(case_id):
    if not validate_csrf():
        return redirect(url_for("dashboard"))
    status = request.form.get("status", "")
    if status not in {"Completed", "Missed"}:
        flash("Invalid follow-up status.", "error")
        return redirect(url_for("dashboard"))
    with get_db() as db:
        found = db.execute("SELECT id FROM cases WHERE id = ?", (case_id,)).fetchone()
        if not found:
            flash("Case not found.", "error")
        else:
            db.execute("UPDATE cases SET followup_status = ? WHERE id = ?", (status, case_id))
            flash("Follow-up status updated.", "success")
    return redirect(url_for("dashboard"))

@app.route("/case/<int:case_id>/referral/new", methods=["GET", "POST"])
@role_required("worker", "supervisor")
def new_referral(case_id):
    with get_db() as db:
        case = db.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not case:
        flash("Case not found.", "error")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        if not validate_csrf():
            return redirect(url_for("new_referral", case_id=case_id))
        destination = request.form.get("destination", "").strip()
        reason = request.form.get("reason", "").strip()
        priority = request.form.get("priority", "")
        if not destination or not reason or priority not in {"Routine", "Prompt review"}:
            flash("Complete all referral fields.", "error")
        elif len(destination) > 100 or len(reason) > 300:
            flash("Referral fields are too long.", "error")
        else:
            with get_db() as db:
                db.execute("""
                    INSERT INTO referrals (case_id, destination, reason, priority)
                    VALUES (?, ?, ?, ?)
                """, (case_id, destination, reason, priority))
            flash("Referral created. Follow your organization's referral procedures.", "success")
            return redirect(url_for("referrals"))
    body = """
    <div class="panel"><h1>Create referral</h1>
    <p>Case: <strong>{{ case['demo_code'] }}</strong> · Area: {{ case['area'] }}</p>
    <p class="muted">Choose a destination and priority according to approved local procedures. This app does not calculate clinical urgency.</p>
    <form method="post">
      <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
      <label>Referral destination</label><input name="destination" placeholder="Community clinic" maxlength="100" required>
      <label>Reason (administrative summary)</label><textarea name="reason" maxlength="300" placeholder="Worker-requested review" required></textarea>
      <label>Priority</label><select name="priority" required><option>Routine</option><option>Prompt review</option></select>
      <button type="submit">Create referral</button> <a class="button secondary" href="{{ url_for('dashboard') }}">Cancel</a>
    </form></div>
    """
    return page("Create referral", body, case=case)

@app.route("/referrals")
@login_required
def referrals():
    with get_db() as db:
        items = db.execute("""
            SELECT r.*, c.demo_code, c.area
            FROM referrals r JOIN cases c ON c.id = r.case_id
            ORDER BY CASE r.status WHEN 'Open' THEN 0 WHEN 'Accepted' THEN 1 ELSE 2 END,
                     r.created_at DESC
        """).fetchall()
    body = """
    <h1>Referral tracking</h1>
    <p class="muted">Statuses show administrative progress only; they do not indicate diagnosis or clinical outcome.</p>
    <div class="panel"><div class="table-wrap"><table><thead><tr><th>Case</th><th>Destination</th><th>Reason</th><th>Priority</th><th>Status</th><th>Update</th></tr></thead><tbody>
    {% for r in items %}
    <tr><td><strong>{{ r['demo_code'] }}</strong><br><span class="small muted">{{ r['area'] }}</span></td>
    <td>{{ r['destination'] }}</td><td>{{ r['reason'] }}</td><td>{{ r['priority'] }}</td>
    <td><span class="pill {% if r['status']=='Completed' %}good{% elif r['status']=='Open' %}warn{% endif %}">{{ r['status'] }}</span></td>
    <td>
      {% if session.get('role') == 'supervisor' %}
      <form method="post" action="{{ url_for('update_referral', referral_id=r['id']) }}">
        <input type="hidden" name="_csrf_token" value="{{ csrf_token() }}">
        <select name="status" aria-label="Referral status">
          {% for status in ['Open','Accepted','Completed','Cancelled'] %}
          <option value="{{ status }}" {% if r['status']==status %}selected{% endif %}>{{ status }}</option>
          {% endfor %}
        </select>
        <button type="submit">Save</button>
      </form>
      {% else %}<span class="small muted">Supervisor updates status</span>{% endif %}
    </td></tr>
    {% else %}<tr><td colspan="6">No referrals yet.</td></tr>{% endfor %}
    </tbody></table></div></div>
    """
    return page("Referrals", body, items=items)

@app.route("/referral/<int:referral_id>/update", methods=["POST"])
@role_required("supervisor")
def update_referral(referral_id):
    if not validate_csrf():
        return redirect(url_for("referrals"))
    status = request.form.get("status", "")
    if status not in {"Open", "Accepted", "Completed", "Cancelled"}:
        flash("Invalid referral status.", "error")
        return redirect(url_for("referrals"))
    with get_db() as db:
        found = db.execute("SELECT id FROM referrals WHERE id = ?", (referral_id,)).fetchone()
        if not found:
            flash("Referral not found.", "error")
        else:
            db.execute("UPDATE referrals SET status = ? WHERE id = ?", (status, referral_id))
            flash("Referral status updated.", "success")
    return redirect(url_for("referrals"))

@app.route("/about")
def about():
    body = """
    <div class="panel"><h1>How CareRoute works</h1>
    <h2>Transparent administrative rules</h2>
    <ul>
      <li>A scheduled follow-up dated before today is displayed as overdue on the dashboard.</li>
      <li>A worker can mark a follow-up Completed or Missed.</li>
      <li>A worker records referral destination, reason, and a priority chosen under local procedures.</li>
      <li>Only a supervisor can update referral status in this demo.</li>
    </ul>
    <p><strong>Role-based access concept:</strong> workers can add cases and create referrals; supervisors can also update referral statuses.</p>
    <p><strong>Privacy:</strong> the app uses fictional demo codes, age bands, and areas. This basic prototype is not a certified health-record system and lacks production-grade controls such as managed identity, audit monitoring, backups, encryption/key management, and organizational privacy review.</p>
    </div>
    """
    return page("About", body)

if __name__ == "__main__":
    init_db()
    # Local demo only. Do not expose the Flask development server to the internet.
    app.run(host="127.0.0.1", port=5000, debug=False)
