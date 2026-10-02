"""Load the employee spreadsheet into PostgreSQL.
Usage: DATABASE_URL=postgresql://user:pw@host/db python load_data.py [employee_csv]
Employee CSV columns: emp_id, emp_name, emp_dept, emp_role, manager_input,
                      last_review_date (DD-Mon-YYYY), years_of_exp, current_domain, Rating
"""
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
    df["last_review_date"] = pd.to_datetime(df["last_review_date"], format="%d-%b-%Y").dt.date
    df["rating"] = df["rating"].str.lower()
    
    bad = set(df["rating"]) - {"exceed", "average", "need improvement"}
    if bad: sys.exit(f"Unexpected Rating values: {bad}")
    return df

df = load_employees(EMP_FILE)
conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

# Insert only into the updated employees table mapping to your DDL
query = """INSERT INTO employees (
    emp_id, emp_name, emp_dept, emp_role, manager_input, 
    last_review_date, years_of_exp, current_domain, Rating
) VALUES %s
ON CONFLICT (emp_id) DO UPDATE SET 
    emp_name=EXCLUDED.emp_name, 
    emp_dept=EXCLUDED.emp_dept,
    emp_role=EXCLUDED.emp_role, 
    manager_input=EXCLUDED.manager_input,
    last_review_date=EXCLUDED.last_review_date,
    years_of_exp=EXCLUDED.years_of_exp,
    current_domain=EXCLUDED.current_domain,
    Rating=EXCLUDED.Rating"""

# Note: columns are lowercased by pandas in the load function, so we access them as r.emp_name, r.rating, etc.
data_tuples = [(
    r.emp_id, r.emp_name, r.emp_dept, r.emp_role, r.manager_input, 
    r.last_review_date, r.years_of_exp, r.current_domain, r.rating
) for r in df.itertuples()]

execute_values(cur, query, data_tuples)

conn.commit()
print(f"Loaded {len(df)} employees into the database successfully.")
