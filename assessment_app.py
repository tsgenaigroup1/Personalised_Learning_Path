"""Employee Assessment Form (Gradio) -> n8n webhook -> verified, personalized learning plan.
Install:  pip install gradio requests pypdf
Run:      N8N_WEBHOOK_URL=https://<your-n8n>/webhook/employee-assessment python assessment_app.py
Context files are read from the folder of this script (override with PROPOSAL_PDF / EMPLOYEE_CSV / CONTENT_CSV)."""
import os, datetime, requests, gradio as gr
from pathlib import Path

HERE = Path(__file__).parent
WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/employee-assessment")  # production URL, not /webhook-test/
PROPOSAL = Path(os.getenv("PROPOSAL_PDF", HERE / "Capstone_Project_Proposal_Group1-Personalized_Learning_Path_Generator.pdf"))
EMPLOYEES = Path(os.getenv("EMPLOYEE_CSV", HERE / "employee_data.csv"))
CONTENT = Path(os.getenv("CONTENT_CSV", HERE / "content_library.csv"))
STYLES = ["Visual (videos, infographics)", "Hands-on (labs, projects)", "Reading (articles, docs, books)",
          "Auditory / Live (podcasts, live sessions)", "Mixed"]

def load_context() -> dict:
    missing = [p.name for p in (PROPOSAL, EMPLOYEES, CONTENT) if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing context file(s): " + ", ".join(missing))
    from pypdf import PdfReader
    return {"project_proposal": "\n".join(pg.extract_text() or "" for pg in PdfReader(str(PROPOSAL)).pages),
            "employee_data_csv": EMPLOYEES.read_text(encoding="utf-8-sig"),
            "content_library_csv": CONTENT.read_text(encoding="utf-8-sig")}

def submit(emp_id, emp_name, current_skill, career_goal, target_skill, style):
    form = {"employee_id": (emp_id or "").strip(), "employee_name": (emp_name or "").strip(),
            "current_skill": (current_skill or "").strip(), "career_goal": (career_goal or "").strip(),
            "target_skill": (target_skill or "").strip(), "learning_style": style}
    empty = [k.replace("_", " ").title() for k, v in form.items() if not v]
    if empty:
        return "⚠️ Please fill in: " + ", ".join(empty), "", None
    try:
        payload = {"form": form, "context": load_context(),
                   "submitted_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        r = requests.post(WEBHOOK_URL, json=payload, timeout=180)
    except FileNotFoundError as e:
        return f"❌ {e}", "", None
    except requests.exceptions.ConnectionError:
        return f"❌ Cannot reach n8n at {WEBHOOK_URL}. Is the workflow active?", "", None
    except requests.exceptions.Timeout:
        return "❌ n8n took too long to respond (over 180s). Try again.", "", None
    try:
        data = r.json()
    except ValueError:
        return f"❌ Unexpected response from n8n (HTTP {r.status_code}): {r.text[:300]}", "", None
    if r.status_code in (401, 403) or data.get("status") == "error":
        return "❌ " + data.get("message", "Verification failed."), "", data
    if not r.ok:
        return f"❌ Workflow error (HTTP {r.status_code}): {data.get('message', r.text[:300])}", "", data
    icon = "✅ Verified. Plan generated." if data.get("status") == "success" else "⚠️ Verified, but no matching content."
    return icon, data.get("markdown", ""), data

with gr.Blocks(title="Employee Assessment Form") as demo:
    gr.Markdown("# Employee Assessment Form\nEnter your details exactly as in HR records. Your ID and name are verified before a plan is generated.")
    with gr.Row():
        emp_id = gr.Textbox(label="Employee ID", placeholder="EMP0001")
        emp_name = gr.Textbox(label="Employee Name", placeholder="As in HR records")
    current_skill = gr.Textbox(label="Current Skill", placeholder="e.g. Python (Intermediate), basic SQL")
    with gr.Row():
        target_skill = gr.Textbox(label="Target Skill", placeholder="e.g. LLMOps, RAG, MLOps")
        style = gr.Dropdown(STYLES, value=STYLES[1], label="Preferred Learning Style")
    career_goal = gr.Textbox(label="Career Goal", lines=2, placeholder="e.g. Move into an ML engineering lead role")
    btn = gr.Button("Submit Assessment", variant="primary")
    status = gr.Markdown()
    plan = gr.Markdown()
    with gr.Accordion("Raw response (debug)", open=False):
        raw = gr.JSON()
    btn.click(submit, [emp_id, emp_name, current_skill, career_goal, target_skill, style], [status, plan, raw])

if __name__ == "__main__":
    demo.launch()
