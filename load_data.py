"""Load the employee spreadsheet (+ optional content library) into PostgreSQL.
Usage: DATABASE_URL=postgresql://user:pw@host/db python load_data.py [employee_csv]
Employee CSV columns: emp_id, emp_name, emp_dept, emp_role, manager_input,
                      last_review_date (DD-Mon-YYYY), years_of_exp, current_domain, Rating
Optional content_library.csv/.xlsx: skill,topic,url,difficulty,duration_hours,format,prereq_skills (';' separated)"""
import os, sys, pandas as pd, psycopg2
from psycopg2.extras import execute_values

EMP_FILE = sys.argv[1] if len(sys.argv) > 1 else "employee_data.csv"

def load_employees(path):
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str).fillna("")
    df.columns = [c.strip().lower() for c in df.columns]
    missing = {"emp_id","emp_name","emp_dept","emp_role","manager_input","last_review_date",
               "years_of_exp","current_domain","rating"} - set(df.columns)
    if missing: sys.exit(f"Missing columns: {missing}")
    for c in df.columns: df[c] = df[c].str.strip()
    df["emp_id"] = df["emp_id"].str.upper()
    if df["emp_id"].duplicated().any(): sys.exit("Duplicate emp_id values found")
    df["years_of_exp"] = pd.to_numeric(df["years_of_exp"])
    df["review_date"] = pd.to_datetime(df["last_review_date"], format="%d-%b-%Y").dt.date
    df["rating"] = df["rating"].str.lower()
    bad = set(df["rating"]) - {"exceed", "average", "need improvement"}
    if bad: sys.exit(f"Unexpected Rating values: {bad}")
    df["focus_skill"] = df["manager_input"].str.extract(r"(?i)build proficiency in (.+?) through")[0]
    return df

def read_optional(name):
    for ext, fn in (("csv", pd.read_csv), ("xlsx", pd.read_excel)):
        if os.path.exists(f"{name}.{ext}"): return fn(f"{name}.{ext}").fillna("")

df = load_employees(EMP_FILE)
conn = psycopg2.connect(os.environ["DATABASE_URL"]); cur = conn.cursor()

execute_values(cur, """INSERT INTO employees (employee_id,full_name,department,role,current_domain,years_of_exp) VALUES %s
  ON CONFLICT (employee_id) DO UPDATE SET full_name=EXCLUDED.full_name, department=EXCLUDED.department,
  role=EXCLUDED.role, current_domain=EXCLUDED.current_domain, years_of_exp=EXCLUDED.years_of_exp""",
  [(r.emp_id, r.emp_name, r.emp_dept, r.emp_role, r.current_domain, r.years_of_exp) for r in df.itertuples()])

execute_values(cur, """INSERT INTO manager_inputs (employee_id,manager_input,focus_skill,performance_rating,review_date) VALUES %s
  ON CONFLICT (employee_id, review_date) DO UPDATE SET manager_input=EXCLUDED.manager_input,
  focus_skill=EXCLUDED.focus_skill, performance_rating=EXCLUDED.performance_rating""",
  [(r.emp_id, r.manager_input, r.focus_skill if isinstance(r.focus_skill, str) else None, r.rating, r.review_date)
   for r in df.itertuples()])

ct = read_optional("content_library")
if ct is not None and "content_id" in ct.columns:   # richer library format: used directly by the assessment workflow, not stored in Postgres
    print("content_library.csv uses the content_id format -> skipped (assessment workflow reads it from the form payload)"); ct = None
if ct is not None:
    ct["prereq_skills"] = ct["prereq_skills"].apply(lambda s: [x.strip() for x in str(s).split(";") if x.strip()])
    ct["duration_hours"] = pd.to_numeric(ct["duration_hours"], errors="coerce")
    execute_values(cur, """INSERT INTO content_library (skill,topic,url,difficulty,duration_hours,format,prereq_skills) VALUES %s
      ON CONFLICT (url) DO NOTHING""",
      [tuple(r[c] for c in ["skill","topic","url","difficulty","duration_hours","format","prereq_skills"]) for _, r in ct.iterrows()])
conn.commit()
print(f"Loaded {len(df)} employees, {len(df)} manager inputs" + (f", {len(ct)} content items" if ct is not None else "; no content loaded into Postgres"))
print("Next: SELECT * FROM v_skill_content_coverage;  -- skills your content library must cover")
