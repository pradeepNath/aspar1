CREATE TABLE users (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR(100)        NOT NULL,
    email      VARCHAR(150) UNIQUE NOT NULL,
    password   VARCHAR(255)        NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE student_profiles (
    id                INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id           INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dream_career      VARCHAR(150) NOT NULL,
    passion_statement TEXT,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_profiles_updated_at
BEFORE UPDATE ON student_profiles
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TABLE academic_results (
    id          SERIAL PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject     VARCHAR(150) NOT NULL,
    grade       VARCHAR(10),
    gpa         FLOAT,
    source      VARCHAR(20) NOT NULL DEFAULT 'manual'
                CHECK (source IN ('manual','ocr_upload')),
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE skill_levels (
    id            SERIAL PRIMARY KEY,
    user_id       INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    career        VARCHAR(150) NOT NULL,
    current_level INT NOT NULL DEFAULT 1 CHECK (current_level BETWEEN 1 AND 5),
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, career)
);

CREATE TABLE skill_tree (
    id             SERIAL PRIMARY KEY,
    user_id        INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    career         VARCHAR(150) NOT NULL,
    level          INT NOT NULL CHECK (level BETWEEN 1 AND 5),
    category       VARCHAR(150) NOT NULL,
    skill_name     VARCHAR(150) NOT NULL,
    sequence_order INT NOT NULL,
    status         VARCHAR(10) NOT NULL DEFAULT 'locked'
                   CHECK (status IN ('locked','unlocked','learned'))
);

CREATE INDEX idx_skill_tree_user ON skill_tree(user_id, career, level, sequence_order);

CREATE TABLE quiz_sessions (
    id             SERIAL PRIMARY KEY,
    user_id        INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    test_type      VARCHAR(15) NOT NULL
                   CHECK (test_type IN ('placement','level_up','skill_test')),
    level          INT NOT NULL CHECK (level BETWEEN 1 AND 5),
    skill_id       INT REFERENCES skill_tree(id) ON DELETE SET NULL,
    attempt_number INT NOT NULL DEFAULT 1,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE quiz_questions (
    id              SERIAL PRIMARY KEY,
    session_id      INT NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    question_text   TEXT NOT NULL,
    question_type   VARCHAR(10) NOT NULL CHECK (question_type IN ('mcq','theory')),
    options         JSONB,
    correct_answer  VARCHAR(255),
    question_number INT NOT NULL
);

CREATE TABLE quiz_answers (
    id          SERIAL PRIMARY KEY,
    session_id  INT NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    question_id INT NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
    answer_text TEXT
);

CREATE TABLE quiz_scores (
    id              SERIAL PRIMARY KEY,
    session_id      INT NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    question_id     INT NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,
    score_out_of_10 FLOAT NOT NULL,
    feedback        TEXT
);

CREATE TABLE roadmaps (
    id           SERIAL PRIMARY KEY,
    user_id      INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    roadmap_text TEXT NOT NULL,
    version      INT NOT NULL DEFAULT 1,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE progress_log (
    id             SERIAL PRIMARY KEY,
    user_id        INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    attempt_number INT NOT NULL,
    total_score    FLOAT NOT NULL,
    previous_score FLOAT,
    level          INT NOT NULL CHECK (level BETWEEN 1 AND 5),
    status         VARCHAR(50) NOT NULL,
    notes          TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE learned_skills (
    id         SERIAL PRIMARY KEY,
    user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    skill_id   INT NOT NULL REFERENCES skill_tree(id) ON DELETE CASCADE,
    learned_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, skill_id)
);

CREATE TABLE last_attempt_log (
    id              SERIAL PRIMARY KEY,
    user_id         INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    skill_id        INT NOT NULL REFERENCES skill_tree(id) ON DELETE CASCADE,
    last_attempt_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, skill_id)
);
ALTER TABLE quiz_scores
ADD CONSTRAINT uq_quiz_scores_session_question
UNIQUE (session_id, question_id);

-- Add skill_type to skill_tree
ALTER TABLE skill_tree ADD COLUMN IF NOT EXISTS skill_type VARCHAR(20) DEFAULT 'mixed';

-- Add skill_category (core vs adaptive)
ALTER TABLE skill_tree ADD COLUMN IF NOT EXISTS skill_category VARCHAR(10) DEFAULT 'core';

-- Skill dependencies table
CREATE TABLE IF NOT EXISTS skill_dependencies (
    id                   SERIAL PRIMARY KEY,
    skill_id             INT NOT NULL REFERENCES skill_tree(id) ON DELETE CASCADE,
    prerequisite_skill_id INT NOT NULL REFERENCES skill_tree(id) ON DELETE CASCADE,
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (skill_id, prerequisite_skill_id)
);

-- Question concept mapping
ALTER TABLE quiz_questions ADD COLUMN IF NOT EXISTS concept VARCHAR(150);

-- Skill gap analysis
CREATE TABLE IF NOT EXISTS skill_gap_analysis (
    id               SERIAL PRIMARY KEY,
    user_id          INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    skill_id         INT NOT NULL REFERENCES skill_tree(id) ON DELETE CASCADE,
    session_id       INT NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    skill_type       VARCHAR(20),
    overall_score    FLOAT,
    weak_concepts    TEXT,
    strong_concepts  TEXT,
    score_trend      VARCHAR(15),
    score_delta      FLOAT,
    attempt_number   INT DEFAULT 1,
    blocks_next      BOOLEAN DEFAULT FALSE,
    analyzed_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, skill_id, session_id)
);

-- Adaptive subskills tracking
CREATE TABLE IF NOT EXISTS adaptive_skills (
    id              SERIAL PRIMARY KEY,
    user_id         INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    parent_skill_id INT NOT NULL REFERENCES skill_tree(id) ON DELETE CASCADE,
    skill_name      VARCHAR(150) NOT NULL,
    skill_type      VARCHAR(20),
    reason          TEXT,
    status          VARCHAR(10) DEFAULT 'unlocked'
                    CHECK (status IN ('unlocked', 'learned')),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Career practice submissions
CREATE TABLE IF NOT EXISTS career_practice (
    id              SERIAL PRIMARY KEY,
    user_id         INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id      INT NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    level           INT NOT NULL,
    task_text       TEXT NOT NULL,
    submission_text TEXT,
    evaluation      TEXT,
    overall_score   FLOAT,
    submitted_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_last_attempt_user_skill'
    ) THEN
        ALTER TABLE last_attempt_log 
        ADD CONSTRAINT uq_last_attempt_user_skill UNIQUE (user_id, skill_id);
    END IF;
END $$;

-- One standardized core tree per career
CREATE TABLE IF NOT EXISTS career_core_trees (
    id SERIAL PRIMARY KEY,
    career_name VARCHAR(150) NOT NULL,
    normalized_career VARCHAR(150) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS career_core_skills (
    id SERIAL PRIMARY KEY,
    core_tree_id INT NOT NULL
        REFERENCES career_core_trees(id) ON DELETE CASCADE,
    level INT NOT NULL CHECK (level BETWEEN 1 AND 5),
    category VARCHAR(150) NOT NULL,
    skill_name VARCHAR(150) NOT NULL,
    sequence_order INT NOT NULL,
    skill_type VARCHAR(20) NOT NULL DEFAULT 'mixed',
    UNIQUE (core_tree_id, level, sequence_order),
    UNIQUE (core_tree_id, skill_name)
);

-- Existing skill_tree becomes the learner's progress copy of a core skill.
ALTER TABLE skill_tree
ADD COLUMN IF NOT EXISTS core_skill_id INT
REFERENCES career_core_skills(id) ON DELETE SET NULL;

-- Existing adaptive_skills becomes learner-specific personalized subskills.
ALTER TABLE adaptive_skills
ADD COLUMN IF NOT EXISTS concept VARCHAR(150);

ALTER TABLE quiz_sessions
ADD COLUMN IF NOT EXISTS adaptive_skill_id INT
REFERENCES adaptive_skills(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_adaptive_skill_concept
ON adaptive_skills (user_id, parent_skill_id, concept)
WHERE concept IS NOT NULL;