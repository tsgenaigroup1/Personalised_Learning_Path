"""
Personalized Employee Learning Path — Gradio application

Environment:
  N8N_WEBHOOK_URL   n8n POST endpoint, e.g. http://localhost:5678/webhook/employee-learning
  CERTIFICATE_DIR    optional directory for generated PDFs (default: ./certificates)

Install:
  pip install gradio requests reportlab

The content library is retrieved by n8n from CONTENT_LIBRARY_URL, so the Gradio
application does not upload the full CSV on every request.
"""
from __future__ import annotations

import datetime as dt
import html
import os
import tempfile
from pathlib import Path
from typing import Any

import gradio as gr
import requests
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

N8N_WEBHOOK_URL = os.getenv(
    "N8N_WEBHOOK_URL",
    "http://localhost:5678/webhook/employee-learning",
)
CERTIFICATE_DIR = Path(os.getenv("CERTIFICATE_DIR", Path.cwd() / "certificates"))
CERTIFICATE_DIR.mkdir(parents=True, exist_ok=True)

STYLES = [
    "Visual (videos, infographics)",
    "Hands-on (labs, projects)",
    "Reading (articles, docs, books)",
    "Auditory / Live (podcasts, live sessions)",
    "Mixed",
]


def post_n8n(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        response = requests.post(N8N_WEBHOOK_URL, json=payload, timeout=180)
    except requests.exceptions.ConnectionError:
        return None, f"Cannot reach n8n at {N8N_WEBHOOK_URL}. Check that the workflow is active."
    except requests.exceptions.Timeout:
        return None, "n8n did not respond within 180 seconds. Please retry."
    except requests.RequestException as exc:
        return None, f"Request failed: {exc}"

    try:
        data = response.json()
    except ValueError:
        return None, f"n8n returned HTTP {response.status_code}: {response.text[:500]}"

    if not response.ok or data.get("status") == "error":
        return data, data.get("message", f"Workflow failed with HTTP {response.status_code}.")
    return data, None


def assessment_payload(
    emp_id: str,
    emp_name: str,
    current_skill: str,
    career_goal: str,
    target_skill: str,
    style: str,
    experience: str,
    manager_input: str,
    slack_user_id: str,
    change_path: bool = False,
) -> dict[str, Any]:
    return {
        "action": "assessment",
        "change_path": change_path,
        "form": {
            "employee_id": emp_id.strip(),
            "employee_name": emp_name.strip(),
            "current_skill": current_skill.strip(),
            "career_goal": career_goal.strip(),
            "target_skill": target_skill.strip(),
            "learning_style": style,
            "years_of_exp": experience.strip(),
            "manager_input": manager_input.strip(),
            "slack_user_id": slack_user_id.strip(),
        },
        "submitted_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def validate_assessment(values: list[str]) -> str | None:
    labels = [
        "Employee ID",
        "Employee Name",
        "Current Skill",
        "Career Goal",
        "Target Skill",
        "Learning Style",
    ]
    missing = [label for label, value in zip(labels, values) if not (value or "").strip()]
    return ", ".join(missing) if missing else None


def render_path(data: dict[str, Any]) -> str:
    if data.get("status") == "confirmation_required":
        existing = data.get("existing_learning_path", {})
        rows = []
        for item in existing.get("path", []) or []:
            rows.append(
                f"| {item.get('week_no','')} | {item.get('topic','')} | "
                f"{item.get('format','')} | {item.get('hours',0)}h |"
            )
        table = (
            "| Week | Topic | Format | Hours |\n|---:|---|---|---:|\n"
            + "\n".join(rows)
        )
        return (
            "## Existing learning path found\n\n"
            f"**Current progress:** {existing.get('progress_pct', 0)}%\n\n"
            f"**Target:** {existing.get('target_skill', '—')}\n\n"
            "The path is incomplete. Choose **Keep current path** to continue it, "
            "or **Update path** to let the adaptive planner revise the remaining journey.\n\n"
            + table
        )
    return data.get("markdown", "No learning path was returned.")


def create_certificate(data: dict[str, Any]) -> str | None:
    if not data or data.get("progress_pct", 0) < 100:
        return None

    employee = data.get("employee", {})
    employee_name = employee.get("name", "Employee")
    employee_id = employee.get("id", "employee")
    skill = employee.get("target_skill") or data.get("target_skill") or "Professional Development"
    cert_id = data.get("certificate_id") or f"CERT-{employee_id}-{int(dt.datetime.now().timestamp())}"
    issued = dt.datetime.now(dt.timezone.utc).strftime("%d %B %Y")

    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(employee_id))
    path = CERTIFICATE_DIR / f"certificate_{safe_id}.pdf"

    page = landscape(A4)
    c = canvas.Canvas(str(path), pagesize=page)
    width, height = page

    c.setTitle(f"Certificate of Completion - {employee_name}")
    c.setLineWidth(2)
    c.rect(35, 35, width - 70, height - 70)

    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(width / 2, height - 125, "CERTIFICATE OF COMPLETION")

    c.setFont("Helvetica", 14)
    c.drawCentredString(width / 2, height - 165, "This certificate recognizes successful completion of")

    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(width / 2, height - 215, str(skill))

    c.setFont("Helvetica", 16)
    c.drawCentredString(width / 2, height - 260, f"Presented to {employee_name}")
    c.drawCentredString(width / 2, height - 285, f"Employee ID: {employee_id}")

    c.setFont("Helvetica", 11)
    c.drawCentredString(width / 2, 105, f"Issued: {issued}")
    c.drawCentredString(width / 2, 85, f"Certificate ID: {cert_id}")
    c.save()
    return str(path)


def submit_assessment(
    emp_id,
    emp_name,
    current_skill,
    career_goal,
    target_skill,
    style,
    experience,
    manager_input,
    slack_user_id,
    change_path,
):
    missing = validate_assessment(
        [emp_id, emp_name, current_skill, career_goal, target_skill, style]
    )
    if missing:
        return f"### Please complete: {missing}", "", None, None

    payload = assessment_payload(
        emp_id, emp_name, current_skill, career_goal, target_skill,
        style, experience, manager_input, slack_user_id, bool(change_path),
    )
    data, error = post_n8n(payload)
    if error:
        return f"### ⚠️ {error}", "", data, None

    if data.get("status") == "confirmation_required":
        return (
            "### 🔄 An incomplete learning path already exists\n"
            "Review it below and select **Update path** only if you want the "
            "planner to adapt it.",
            render_path(data),
            data,
            None,
        )

    certificate = create_certificate(data)
    status = (
        "### 🎓 Training complete — certificate generated"
        if data.get("progress_pct", 0) >= 100
        else f"### ✅ Learning path updated • {data.get('progress_pct', 0)}% complete"
    )
    return status, render_path(data), data, certificate


def submit_progress(
    emp_id,
    emp_name,
    progress_pct,
    content_id,
    feedback,
    slack_user_id,
):
    if not (emp_id or "").strip() or not (emp_name or "").strip():
        return "### Please enter Employee ID and Employee Name.", "", None, None

    pct = max(0, min(100, int(progress_pct)))
    payload = {
        "action": "progress_update",
        "employee_id": emp_id.strip(),
        "employee_name": emp_name.strip(),
        "slack_user_id": (slack_user_id or "").strip(),
        "progress": {
            "progress_pct": pct,
            "content_id": (content_id or "").strip(),
            "feedback": (feedback or "").strip(),
        },
        "source": "gradio",
        "submitted_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }

    data, error = post_n8n(payload)
    if error:
        return f"### ⚠️ {error}", "", data, None

    badge = data.get("badge")
    milestone = {
        "bronze": "🥉 Bronze badge unlocked — 25% complete!",
        "silver": "🥈 Silver badge unlocked — 50% complete!",
        "gold": "🥇 Gold badge unlocked — 75% complete!",
        "certificate": "🎓 Certificate earned — 100% complete!",
    }.get(badge, "")

    status = f"### ✅ Progress saved — {pct}%\n{milestone}"
    certificate = create_certificate(data)
    return status, render_path(data), data, certificate


CUSTOM_CSS = """
:root { --radius: 14px; }
.gradio-container { max-width: 1200px !important; }
.hero {
    padding: 28px;
    border-radius: 18px;
    background: linear-gradient(135deg, #172554, #1e3a8a);
    color: white;
    margin-bottom: 18px;
}
.hero h1 { margin-bottom: 6px; }
.card {
    border: 1px solid #e5e7eb;
    border-radius: 14px;
    padding: 16px;
}
"""

with gr.Blocks(
    title="Personalized Employee Learning",
    theme=gr.themes.Soft(primary_hue="blue", neutral_hue="slate"),
    css=CUSTOM_CSS,
) as demo:
    gr.HTML(
        """
        <div class="hero">
          <h1>🎯 Personalized Learning Hub</h1>
          <p>Assessment → RAG-powered learning path → weekly progress → badges → certificate</p>
        </div>
        """
    )

    with gr.Tabs():
        with gr.Tab("🧭 Assessment & Learning Path"):
            gr.Markdown(
                "Your employee ID and name are verified against HR records. "
                "The planner uses your role, experience, goals, learning style, "
                "assessment history, training progress and feedback."
            )

            with gr.Row():
                emp_id = gr.Textbox(label="Employee ID", placeholder="EMP0001")
                emp_name = gr.Textbox(label="Employee Name", placeholder="As in HR records")

            current_skill = gr.Textbox(
                label="Current Skill / Experience",
                placeholder="Python (Intermediate), basic SQL, introductory ML...",
            )
            with gr.Row():
                target_skill = gr.Textbox(label="Target Skill", placeholder="RAG / LLMOps / MLOps")
                style = gr.Dropdown(STYLES, value=STYLES[1], label="Preferred Learning Style")

            career_goal = gr.Textbox(
                label="Career Goal",
                lines=2,
                placeholder="Move into an ML engineering lead role",
            )
            with gr.Row():
                experience = gr.Textbox(label="Years of Experience", placeholder="5")
                slack_user_id = gr.Textbox(
                    label="Slack User ID (optional)",
                    placeholder="U012ABCDEF",
                    info="Enables direct Slack progress/feedback mapping.",
                )

            manager_input = gr.Textbox(
                label="Manager Development Input (optional)",
                lines=2,
                placeholder="Needs stronger system design and stakeholder communication...",
            )

            change_path = gr.Checkbox(
                label="I confirm that I want to update an existing incomplete learning path",
                value=False,
            )
            submit_btn = gr.Button("🚀 Generate / Update My Learning Path", variant="primary")

            assessment_status = gr.Markdown()
            assessment_plan = gr.Markdown()

        with gr.Tab("📈 Progress & Feedback"):
            gr.Markdown(
                "Use this after a course, lab, project or weekly check-in. "
                "The progress and feedback are stored and re-indexed into the employee RAG profile."
            )
            progress_emp_id = gr.Textbox(label="Employee ID", placeholder="EMP0001")
            progress_emp_name = gr.Textbox(label="Employee Name", placeholder="As in HR records")
            progress_pct = gr.Slider(0, 100, value=25, step=5, label="Overall Training Progress (%)")
            content_id = gr.Textbox(label="Content ID (optional)", placeholder="C0001")
            feedback = gr.Textbox(
                label="Learning Experience Feedback",
                lines=4,
                placeholder="The lab was too advanced / I want more videos / I need more practice...",
            )
            progress_slack = gr.Textbox(
                label="Slack User ID (optional)",
                placeholder="U012ABCDEF",
            )
            progress_btn = gr.Button("💾 Save Progress & Feedback", variant="primary")

            progress_status = gr.Markdown()
            progress_plan = gr.Markdown()

        with gr.Tab("🏆 Certificate"):
            gr.Markdown(
                "At 100% completion the workflow records the certificate and Slack sends "
                "a certificate-of-completion message. The application also creates a PDF."
            )
            certificate_info = gr.Markdown(
                "Complete the training to generate your certificate here."
            )

    with gr.Accordion("Technical response / debugging", open=False):
        raw_response = gr.JSON(label="n8n response")

    submit_btn.click(
        submit_assessment,
        inputs=[
            emp_id, emp_name, current_skill, career_goal, target_skill, style,
            experience, manager_input, slack_user_id, change_path,
        ],
        outputs=[assessment_status, assessment_plan, raw_response, certificate_info],
    )

    progress_btn.click(
        submit_progress,
        inputs=[
            progress_emp_id, progress_emp_name, progress_pct, content_id,
            feedback, progress_slack,
        ],
        outputs=[progress_status, progress_plan, raw_response, certificate_info],
    )

if __name__ == "__main__":
    demo.launch()
