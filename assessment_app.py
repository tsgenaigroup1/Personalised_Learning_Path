"""SkillPath - Personalized Learning Path Generator (Gradio front-end for the n8n workflow).

Flow:  Gradio form -> n8n webhook (verify employee -> Pinecone RAG -> LLM plan -> Postgres + Pinecone -> Slack)
Install: pip install "gradio>=4.44" requests pypdf reportlab
Run:     N8N_WEBHOOK_URL=https://<codespace>-5678.app.github.dev/webhook/employee-assessment python assessment_app.py

Environment variables (all optional):
  N8N_WEBHOOK_URL  production webhook URL (not /webhook-test/)
  PROPOSAL_PDF     project proposal PDF            (default: ./Capstone_Project_Proposal_Group1-Personalized_Learning_Path_Generator.pdf)
  EMPLOYEE_CSV     employee data CSV, path or URL  (default: ./employee_data.csv)
  CONTENT_CSV      content library CSV, path or URL; GitHub "blob" links are converted to raw automatically
                   (default: ./content_library.csv)
  ADMIN_KEY        pre-fills the Admin tab (must match ADMIN_KEY in the n8n "Normalize Request" node)
  APP_PORT         default 7860
"""
from __future__ import annotations

import datetime as dt
import html
import os
import re
import tempfile
import time
from pathlib import Path

import gradio as gr
import requests

HERE = Path(__file__).parent
WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/employee-assessment")
PROPOSAL = os.getenv("PROPOSAL_PDF", str(HERE / "Capstone_Project_Proposal_Group1-Personalized_Learning_Path_Generator.pdf"))
EMPLOYEES = os.getenv("EMPLOYEE_CSV", str(HERE / "employee_data.csv"))
CONTENT = os.getenv("CONTENT_CSV", str(HERE / "content_library.csv"))
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
TIMEOUT = 240

STYLES = ["Visual (videos, infographics)", "Hands-on (labs, projects)", "Reading (articles, docs, books)",
          "Auditory / Live (podcasts, live sessions)", "Mixed"]
PROFICIENCY = ["None", "Beginner", "Intermediate", "Advanced"]
BADGES = [("bronze", "🥉", "Bronze", 25), ("silver", "🥈", "Silver", 50), ("gold", "🥇", "Gold", 75), ("certificate", "🎓", "Certificate", 100)]
FORMAT_ICON = {"video": "🎬", "infographic": "🖼️", "hands-on lab": "🧪", "lab": "🧪", "project": "🛠️", "article": "📰",
               "documentation": "📘", "book": "📚", "podcast": "🎧", "live session": "🎤", "course": "🎓"}
RATINGS = ["1 😣 Not working", "2 🙁 Hard going", "3 😐 OK", "4 🙂 Good", "5 🤩 Great"]


# ------------------------------------------------------------------ context loading
def _raw_github(url: str) -> str:
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/blob/(.+)", url)
    return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else url


def _read_text(src: str) -> str:
    if src.startswith(("http://", "https://")):
        r = requests.get(_raw_github(src), timeout=30)
        r.raise_for_status()
        return r.content.decode("utf-8-sig")
    p = Path(src)
    return p.read_text(encoding="utf-8-sig") if p.exists() else ""


_CACHE: dict = {"t": 0.0, "v": None}


def load_context(force: bool = False) -> dict:
    """Proposal + employee CSV + content CSV (cached for 5 minutes)."""
    if not force and _CACHE["v"] and time.time() - _CACHE["t"] < 300:
        return _CACHE["v"]
    proposal = ""
    if Path(PROPOSAL).exists():
        from pypdf import PdfReader
        proposal = "\n".join(pg.extract_text() or "" for pg in PdfReader(PROPOSAL).pages)
    ctx = {"project_proposal": proposal, "employee_data_csv": _read_text(EMPLOYEES), "content_library_csv": _read_text(CONTENT)}
    _CACHE.update(t=time.time(), v=ctx)
    return ctx


# ------------------------------------------------------------------ API
class ApiError(Exception):
    pass


def call_api(action: str, **payload) -> dict:
    body = {"action": action, **payload, "submitted_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    try:
        r = requests.post(WEBHOOK_URL, json=body, timeout=TIMEOUT)
    except requests.exceptions.ConnectionError:
        raise ApiError(f"Cannot reach n8n at {WEBHOOK_URL}. Is the workflow active?")
    except requests.exceptions.Timeout:
        raise ApiError(f"n8n took longer than {TIMEOUT}s to respond. Please try again.")
    try:
        data = r.json()
    except ValueError:
        raise ApiError(f"Unexpected response from n8n (HTTP {r.status_code}): {r.text[:300]}")
    if isinstance(data, list):
        data = data[0] if data else {}
    if r.status_code >= 400 or data.get("status") == "error":
        raise ApiError(data.get("message") or f"Workflow error (HTTP {r.status_code})")
    return data


def _ident(emp_id: str, emp_name: str) -> dict:
    emp_id, emp_name = (emp_id or "").strip(), (emp_name or "").strip()
    if not emp_id or not emp_name:
        raise ApiError("Enter your Employee ID and Name in the sign-in bar at the top.")
    return {"employee_id": emp_id, "employee_name": emp_name}


# ------------------------------------------------------------------ HTML rendering
E = lambda x: html.escape(str(x if x is not None else ""))


def banner(kind: str, text: str) -> str:
    icon = {"ok": "✅", "warn": "⚠️", "err": "❌", "info": "ℹ️", "party": "🎉"}[kind]
    return f'<div class="sp-banner sp-{kind}"><span>{icon}</span><div>{text}</div></div>'


def _week_label(i: dict) -> str:
    w, e = int(i.get("week_no") or 0), int(i.get("end_week") or i.get("week_no") or 0)
    if w == 0:
        return "Completed earlier"
    return f"Weeks {w}–{e}" if e > w else f"Week {w}"


def render_badges(badges: dict, pct: float = 0) -> str:
    cells = []
    for key, emoji, label, at in BADGES:
        on = bool((badges or {}).get(key))
        cells.append(f'<div class="sp-badge {"on" if on else "off"}"><div class="sp-badge-em">{emoji if on else "🔒"}</div>'
                     f'<div class="sp-badge-l">{label}</div><div class="sp-badge-at">{at}%</div></div>')
    return '<div class="sp-badges">' + "".join(cells) + "</div>"


def render_progress(data: dict) -> str:
    if not data or not data.get("has_path"):
        return banner("info", "No learning path yet. Head to <b>New Assessment</b> to generate your personalised 90-day plan.")
    p = data["path"]
    pct = float(p.get("progress_pct") or 0)
    exp = float(p.get("expected_pct") or 0)
    marks = "".join(f'<span class="sp-mark" style="left:{at}%"><i></i>{emoji}</span>' for _, emoji, _, at in BADGES[:3])
    track = ("✅ On track" if p.get("on_track") else f"⏰ Behind plan (expected {exp:.0f}%)") if p.get("status") == "active" else "🎓 Completed"
    stats = [("Progress", f"{pct:.0f}%"), ("Items", f'{p.get("items_completed")}/{p.get("items_total")}'),
             ("Hours", f'{p.get("completed_hours")}/{p.get("total_hours")}'), ("Week", f'{p.get("current_week")} / 13')]
    stat_html = "".join(f'<div class="sp-stat"><div class="v">{E(v)}</div><div class="k">{E(k)}</div></div>' for k, v in stats)
    return f"""
<div class="sp-card">
  <div class="sp-row"><div><div class="sp-kicker">Target skill</div><div class="sp-h2">{E(p.get('target_skill'))}</div>
  <div class="sp-muted">{E(p.get('career_goal'))}</div></div><div class="sp-pill">{E(track)}</div></div>
  <div class="sp-bar"><div class="sp-fill" style="width:{min(pct, 100)}%"></div>
    <div class="sp-expected" style="left:{min(exp, 100)}%" title="Where the plan expects you to be"></div>{marks}</div>
  <div class="sp-stats">{stat_html}</div>
  {render_badges(data.get('badges'), pct)}
</div>"""


def render_plan(data: dict, title: str = "Your 90-day learning path") -> str:
    if not data or not data.get("has_path"):
        return ""
    p = data["path"]
    weeks: dict = {}
    for i in p.get("items", []):
        weeks.setdefault(_week_label(i), []).append(i)
    blocks = []
    for label, items in weeks.items():
        rows = []
        for i in items:
            icon = FORMAT_ICON.get(str(i.get("format", "")).lower(), "📄")
            done = i.get("done") or i.get("status") == "completed"
            url = E(i.get("url"))
            chips = "".join(f'<span class="chip{cls}">{E(pre)}{E(i.get(k))}{E(suf)}</span>'
                            for k, cls, pre, suf in (("content_id", "", "", ""), ("skill", "", "", ""), ("level", " lvl", "", ""),
                                                     ("format", "", "", ""), ("hours", "", "⏱ ", " h"), ("provider", "", "", ""),
                                                     ("cost", "", "", "")) if i.get(k) not in (None, ""))
            rows.append(f"""
<div class="sp-item {'done' if done else ''}">
  <div class="sp-item-ic">{'✅' if done else icon}</div>
  <div class="sp-item-main"><a href="{url}" target="_blank" rel="noopener">{E(i.get('topic'))}</a>
    <div class="sp-chips">{chips}</div>
    {f'<div class="sp-why">{E(i.get("rationale"))}</div>' if i.get('rationale') else ''}</div></div>""")
        blocks.append(f'<div class="sp-week"><div class="sp-week-h">{E(label)}</div>{"".join(rows)}</div>')
    extra = ""
    for k, lbl in (("skill_gap_analysis", "Skill-gap analysis"), ("personalization_notes", "How we personalised this"),
                   ("coverage_note", "Coverage note")):
        if p.get(k):
            extra += f'<div class="sp-note"><b>{lbl}:</b> {E(p[k])}</div>'
    meta = f'{E(p.get("experience_band") or "")} · {E(p.get("learning_style") or "")} · ~{E(p.get("weekly_hours") or "")} h/week · v{E(p.get("version"))}'
    return f"""<div class="sp-card"><div class="sp-h2">{E(title)}</div><div class="sp-muted">{meta}</div>
<p>{E(p.get('summary'))}</p>{extra}<div class="sp-weeks">{''.join(blocks)}</div></div>"""


def render_certificate(cert: dict | None) -> str:
    if not cert:
        return banner("info", "Complete 100% of your learning path to unlock your certificate. 🎓")
    date = str(cert.get("awarded_at") or dt.date.today().isoformat())[:10]
    return f"""
<div class="sp-cert"><div class="sp-cert-in">
  <div class="sp-cert-k">Certificate of Completion</div><div class="sp-cert-sub">This certifies that</div>
  <div class="sp-cert-name">{E(cert.get('employee_name'))}</div>
  <div class="sp-cert-sub">has successfully completed the 90-day personalised learning path in</div>
  <div class="sp-cert-skill">{E(cert.get('target_skill'))}</div>
  <div class="sp-cert-meta">{E(cert.get('items'))} learning items · {E(cert.get('total_hours'))} hours · issued {E(date)}</div>
  <div class="sp-cert-badges">🥉 🥈 🥇 🎓</div><div class="sp-cert-id">Certificate ID: {E(cert.get('cert_id'))}</div>
</div></div>"""


def certificate_pdf(cert: dict) -> str | None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfgen import canvas
    except ImportError:
        return None
    path = Path(tempfile.gettempdir()) / f"{cert.get('cert_id', 'certificate')}.pdf"
    w, h = landscape(A4)
    c = canvas.Canvas(str(path), pagesize=(w, h))
    navy, gold = colors.HexColor("#1e1b4b"), colors.HexColor("#b8860b")
    c.setFillColor(colors.HexColor("#fffdf7")); c.rect(0, 0, w, h, fill=1, stroke=0)
    c.setStrokeColor(navy); c.setLineWidth(6); c.rect(24, 24, w - 48, h - 48)
    c.setStrokeColor(gold); c.setLineWidth(1.5); c.rect(38, 38, w - 76, h - 76)
    c.setFillColor(gold); c.circle(w - 120, 120, 42, fill=1, stroke=0)
    c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 13); c.drawCentredString(w - 120, 124, "100%")
    c.setFont("Helvetica", 8); c.drawCentredString(w - 120, 110, "COMPLETE")
    y = h - 120
    for text, font, size, col, gap in [
        ("CERTIFICATE OF COMPLETION", "Helvetica-Bold", 30, navy, 46), ("This certifies that", "Helvetica-Oblique", 14, colors.grey, 46),
        (str(cert.get("employee_name", "")), "Helvetica-Bold", 34, navy, 44),
        ("has successfully completed the 90-day personalised learning path in", "Helvetica", 14, colors.grey, 40),
        (str(cert.get("target_skill", "")), "Helvetica-Bold", 24, gold, 44),
        (f"{cert.get('items', '')} learning items  ·  {cert.get('total_hours', '')} hours  ·  Bronze · Silver · Gold milestones achieved",
         "Helvetica", 11, colors.grey, 30)]:
        c.setFont(font, size); c.setFillColor(col); c.drawCentredString(w / 2, y, text); y -= gap
    c.setFont("Helvetica", 10); c.setFillColor(colors.grey)
    c.drawString(70, 80, f"Issued: {str(cert.get('awarded_at') or dt.date.today())[:10]}")
    c.drawString(70, 64, f"Certificate ID: {cert.get('cert_id', '')}   (Employee {cert.get('employee_id', '')})")
    c.showPage(); c.save()
    return str(path)


# ------------------------------------------------------------------ handlers
def _checklist_update(data: dict):
    if not data or not data.get("has_path"):
        return gr.update(choices=[], value=[], interactive=False)
    items = data["path"].get("items", [])
    choices = [(f"{i['content_id']} · {_week_label(i)} · {i.get('topic')} ({i.get('hours')} h)", i["content_id"]) for i in items]
    value = [i["content_id"] for i in items if i.get("done") or i.get("status") == "completed"]
    return gr.update(choices=choices, value=value, interactive=data["path"].get("status") == "active")


def _dashboard(data: dict, note: str = ""):
    cert = (data or {}).get("certificate")
    pdf = certificate_pdf(cert) if cert else None
    return (note, render_progress(data), render_plan(data), _checklist_update(data), data,
            render_certificate(cert), gr.update(value=pdf, visible=bool(pdf)))


def load_dashboard(emp_id, emp_name):
    try:
        data = call_api("status", **_ident(emp_id, emp_name))
    except ApiError as e:
        return _dashboard({}, banner("err", E(e)))
    return _dashboard(data, banner("ok", f"Signed in as <b>{E(data['employee']['name'])}</b> ({E(data['employee']['id'])})."))


def run_assessment(emp_id, emp_name, slack_id, current_skill, proficiency, target_skill, career_goal, style, hours, decision=""):
    hide = gr.update(visible=False)
    try:
        ident = _ident(emp_id, emp_name)
        form = {**ident, "slack_user_id": (slack_id or "").strip(), "current_skill": (current_skill or "").strip(),
                "target_proficiency": proficiency, "target_skill": (target_skill or "").strip(),
                "career_goal": (career_goal or "").strip(), "learning_style": style, "weekly_hours": hours}
        missing = [k.replace("_", " ").title() for k in ("current_skill", "target_skill", "career_goal") if not form[k]]
        if missing:
            raise ApiError("Please fill in: " + ", ".join(missing))
        data = call_api("assess", form=form, context=load_context(), decision=decision)
    except (ApiError, requests.RequestException) as e:
        return banner("err", E(e)), "", hide, ""
    status = data.get("status")
    if status == "existing_path":
        return (banner("warn", E(data.get("message"))), "", gr.update(visible=True),
                render_progress(data) + render_plan(data, "Your current path"))
    if status == "kept":
        return banner("ok", E(data.get("message"))), render_plan(data, "Your current path"), hide, ""
    if status == "no_content":
        near = ", ".join(data.get("nearest_library_skills") or [])
        return (banner("warn", f"Verified, but the library has no matching content. {E(data.get('message'))}"
                       + (f"<br><b>Closest library skills:</b> {E(near)}" if near else "")), "", hide, "")
    dropped = len(data.get("dropped_for_schedule") or []) + int(data.get("dropped_invalid_items") or 0)
    msg = f"{E(data.get('message'))} <span class='sp-muted'>(retrieval: {E(data.get('retrieval_mode'))}"
    msg += f", {dropped} suggestion(s) removed by guardrails)</span>" if dropped else ")</span>"
    return banner("ok", msg), render_progress(data) + render_plan(data), hide, ""


def save_progress(emp_id, emp_name, selected, data):
    if not data or not data.get("has_path"):
        return _dashboard(data or {}, banner("warn", "Load your dashboard first."))
    before = {i["content_id"] for i in data["path"]["items"] if i.get("done") or i.get("status") == "completed"}
    after = set(selected or [])
    updates = [{"content_id": c, "done": True} for c in after - before] + [{"content_id": c, "done": False} for c in before - after]
    if not updates:
        return _dashboard(data, banner("info", "No changes to save."))
    try:
        res = call_api("progress", **_ident(emp_id, emp_name), updates=updates)
    except ApiError as e:
        return _dashboard(data, banner("err", E(e)))
    new = res.get("new_awards") or []
    for a in new:
        gr.Info(f"{a['emoji']} {a['label']} unlocked!")
    note = banner("party", E(res.get("message"))) if new else banner("ok", E(res.get("message")))
    if any(a["award"] == "certificate" for a in new):
        note += banner("party", "Your certificate is ready in the <b>Achievements</b> tab and has been sent to you on Slack.")
    return _dashboard(res, note)


def send_feedback(emp_id, emp_name, rating, comment):
    try:
        n = int(str(rating or "0")[0]) if rating else None
        res = call_api("feedback", **_ident(emp_id, emp_name), rating=n, comment=(comment or "").strip(), source="app")
    except (ApiError, ValueError) as e:
        return banner("err", E(e)), gr.update()
    kind = "warn" if res.get("suggest_update") else "ok"
    return banner(kind, E(res.get("message"))), gr.update(value="")


def verify_cert(cert_id):
    try:
        res = call_api("verify_certificate", cert_id=(cert_id or "").strip())
    except ApiError as e:
        return banner("err", E(e))
    if res.get("status") != "valid":
        return banner("err", E(res.get("message", "Not found")))
    c = res["certificate"]
    return banner("ok", f"Valid certificate for <b>{E(c.get('employee_name'))}</b> ({E(c.get('employee_id'))}) · "
                        f"{E(c.get('target_skill'))} · issued {E(str(c.get('awarded_at'))[:10])}")


def sync_library(admin_key):
    try:
        csv_text = load_context(force=True)["content_library_csv"]
        if not csv_text.strip():
            raise ApiError(f"Content library not found at {CONTENT}")
        res = call_api("ingest_library", admin_key=admin_key, content_library_csv=csv_text)
    except (ApiError, requests.RequestException) as e:
        return banner("err", E(e))
    errs = res.get("errors") or []
    return banner("ok" if not errs else "warn", E(res.get("message")) + ("<br>" + E("; ".join(errs)) if errs else ""))


# ------------------------------------------------------------------ UI
CSS = """
.gradio-container{max-width:1180px!important;margin:auto}
.sp-hero{background:linear-gradient(120deg,#312e81,#4f46e5 55%,#7c3aed);color:#fff;border-radius:18px;padding:26px 30px;margin-bottom:6px}
.sp-hero h1{margin:0;font-size:28px;color:#fff}.sp-hero p{margin:6px 0 0;opacity:.9}
.sp-hero .sp-steps{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}.sp-hero .sp-steps span{background:rgba(255,255,255,.16);padding:5px 12px;border-radius:999px;font-size:13px}
.sp-card{background:#fff;color:#1f2937;border:1px solid #e5e7eb;border-radius:16px;padding:20px 22px;margin:8px 0;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.sp-card p{color:#374151}.sp-card a{color:#4338ca;font-weight:600;text-decoration:none}.sp-card a:hover{text-decoration:underline}
.sp-row{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.sp-kicker{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#6b7280}.sp-h2{font-size:21px;font-weight:700;color:#111827}
.sp-muted{color:#6b7280;font-size:13px}.sp-pill{background:#eef2ff;color:#3730a3;padding:6px 12px;border-radius:999px;font-weight:600;font-size:13px}
.sp-bar{position:relative;height:16px;background:#e5e7eb;border-radius:999px;margin:28px 0 14px}
.sp-fill{height:100%;border-radius:999px;background:linear-gradient(90deg,#f59e0b,#10b981);transition:width .6s}
.sp-expected{position:absolute;top:-4px;width:3px;height:24px;background:#6366f1;border-radius:2px}
.sp-mark{position:absolute;top:-24px;transform:translateX(-50%);font-size:15px}.sp-mark i{position:absolute;left:50%;top:22px;width:1px;height:18px;background:#9ca3af}
.sp-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:8px 0}
.sp-stat{background:#f9fafb;border-radius:12px;padding:10px;text-align:center}.sp-stat .v{font-size:20px;font-weight:700;color:#111827}.sp-stat .k{font-size:12px;color:#6b7280}
.sp-badges{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}
.sp-badge{border-radius:14px;padding:12px;text-align:center;border:1px dashed #d1d5db;background:#f9fafb;color:#9ca3af}
.sp-badge.on{border:1px solid #fcd34d;background:linear-gradient(160deg,#fffbeb,#fef3c7);color:#92400e;box-shadow:0 2px 8px rgba(245,158,11,.2)}
.sp-badge-em{font-size:30px}.sp-badge-l{font-weight:700}.sp-badge-at{font-size:12px}
.sp-weeks{display:flex;flex-direction:column;gap:12px;margin-top:10px}
.sp-week-h{font-weight:700;color:#4338ca;margin-bottom:6px;font-size:14px;text-transform:uppercase;letter-spacing:.05em}
.sp-item{display:flex;gap:12px;padding:12px;border:1px solid #eef0f4;border-radius:12px;margin-bottom:6px;background:#fcfcfd}
.sp-item.done{background:#f0fdf4;border-color:#bbf7d0}.sp-item.done a{color:#15803d}
.sp-item-ic{font-size:22px;line-height:1}.sp-item-main{flex:1}
.sp-chips{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}.chip{font-size:12px;background:#f3f4f6;color:#374151;padding:2px 8px;border-radius:999px}
.chip.lvl{background:#ede9fe;color:#5b21b6}.sp-why{font-size:13px;color:#6b7280}
.sp-note{background:#f8fafc;border-left:3px solid #6366f1;padding:8px 12px;border-radius:6px;margin:6px 0;color:#334155;font-size:14px}
.sp-banner{display:flex;gap:10px;align-items:flex-start;padding:12px 16px;border-radius:12px;margin:6px 0;font-size:15px}
.sp-ok{background:#ecfdf5;color:#065f46;border:1px solid #a7f3d0}.sp-warn{background:#fffbeb;color:#92400e;border:1px solid #fde68a}
.sp-err{background:#fef2f2;color:#991b1b;border:1px solid #fecaca}.sp-info{background:#eff6ff;color:#1e40af;border:1px solid #bfdbfe}
.sp-party{background:linear-gradient(90deg,#fef3c7,#fce7f3);color:#7c2d12;border:1px solid #fcd34d;font-weight:600}
.sp-cert{background:#fffdf7;border:6px solid #1e1b4b;border-radius:6px;padding:8px;margin:10px 0}
.sp-cert-in{border:1.5px solid #b8860b;padding:34px 20px;text-align:center;color:#1e1b4b}
.sp-cert-k{font-size:28px;font-weight:800;letter-spacing:.12em}.sp-cert-sub{color:#6b7280;font-style:italic;margin:10px 0}
.sp-cert-name{font-size:34px;font-weight:800;font-family:Georgia,serif}.sp-cert-skill{font-size:24px;font-weight:700;color:#b8860b}
.sp-cert-meta{color:#6b7280;margin-top:12px}.sp-cert-badges{font-size:30px;margin:12px 0}.sp-cert-id{font-family:monospace;color:#6b7280}
.sp-decision{border:2px solid #f59e0b!important;border-radius:16px!important;background:#fffbeb!important}
@media (max-width:700px){.sp-stats,.sp-badges{grid-template-columns:repeat(2,1fr)}}
"""

HERO = """<div class="sp-hero"><h1>🧭 SkillPath · Personalised Learning</h1>
<p>Answer a short assessment, get a 90-day plan built from our content library, track progress and earn badges.</p>
<div class="sp-steps"><span>1 · Assess</span><span>2 · Get your plan</span><span>3 · Learn & tick off</span>
<span>🥉 25% · 🥈 50% · 🥇 75% · 🎓 100%</span><span>💬 Slack: /learn status</span></div></div>"""


def build_ui():
    theme = gr.themes.Soft(primary_hue="indigo", secondary_hue="amber", neutral_hue="slate", radius_size="lg")
    gr_major = int(gr.__version__.split(".")[0])
    blocks_kw = {} if gr_major >= 6 else {"theme": theme, "css": CSS}
    with gr.Blocks(title="SkillPath · Learning Path Generator", **blocks_kw) as demo:
        gr.HTML(HERO)
        dash_state = gr.State({})
        with gr.Group():
            with gr.Row(equal_height=True):
                emp_id = gr.Textbox(label="Employee ID", placeholder="EMP0001", scale=2)
                emp_name = gr.Textbox(label="Employee Name", placeholder="Exactly as in HR records", scale=3)
                load_btn = gr.Button("🔄 Load my dashboard", variant="secondary", scale=1)
        top_note = gr.HTML()

        with gr.Tabs():
            # ---------------------------------------------------------- assessment
            with gr.Tab("🧭 New Assessment"):
                gr.Markdown("Tell us where you are and where you want to go. Your **experience, manager input and performance "
                            "rating** from HR records are combined with these answers to tailor the pace and level.")
                with gr.Row():
                    current_skill = gr.Textbox(label="Current skills", placeholder="e.g. Python (intermediate), basic SQL", scale=3)
                    proficiency = gr.Radio(PROFICIENCY, value="Beginner", label="Current level in the target skill", scale=2)
                with gr.Row():
                    target_skill = gr.Textbox(label="Target skill", placeholder="e.g. MLOps, LLMOps, RAG", scale=2)
                    style = gr.Dropdown(STYLES, value=STYLES[1], label="Preferred learning style", scale=2)
                    hours = gr.Slider(2, 12, value=4, step=1, label="Hours per week", scale=1)
                career_goal = gr.Textbox(label="Career goal", lines=2, placeholder="e.g. Move into an ML engineering lead role")
                with gr.Accordion("🔔 Slack notifications (optional)", open=False):
                    slack_id = gr.Textbox(label="Slack member ID", placeholder="U0123ABCD  (Slack profile ▸ ⋮ ▸ Copy member ID)",
                                          info="Or run /learn link <ID> <Name> in Slack. Enables weekly check-ins, badges and certificate in Slack.")
                submit_btn = gr.Button("✨ Generate my learning path", variant="primary", size="lg")
                assess_note = gr.HTML()
                with gr.Group(visible=False, elem_classes="sp-decision") as decision_box:
                    gr.Markdown("### You already have a learning path in progress\nChoose what to do with it:")
                    existing_html = gr.HTML()
                    with gr.Row():
                        keep_btn = gr.Button("👍 Keep current path")
                        update_btn = gr.Button("🔁 Update path (keep my progress & badges)", variant="primary")
                        replace_btn = gr.Button("🆕 Start a fresh path")
                plan_html = gr.HTML()

            # ---------------------------------------------------------- progress
            with gr.Tab("📈 My Progress"):
                progress_html = gr.HTML(render_progress({}))
                with gr.Row():
                    with gr.Column(scale=2):
                        checklist = gr.CheckboxGroup(label="Tick what you have finished", choices=[], interactive=False)
                        save_btn = gr.Button("💾 Save progress", variant="primary")
                    with gr.Column(scale=3):
                        my_plan_html = gr.HTML()

            # ---------------------------------------------------------- achievements
            with gr.Tab("🏆 Achievements"):
                cert_html = gr.HTML(render_certificate(None))
                cert_file = gr.File(label="Download certificate (PDF)", visible=False, interactive=False)
                with gr.Accordion("🔎 Verify a certificate", open=False):
                    with gr.Row():
                        cert_id = gr.Textbox(label="Certificate ID", placeholder="CERT-EMP0001-12-…", scale=4)
                        verify_btn = gr.Button("Verify", scale=1)
                    verify_out = gr.HTML()

            # ---------------------------------------------------------- feedback
            with gr.Tab("💬 Feedback"):
                gr.Markdown("How is your learning path going? Feedback is stored with your profile and used the next time "
                            "your path is updated (e.g. slower pace, more hands-on).")
                rating = gr.Radio(RATINGS, value=RATINGS[3], label="Overall")
                comment = gr.Textbox(label="Comments", lines=3, placeholder="e.g. Labs are great but week 3 felt too fast")
                fb_btn = gr.Button("Send feedback", variant="primary")
                fb_note = gr.HTML()

            # ---------------------------------------------------------- admin
            with gr.Tab("⚙️ Admin"):
                gr.Markdown(f"**n8n webhook:** `{WEBHOOK_URL}`  \n**Content library:** `{CONTENT}`  \n"
                            "Sync embeds every content item into Pinecone (namespace `content-library`) so assessments use RAG retrieval. "
                            "Run it once and again whenever the CSV changes.")
                admin_key = gr.Textbox(label="Admin key", type="password", value=ADMIN_KEY)
                sync_btn = gr.Button("⬆️ Sync content library to Pinecone")
                sync_note = gr.HTML()

        # ---------------------------------------------------------- wiring
        dash_outputs = [top_note, progress_html, my_plan_html, checklist, dash_state, cert_html, cert_file]
        form_inputs = [emp_id, emp_name, slack_id, current_skill, proficiency, target_skill, career_goal, style, hours]
        assess_outputs = [assess_note, plan_html, decision_box, existing_html]

        load_btn.click(load_dashboard, [emp_id, emp_name], dash_outputs)
        emp_name.submit(load_dashboard, [emp_id, emp_name], dash_outputs)

        def refresh_quietly(i, n):
            out = list(load_dashboard(i, n))
            out[0] = gr.update()  # keep the top banner as is
            return out

        submit_btn.click(lambda: banner("info", "⏳ Verifying and building your plan (this can take up to a minute)…"),
                         None, assess_note).then(run_assessment, form_inputs, assess_outputs) \
                  .then(refresh_quietly, [emp_id, emp_name], dash_outputs)
        def decider(decision):
            def handler(i, n, s, c, p, t, g, st, h):
                return run_assessment(i, n, s, c, p, t, g, st, h, decision=decision)
            return handler

        for btn, decision in ((keep_btn, "keep"), (update_btn, "update"), (replace_btn, "replace")):
            btn.click(lambda: banner("info", "⏳ Working on it…"), None, assess_note) \
               .then(decider(decision), form_inputs, assess_outputs) \
               .then(refresh_quietly, [emp_id, emp_name], dash_outputs)

        save_btn.click(save_progress, [emp_id, emp_name, checklist, dash_state], dash_outputs)
        verify_btn.click(verify_cert, cert_id, verify_out)
        fb_btn.click(send_feedback, [emp_id, emp_name, rating, comment], [fb_note, comment])
        sync_btn.click(sync_library, admin_key, sync_note)
    launch_kw = {"theme": theme, "css": CSS} if gr_major >= 6 else {}
    return demo, launch_kw


if __name__ == "__main__":
    app, kw = build_ui()
    app.queue().launch(server_name="0.0.0.0", server_port=int(os.getenv("APP_PORT", "7860")), **kw)
