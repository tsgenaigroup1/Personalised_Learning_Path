-- Learning Path Generator: PostgreSQL schema (run once, after your existing `employees` table exists)
-- Postgres = transactional source of truth (paths, progress, badges, certificates, feedback).
-- Pinecone = RAG layer (content library + assessments, paths, progress and feedback as embeddings).

ALTER TABLE employees ADD COLUMN IF NOT EXISTS slack_user_id text;
CREATE UNIQUE INDEX IF NOT EXISTS employees_slack_user_id_uq ON employees (slack_user_id) WHERE slack_user_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS learning_paths (
  path_id               bigserial PRIMARY KEY,
  emp_id                text        NOT NULL,                 -- stored upper-case
  status                text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed','superseded','abandoned')),
  version               int         NOT NULL DEFAULT 1,
  parent_path_id        bigint      REFERENCES learning_paths(path_id),
  target_skill          text,
  career_goal           text,
  current_skill         text,
  learning_style        text,
  target_proficiency    text,
  experience_years      numeric,
  experience_band       text,
  weekly_hours          numeric,
  summary               text,
  skill_gap_analysis    text,
  coverage_note         text,
  personalization_notes text,
  assessment            jsonb,                                -- full form answers + profile snapshot
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  completed_at          timestamptz
);
-- at most one active (incomplete) path per employee
CREATE UNIQUE INDEX IF NOT EXISTS learning_paths_one_active ON learning_paths (emp_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS learning_paths_emp ON learning_paths (emp_id, created_at DESC);

CREATE TABLE IF NOT EXISTS path_items (
  path_id      bigint  NOT NULL REFERENCES learning_paths(path_id) ON DELETE CASCADE,
  content_id   text    NOT NULL,
  week_no      int     NOT NULL,          -- start week; 0 = completed in a previous version of the path
  end_week     int,                       -- long items span several weeks
  seq          int     NOT NULL,
  skill        text, topic text, level text, format text,
  hours        numeric NOT NULL DEFAULT 0,
  provider     text, cost text, url text, rationale text,
  status       text    NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','completed')),
  completed_at timestamptz,
  PRIMARY KEY (path_id, content_id)
);

CREATE TABLE IF NOT EXISTS awards (
  path_id    bigint NOT NULL REFERENCES learning_paths(path_id) ON DELETE CASCADE,
  emp_id     text   NOT NULL,
  award      text   NOT NULL CHECK (award IN ('bronze','silver','gold','certificate')),
  cert_id    text   UNIQUE,
  awarded_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (path_id, award)
);

CREATE TABLE IF NOT EXISTS feedback (
  id         bigserial PRIMARY KEY,
  emp_id     text NOT NULL,
  path_id    bigint REFERENCES learning_paths(path_id) ON DELETE SET NULL,
  source     text NOT NULL DEFAULT 'app',     -- app | slack
  rating     int  CHECK (rating BETWEEN 1 AND 5),
  comment    text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS feedback_emp ON feedback (emp_id, created_at DESC);

-- Handy reporting view for the engagement / completion metrics in the project brief
CREATE OR REPLACE VIEW v_learning_metrics AS
SELECT p.path_id, p.emp_id, p.target_skill, p.status, p.created_at, p.completed_at,
       count(i.*)                                             AS items,
       count(i.*) FILTER (WHERE i.status = 'completed')       AS items_completed,
       round(100.0 * COALESCE(sum(i.hours) FILTER (WHERE i.status = 'completed'), 0) / NULLIF(sum(i.hours), 0), 1) AS progress_pct,
       (SELECT round(avg(f.rating), 2) FROM feedback f WHERE f.path_id = p.path_id) AS avg_rating
FROM learning_paths p LEFT JOIN path_items i ON i.path_id = p.path_id
GROUP BY p.path_id;
