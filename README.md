# SkillPath – Personalized Learning Path Generator

SkillPath is a personalized learning path generator that uses a Gradio front end, n8n workflow automation, OpenAI models, Pinecone RAG, PostgreSQL persistence, and optional Slack notifications.

The application collects an employee's learning assessment, verifies the employee, retrieves relevant content from the content library, generates a personalized 90-day learning path, stores the result, tracks progress and feedback, and supports gamification/certificate verification.

---

## 1. Solution Architecture

```text
                    ┌─────────────────────────┐
                    │      Gradio UI          │
                    │   assessment_app.py     │
                    └────────────┬────────────┘
                                 │
                                 │ HTTP Webhook
                                 ▼
                    ┌─────────────────────────┐
                    │          n8n             │
                    │ Employee Assessment     │
                    │       Workflow          │
                    └────────────┬────────────┘
                                 │
               ┌─────────────────┼──────────────────┐
               │                 │                  │
               ▼                 ▼                  ▼
       ┌──────────────┐  ┌───────────────┐  ┌──────────────┐
       │ Employee     │  │ OpenAI        │  │ Pinecone     │
       │ Verification │  │ Embeddings +  │  │ RAG          │
       │ / PostgreSQL │  │ Learning Plan │  │              │
       └──────────────┘  └───────────────┘  └──────────────┘
               │                 │                  │
               └─────────────────┼──────────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │ PostgreSQL              │
                    │ Paths / Items / Awards  │
                    │ Feedback                │
                    └─────────────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │ Slack Notifications     │
                    │        (Optional)       │
                    └─────────────────────────┘
```

---

## 2. Project Structure

Recommended project structure:

```text
SkillPath/
├── assessment_app.py
├── employee_data.csv
├── content_library.csv
├── schema.sql
├── Capstone_Project_Proposal_Group1-Personalized_Learning_Path_Generator.pdf
├── Employee Assessment - Learning Path (RAG + Slack + Gamification).json
├── .env
├── .gitignore
└── README.md
```

Do not commit API keys, database passwords, Slack tokens, Pinecone keys, or webhook URLs.

---

## 3. Prerequisites

You need:

- Python 3.10+
- Git / GitHub Codespaces
- n8n
- OpenAI API access
- Pinecone account and API key
- PostgreSQL database
- Slack workspace/app if Slack notifications are required

---

## 4. Python Environment

Create and activate a virtual environment.

### Linux / GitHub Codespaces

```bash
python -m venv .venv
source .venv/bin/activate
```

Install the required packages:

```bash
pip install "gradio>=4.44" requests pypdf reportlab
```

If your environment already contains compatible versions, you can continue using those packages.

---

## 5. PostgreSQL Setup

Create the PostgreSQL database and run the supplied schema.

The application uses the following logical tables:

```text
employees
learning_paths
path_items
awards
feedback
```

The database is used for employee verification, learning-path persistence, progress tracking, awards/gamification, and feedback.

Use the project's `schema.sql` file as the source of truth for the exact table definitions.

---

## 6. Pinecone Setup

Create **one Pinecone serverless index** for the SkillPath workflow.

### Required configuration

| Setting | Value |
|---|---|
| Dimension | `1536` |
| Metric | `cosine` |
| Embedding model | `text-embedding-3-small` |
| Content namespace | `content-library` |
| Employee namespace | `employee-learning` |

The current SkillPath workflow expects a 1536-dimensional embedding space.

> Important: An older/other setup may use 512 dimensions. Do **not** use 512 dimensions for this SkillPath workflow when using the configured `text-embedding-3-small` embeddings.

### Pinecone namespaces

Pinecone namespaces are created implicitly when vectors are first inserted.

The workflow uses:

```text
content-library
employee-learning
```

Logical layout:

```text
Pinecone Index
│
├── content-library
│   ├── C0001
│   ├── C0002
│   └── ...
│
└── employee-learning
    ├── assessment#EMP001#PATH001
    ├── path#EMP001#PATH001
    ├── feedback#EMP001#1
    └── ...
```

---

## 7. Pinecone Content Library

The content library is loaded into the `content-library` namespace.

Each content item is converted into an embedding and stored as a Pinecone vector.

Typical metadata includes:

```text
content_id
skill
topic
level
level_rank
format
hours
provider
cost
url
prereqs
text
```

The vector ID is the content ID, for example:

```text
C0001
C0002
C0003
```

---

## 8. Employee Learning Namespace

The `employee-learning` namespace stores employee-specific learning information.

### Assessment vector

Example ID:

```text
assessment#EMP001#PATH001
```

Contains employee assessment/profile information such as:

- Current skill
- Learning style
- Target proficiency
- Decision/profile information
- Assessment text

### Learning path vector

Example ID:

```text
path#EMP001#PATH001
```

Contains information such as:

- Learning path version
- Status
- Progress percentage
- Total hours
- Number of items
- Completed content IDs
- Badges
- Updated timestamp
- Learning path text

### Feedback vectors

Example ID:

```text
feedback#EMP001#1
```

Each feedback item can be embedded and stored in the same employee namespace.

---

## 9. Import the n8n Workflow

Import:

```text
Employee Assessment - Learning Path (RAG + Slack + Gamification).json
```

The workflow supports these logical actions:

```text
assess
status
progress
feedback
verify_certificate
ingest_library
```

The production webhook used by the Gradio application is:

```text
/webhook/employee-assessment
```

Make sure the workflow is active when using the production webhook.

---

## 10. n8n Configuration

The workflow contains a `Normalize Request` configuration similar to:

```javascript
const CFG = {
  PINECONE_HOST: 'YOUR_PINECONE_INDEX_HOST',
  NS_CONTENT: 'content-library',
  NS_EMPLOYEE: 'employee-learning',
  EMBED_MODEL: 'text-embedding-3-small',
  OPENAI_MODEL: 'YOUR_AVAILABLE_OPENAI_MODEL',
  ADMIN_KEY: 'YOUR_ADMIN_KEY',
  TOP_K: 40,
  DEFAULT_WEEKLY_HOURS: 4,
  MAX_ROWS: 400
};
```

Replace the placeholder values with your actual configuration.

### Pinecone host

Use the host shown in the Pinecone console for the SkillPath index.

Example format:

```text
https://<index-name>-<id>.svc.<region>.pinecone.io
```

Do not invent or substitute a different index host.

---

## 11. Pinecone n8n Credential

For the HTTP Request nodes that call Pinecone, use:

```text
Authentication:
Generic Credential Type

Credential Type:
HTTP Header Auth
```

Configure the header as:

```text
Name: Api-Key
Value: <YOUR_PINECONE_API_KEY>
```

The Pinecone API key should never be hard-coded into the workflow or committed to Git.

---

## 12. OpenAI Configuration

The workflow uses:

```text
text-embedding-3-small
```

for embeddings.

The configured embedding dimension for this project is:

```text
1536
```

The chat model is configured through the workflow's `OPENAI_MODEL` setting.

Use an OpenAI model that is available to your project/account.

Example:

```javascript
OPENAI_MODEL: 'YOUR_AVAILABLE_OPENAI_MODEL'
```

Do not assume a model is available simply because it appears in an example configuration.

---

## 13. Gradio Environment Variables

The Gradio application can use environment variables similar to:

```bash
export N8N_WEBHOOK_URL="https://<codespace>-5678.app.github.dev/webhook/employee-assessment"
export PROPOSAL_PDF="./Capstone_Project_Proposal_Group1-Personalized_Learning_Path_Generator.pdf"
export EMPLOYEE_CSV="./employee_data.csv"
export CONTENT_CSV="./content_library.csv"
export ADMIN_KEY="YOUR_ADMIN_KEY"
export APP_PORT=7860
```

On Windows PowerShell, the equivalent syntax is:

```powershell
$env:N8N_WEBHOOK_URL="https://<codespace>-5678.app.github.dev/webhook/employee-assessment"
$env:PROPOSAL_PDF="./Capstone_Project_Proposal_Group1-Personalized_Learning_Path_Generator.pdf"
$env:EMPLOYEE_CSV="./employee_data.csv"
$env:CONTENT_CSV="./content_library.csv"
$env:ADMIN_KEY="YOUR_ADMIN_KEY"
$env:APP_PORT="7860"
```

Keep secrets in environment variables or a local `.env` file.

---

## 14. Start the Gradio Application

From the project directory:

```bash
python assessment_app.py
```

The Gradio application runs on the configured application port, commonly:

```text
7860
```

In GitHub Codespaces, use the forwarded port URL provided by Codespaces.

---

## 15. Employee Assessment

The assessment form contains fields including:

```text
Employee ID
Employee Name
Current Skill
Career Goal
Target Skill
Preferred Learning Style
Weekly Hours
Slack ID (optional)
```

The employee ID and employee name are verified against the employee database/data source before the learning path is generated.

---

## 16. End-to-End Learning Path Flow

The main flow is:

```text
Employee
   │
   ▼
Gradio Assessment Form
   │
   ▼
n8n Webhook
   │
   ▼
Validate Request
   │
   ▼
Verify Employee ID + Name
   │
   ├── Invalid → Return validation response
   │
   ▼
Generate Employee Profile / Assessment
   │
   ▼
Create Query Embedding
   │
   ▼
Pinecone RAG Retrieval
   │
   ├── content-library
   │
   └── completed employee paths
   │
   ▼
Generate Personalized Learning Path
   │
   ▼
Store in PostgreSQL
   │
   ▼
Store employee vectors in Pinecone
   │
   ▼
Optional Slack Notification
   │
   ▼
Return Learning Path to Gradio
```

---

## 17. Content Library Ingestion

The Gradio Admin section can trigger content-library ingestion.

The logical flow is:

```text
content_library.csv
       │
       ▼
Build Library Batches
       │
       ▼
OpenAI Embeddings
       │
       ▼
Build Library Upserts
       │
       ▼
Pinecone Upsert Library
       │
       ▼
content-library namespace
```

For the current project data, the content library contains:

```text
1,372 content items
```

With the workflow's batching approach, the data is divided into multiple Pinecone upsert requests.

After successful ingestion, the namespace should contain the expected content vectors.

---

## 18. Verify Content Library Ingestion

After running:

```text
Admin → Sync content library to Pinecone
```

verify the Pinecone index.

Check:

```text
Namespace:
content-library
```

The vector count should correspond to the number of successfully ingested content items.

For the current 1,372-item library, the expected successful count is:

```text
1,372 vectors
```

If the workflow reports:

```text
Upserted 0 of 1372 content items
```

do not assume the data is present. Check the Pinecone HTTP Request node and its actual response.

---

## 19. Troubleshooting: Pinecone Upsert Failure

### Error

```text
Upserted 0 of 1372 content items into Pinecone namespace "content-library".
Cannot read properties of undefined (reading 'status')
```

The `undefined status` message can be a downstream symptom. First inspect the Pinecone upsert request itself.

### Check 1 — Pinecone index

Confirm:

```text
Dimension: 1536
Metric: cosine
```

### Check 2 — Pinecone host

Confirm that:

```text
PINECONE_HOST
```

matches the host of the correct Pinecone index.

### Check 3 — Pinecone API key

Confirm the n8n credential uses:

```text
Header name: Api-Key
Header value: <Pinecone API key>
```

### Check 4 — HTTP Request node

For `Pinecone Upsert Library`, verify:

```text
Method: POST
URL: {{$json.url}}
Send Body: ON
Body Content Type: JSON
```

The JSON body should be the generated request body:

```text
{{$json.body}}
```

or the corresponding JSON-string expression used by the imported workflow.

### Check 5 — Never Error

Temporarily turn:

```text
Never Error
```

OFF.

This allows the actual Pinecone HTTP error to surface instead of allowing a later node to fail while reading an undefined response.

---

## 20. Common Pinecone Errors

### Dimension mismatch

Typical problem:

```text
Vector dimension does not match index dimension
```

For this project:

```text
Index dimension = 1536
Embedding model = text-embedding-3-small
```

If an older index was created with 512 dimensions, create/use the correct 1536-dimensional index for this workflow.

### Unauthorized

Check:

```text
Api-Key
```

and make sure the key belongs to the correct Pinecone account/project.

### Wrong host

Make sure the URL points to the intended SkillPath index.

### Empty namespace

If the namespace is empty, ingestion may not have succeeded.

Run the content ingestion again after correcting the underlying Pinecone request.

---

## 21. RAG Retrieval

The workflow prepares two Pinecone queries.

### Content retrieval

Uses:

```text
Namespace:
content-library
```

with a configured top-K value.

Current configuration:

```text
TOP_K = 40
```

Metadata is included with the retrieved vectors.

### Completed peer paths

The workflow also searches:

```text
employee-learning
```

for completed learning paths.

The retrieval filter uses path records with:

```text
type = path
status = completed
```

This can provide completed-path context for the learning-path generation flow.

---

## 22. Progress Tracking

Learning-path progress is persisted in the system.

The employee path vector tracks fields such as:

```text
status
progress_pct
items_total
items_completed
content_ids
completed_ids
badges
updated_at
```

When progress changes, the corresponding employee learning-path record can be updated.

---

## 23. Gamification

The workflow supports badges/awards.

Badges can be associated with completed learning-path activities.

The employee path metadata contains a list of active badges.

Example metadata concept:

```text
badges:
[
  ...
]
```

The exact badge logic should follow the imported n8n workflow.

---

## 24. Feedback

Employee feedback is stored and can also be embedded into Pinecone.

Feedback vectors use the:

```text
employee-learning
```

namespace.

The logical ID format is:

```text
feedback#<employee_id>#<feedback_id>
```

This allows feedback to remain associated with the employee.

---

## 25. Slack Integration (Optional)

Slack notifications are optional.

A Slack app can be configured with the required permissions and used by n8n to send learning-path notifications.

Typical Slack setup:

1. Create a Slack app.
2. Enable the required Slack features/scopes.
3. Install the app in the workspace.
4. Ensure the bot has access to the target channel.
5. Configure the Slack credentials/webhook used by the workflow.
6. Keep Slack secrets outside source control.

Do not commit a Slack webhook URL or token to GitHub.

---

## 26. GitHub Codespaces

If running in GitHub Codespaces:

1. Open the repository in Codespaces.
2. Install Python dependencies.
3. Start n8n.
4. Import/activate the n8n workflow.
5. Forward the n8n port, commonly `5678`.
6. Use the Codespaces HTTPS URL for the n8n webhook.
7. Start the Gradio application.
8. Forward the Gradio port, commonly `7860`.
9. Open the Gradio URL.

Example n8n webhook format:

```text
https://<codespace>-5678.app.github.dev/webhook/employee-assessment
```

The exact Codespaces host is generated by GitHub and will vary.

---

## 27. Security

Never commit:

```text
OpenAI API keys
Pinecone API keys
PostgreSQL passwords
Slack tokens
Slack webhook URLs
Admin keys
OAuth credentials
```

Recommended `.gitignore` entries:

```gitignore
.env
.venv/
__pycache__/
*.pyc
.DS_Store
```

If a secret is accidentally committed, rotate/revoke it immediately and remove it from the repository history as appropriate.

---

## 28. Recommended Test Sequence

Use this order when validating the complete application.

### Test 1 — PostgreSQL

Verify the database connection and employee records.

### Test 2 — Pinecone

Verify:

```text
Index dimension = 1536
Metric = cosine
```

### Test 3 — Content ingestion

Run:

```text
Admin → Sync content library to Pinecone
```

Confirm:

```text
content-library
```

contains the expected vectors.

### Test 4 — Employee verification

Submit a known employee ID and matching employee name.

### Test 5 — Invalid employee

Submit an invalid employee ID/name combination.

The workflow should reject the request rather than generate a path for an unverified employee.

### Test 6 — Learning path generation

Submit a valid assessment and verify that a personalized learning path is returned.

### Test 7 — PostgreSQL persistence

Confirm the learning path and path items are stored.

### Test 8 — Pinecone employee storage

Verify:

```text
employee-learning
```

contains assessment/path vectors.

### Test 9 — Progress

Mark learning content as completed and verify progress updates.

### Test 10 — Feedback

Submit feedback and verify the feedback record/vector.

### Test 11 — Slack

If Slack is enabled, verify the notification is delivered.

### Test 12 — Certificate verification

Use the certificate verification flow and confirm the expected response.

---

## 29. Quick Validation Checklist

Before the final demo, verify:

- [ ] Gradio starts successfully.
- [ ] n8n workflow is imported.
- [ ] n8n workflow is active.
- [ ] Production webhook is used.
- [ ] Employee data is available.
- [ ] PostgreSQL schema is created.
- [ ] Pinecone index dimension is 1536.
- [ ] Pinecone metric is cosine.
- [ ] `content-library` namespace is populated.
- [ ] `employee-learning` namespace is available.
- [ ] OpenAI embedding model is configured.
- [ ] OpenAI chat model is available to the project.
- [ ] Employee ID/name verification works.
- [ ] RAG retrieval returns content.
- [ ] Learning path is generated.
- [ ] Learning path is persisted.
- [ ] Progress tracking works.
- [ ] Badges/gamification work.
- [ ] Feedback works.
- [ ] Slack works if enabled.
- [ ] Certificate verification works.
- [ ] Secrets are not committed to Git.

---

## 30. Demo Flow

A complete demonstration can follow this sequence:

```text
1. Show project architecture
        ↓
2. Show employee_data.csv
        ↓
3. Show content_library.csv
        ↓
4. Show PostgreSQL schema
        ↓
5. Show Pinecone index
        ↓
6. Show content-library namespace
        ↓
7. Show n8n workflow
        ↓
8. Sync content library
        ↓
9. Open Gradio assessment form
        ↓
10. Enter employee details
        ↓
11. Verify employee
        ↓
12. Generate personalized learning path
        ↓
13. Show RAG-based recommendations
        ↓
14. Show saved learning path
        ↓
15. Update progress
        ↓
16. Demonstrate badges/gamification
        ↓
17. Submit feedback
        ↓
18. Show optional Slack notification
        ↓
19. Demonstrate certificate verification
```

---

## 31. Data Flow Summary

```text
Employee Assessment
        │
        ▼
Employee Verification
        │
        ▼
Assessment/Profile
        │
        ▼
Embedding Generation
        │
        ▼
Pinecone Retrieval
        │
        ├── Content Library
        │
        └── Completed Learning Paths
        │
        ▼
Personalized Learning Path
        │
        ├── PostgreSQL
        │
        ├── Pinecone
        │
        └── Slack (optional)
        │
        ▼
Progress + Feedback + Gamification
```

---

## 32. Success Criteria

The implementation is considered operational when:

1. The Gradio assessment form loads.
2. Employee ID and employee name can be verified.
3. The content library can be ingested into Pinecone.
4. The `content-library` namespace contains the expected vectors.
5. RAG retrieval returns relevant learning content.
6. A personalized learning path is generated.
7. Learning paths are persisted in PostgreSQL.
8. Employee learning vectors are stored in Pinecone.
9. Progress can be updated.
10. Feedback can be recorded.
11. Gamification/badges can be updated.
12. Slack notifications work when configured.
13. Certificate verification works.
14. Secrets are kept out of source control.

---

## 33. Important Configuration Notes

### Do not mix the old 512-dimension setup with this project

This SkillPath workflow is configured for:

```text
text-embedding-3-small
1536 dimensions
cosine similarity
```

If you see a Pinecone index configured for 512 dimensions from another project/workflow, do not use that index for the current SkillPath workflow without changing the embedding/index configuration consistently.

### Use the production n8n webhook for Gradio

When the workflow is active, use:

```text
/webhook/employee-assessment
```

rather than relying on a temporary test webhook.

### Check the first failing node

When n8n displays an error from a later node such as:

```text
Cannot read properties of undefined (reading 'status')
```

inspect the immediately preceding HTTP Request/API node first. The displayed error can be a consequence of an earlier failed API request.

---

## 34. Project Components

| Component | Purpose |
|---|---|
| Gradio | Employee-facing UI |
| n8n | Workflow orchestration |
| PostgreSQL | Structured persistence |
| Pinecone | Vector database / RAG |
| OpenAI embeddings | Convert content and employee information to vectors |
| OpenAI chat model | Generate personalized learning paths |
| Slack | Optional notifications |
| GitHub Codespaces | Development/runtime environment |

---

## 35. Final Architecture

```text
                         SkillPath
                            │
            ┌───────────────┴───────────────┐
            │                               │
       Employee UI                    Administration
       (Gradio)                       (n8n/Admin)
            │                               │
            └───────────────┬───────────────┘
                            │
                            ▼
                         n8n
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
          ▼                 ▼                 ▼
      PostgreSQL         OpenAI           Pinecone
      Employee DB        Embeddings       RAG
      Learning Paths     + LLM            Vectors
      Progress           │                 │
      Feedback           └────────┬────────┘
                                  │
                                  ▼
                         Personalized Path
                                  │
                    ┌─────────────┴─────────────┐
                    │                           │
                 Progress                    Slack
                 + Badges                  Notification
                    │
                    ▼
                 Feedback
```

---

## 36. Troubleshooting Quick Reference

| Problem | What to check |
|---|---|
| Gradio cannot connect to n8n | Codespaces URL, forwarded port, `/webhook/employee-assessment`, workflow active |
| Employee always fails verification | Employee ID/name values, database data, exact matching logic |
| Pinecone upsert = 0 | API key, `Api-Key` header, index host, index dimension, HTTP node configuration |
| `undefined status` error | Inspect the preceding Pinecone/API response; disable `Never Error` temporarily |
| Dimension mismatch | Pinecone index must match the embedding dimension; current setup is 1536 |
| Empty `content-library` | Re-run ingestion and inspect the Pinecone upsert response |
| No RAG results | Confirm vectors exist in `content-library` and retrieval uses the same namespace |
| OpenAI error | Confirm API key, project access, model availability, and embedding configuration |
| Slack notification fails | App permissions, token/webhook, channel access |
| Codespaces URL changes | Update `N8N_WEBHOOK_URL` when the forwarded URL changes |

---

## 37. License / Internal Use

Add the appropriate project/company/course license or usage terms here if required.

---

## 38. Project Status

This README documents the configured SkillPath architecture and the operational setup for:

```text
Gradio
n8n
OpenAI
Pinecone
PostgreSQL
Slack
GitHub Codespaces
```

Use the actual project files and imported n8n workflow as the source of truth for implementation-specific node settings and database schema details.
