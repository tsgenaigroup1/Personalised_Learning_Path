# SkillPath v2: setup

## 1. Postgres
Run `schema.sql` against the database that already holds `employees`. It adds `slack_user_id` to `employees` and creates
`learning_paths`, `path_items`, `awards` and `feedback`, plus a `v_learning_metrics` view for the completion and satisfaction report.

## 2. Pinecone
Create a serverless index with **dimension 1536** and **metric cosine** (this matches `text-embedding-3-small`). Copy the index **Host**.

Two namespaces are used:

| Namespace | Vector id | Contents |
|---|---|---|
| `content-library` | `C0001` | One vector per content item. Metadata holds skill, topic, level, level_rank, format, hours, provider, cost, url and prereqs. |
| `employee-learning` | `assessment#EMP#path` | Form answers plus the experience profile. |
| | `path#EMP#path` | The learning path. Its metadata is updated on every progress change: status, progress_pct, completed_ids and badges. |
| | `feedback#EMP#id` | Each piece of feedback, as an embedding. |

## 3. n8n
1. Import `Employee_Assessment_-_Learning_Path_v2.json`.
2. Open **Normalize Request** and edit the `CFG` block. Set `PINECONE_HOST`, `ADMIN_KEY` and, if needed, `OPENAI_MODEL`.
3. Open **Parse Slack Request** and edit the `SLACK_CFG` block. Set `VERIFICATION_TOKEN`, `INTERNAL_URL` (normally `http://localhost:5678/webhook/employee-assessment`) and `APP_URL`.
4. Set up credentials:
   - **Postgres** and **OpenAI**: these are already referenced by the workflow.
   - **Header Auth** for Pinecone: Name `Api-Key`, Value is your key. Attach it to all 6 nodes whose names contain "Pinecone".
   - **Slack API** (bot token `xoxb-…`): attach it to *Slack Post New Path*, *Slack Post Award* and *Send Check-in*.
5. Activate the workflow. The workflow uses production URLs `/webhook/...`.

## 4. Slack app
- **Slash command** `/learn`, with Request URL `https://<n8n-host>/webhook/slack-learning`.
- **Interactivity**: turn it on and use the same Request URL. The Done and feedback buttons in the weekly check-ins need this.
- **Bot scopes**: `chat:write`, `commands`, `im:write`. Install the app to the workspace.
- **Commands**:
  - `/learn link EMP0001 Full Name` links your Slack account (run once).
  - `/learn status` shows your progress.
  - `/learn done C0003` marks an item complete, and `/learn undo C0003` reverses it.
  - `/learn feedback 4 too fast` sends a rating and comment.
- Weekly check-ins go out every Monday at 09:00 in the n8n timezone. They include progress, items that are due with Done buttons, and feedback buttons.

## 5. Gradio app
```bash
pip install "gradio>=4.44" requests pypdf reportlab
export N8N_WEBHOOK_URL=https://<codespace>-5678.app.github.dev/webhook/employee-assessment
export CONTENT_CSV=https://github.com/<org>/<repo>/blob/main/content_library.csv   # a path or a GitHub URL both work
export ADMIN_KEY=change-me
python assessment_app.py
```
After the app starts, open the **Admin** tab and click **Sync content library to Pinecone**. Run the sync once, and again whenever the CSV changes.
Until the library has been synced, assessments fall back to the full CSV catalog.

## Webhook API (`POST /webhook/employee-assessment`)
| action | body | result |
|---|---|---|
| `assess` | `form{employee_id, employee_name, current_skill, target_skill, target_proficiency, career_goal, learning_style, weekly_hours, slack_user_id?}`, `context{…csv…}`, `decision?` = `keep`/`update`/`replace` | `success`, `existing_path`, `kept` or `no_content` |
| `status` | `employee_id`, `employee_name` | Path, progress, badges and certificate |
| `progress` | `employee_id`, `employee_name`, `updates[{content_id, done}]` | Same as status, plus `new_awards` |
| `feedback` | `employee_id`, `employee_name`, `rating` (1-5), `comment` | Message and `suggest_update` |
| `verify_certificate` | `cert_id` | `valid` or `invalid` |
| `ingest_library` | `admin_key`, `content_library_csv` | Upsert counts |

## Hardening before production
- Swap the Slack verification-token check for signing-secret verification. Enable the webhook's raw body option and an HMAC check in a Code node; this needs `NODE_FUNCTION_ALLOW_BUILTIN=crypto`.
- Put the n8n webhooks behind auth, for example header auth on the Webhook node, with the matching header sent from the app.
