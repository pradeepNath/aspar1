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
