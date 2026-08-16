-- ============================================================
-- ASPAR Database Schema
-- Run this once against a fresh MySQL database (XAMPP):
--   mysql -u root -p < schema.sql
-- or import via phpMyAdmin.
-- ============================================================

CREATE DATABASE IF NOT EXISTS aspar_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE aspar_db;

-- ============================================================
-- 1. users
-- ============================================================
CREATE TABLE users (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100)        NOT NULL,
    email       VARCHAR(150) NOT NULL UNIQUE,
    password    VARCHAR(255) NOT NULL,   -- bcrypt hash
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ============================================================
-- 2. student_profiles
-- ============================================================
CREATE TABLE student_profiles (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    user_id             INT NOT NULL,
    dream_career        VARCHAR(150) NOT NULL,
    passion_statement   TEXT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_profile_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;

-- ============================================================
-- 3. academic_results
-- ============================================================
CREATE TABLE academic_results (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    subject     VARCHAR(150) NOT NULL,
    grade       VARCHAR(10),
    gpa         FLOAT,
    source      ENUM('manual', 'ocr_upload') NOT NULL DEFAULT 'manual',
    uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_academics_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;

-- ============================================================
-- 4. skill_levels  (one row per user per career)
-- ============================================================
CREATE TABLE skill_levels (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    career          VARCHAR(150) NOT NULL,
    current_level   INT NOT NULL DEFAULT 1,   -- 1-5
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_levels_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,
    CONSTRAINT chk_level_range CHECK (current_level BETWEEN 1 AND 5),
    UNIQUE KEY uq_user_career (user_id, career)
) ENGINE=InnoDB;

-- ============================================================
-- 5. skill_tree
-- ============================================================
CREATE TABLE skill_tree (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    career          VARCHAR(150) NOT NULL,
    level           INT NOT NULL,             -- 1-5
    category        VARCHAR(150) NOT NULL,    -- e.g. "Data Structures"
    skill_name      VARCHAR(150) NOT NULL,    -- e.g. "Linked Lists"
    sequence_order  INT NOT NULL,             -- order within the level
    status          ENUM('locked', 'unlocked', 'learned') NOT NULL DEFAULT 'locked',
    CONSTRAINT fk_tree_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,
    CONSTRAINT chk_tree_level_range CHECK (level BETWEEN 1 AND 5),
    INDEX idx_tree_user_career_level (user_id, career, level, sequence_order)
) ENGINE=InnoDB;

-- ============================================================
-- 6. quiz_sessions
-- ============================================================
CREATE TABLE quiz_sessions (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    test_type       ENUM('placement', 'level_up', 'skill_test') NOT NULL,
    level           INT NOT NULL,
    skill_id        INT NULL,                 -- only for skill_test
    attempt_number  INT NOT NULL DEFAULT 1,   -- shared with progress_log for level_up
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_session_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_session_skill
        FOREIGN KEY (skill_id) REFERENCES skill_tree(id)
        ON DELETE SET NULL,
    CONSTRAINT chk_session_level_range CHECK (level BETWEEN 1 AND 5)
) ENGINE=InnoDB;

-- ============================================================
-- 7. quiz_questions
-- ============================================================
CREATE TABLE quiz_questions (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    session_id      INT NOT NULL,
    question_text   TEXT NOT NULL,
    question_type   ENUM('mcq', 'theory') NOT NULL,
    options         JSON NULL,        -- list of choices, for MCQ only
    correct_answer  VARCHAR(255) NULL, -- correct option, for MCQ only
    question_number INT NOT NULL,
    CONSTRAINT fk_question_session
        FOREIGN KEY (session_id) REFERENCES quiz_sessions(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;

-- ============================================================
-- 8. quiz_answers
-- ============================================================
CREATE TABLE quiz_answers (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    session_id      INT NOT NULL,
    question_id     INT NOT NULL,
    answer_text     TEXT,            -- written answer OR selected MCQ option
    CONSTRAINT fk_answer_session
        FOREIGN KEY (session_id) REFERENCES quiz_sessions(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_answer_question
        FOREIGN KEY (question_id) REFERENCES quiz_questions(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;

-- ============================================================
-- 9. quiz_scores
-- ============================================================
CREATE TABLE quiz_scores (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    session_id      INT NOT NULL,
    question_id     INT NOT NULL,
    score_out_of_10 FLOAT NOT NULL,
    feedback        TEXT,
    CONSTRAINT fk_score_session
        FOREIGN KEY (session_id) REFERENCES quiz_sessions(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_score_question
        FOREIGN KEY (question_id) REFERENCES quiz_questions(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;

-- ============================================================
-- 10. roadmaps
-- ============================================================
CREATE TABLE roadmaps (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    roadmap_text    TEXT NOT NULL,
    version         INT NOT NULL DEFAULT 1,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_roadmap_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;

-- ============================================================
-- 11. progress_log
-- ============================================================
CREATE TABLE progress_log (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    attempt_number  INT NOT NULL,
    total_score     FLOAT NOT NULL,
    previous_score  FLOAT NULL,
    level           INT NOT NULL,
    status          VARCHAR(50) NOT NULL, -- 'leveled_up', 'retained', 'eased', etc.
    notes           TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_progress_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,
    CONSTRAINT chk_progress_level_range CHECK (level BETWEEN 1 AND 5)
) ENGINE=InnoDB;

-- ============================================================
-- 12. learned_skills
-- ============================================================
CREATE TABLE learned_skills (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    skill_id    INT NOT NULL,
    learned_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_learned_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_learned_skill
        FOREIGN KEY (skill_id) REFERENCES skill_tree(id)
        ON DELETE CASCADE,
    UNIQUE KEY uq_user_skill (user_id, skill_id)
) ENGINE=InnoDB;

-- ============================================================
-- 13. last_attempt_log  (4-hour skill-test retry cooldown)
-- ============================================================
CREATE TABLE last_attempt_log (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    skill_id        INT NOT NULL,
    last_attempt_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_attempt_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_attempt_skill
        FOREIGN KEY (skill_id) REFERENCES skill_tree(id)
        ON DELETE CASCADE,
    UNIQUE KEY uq_user_skill_attempt (user_id, skill_id)
) ENGINE=InnoDB;
