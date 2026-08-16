<div align="center">

# ASPAR
### AI-Based Student Performance Analysis and Roadmap System

**ASPAR tells students exactly what to learn, level by level, to reach their dream career.**
It tests where you are, builds your personal skill tree, and adapts your roadmap based on real performance — not guesswork.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)](https://react.dev/)
[![Flask](https://img.shields.io/badge/Flask-REST%20API-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![MySQL](https://img.shields.io/badge/MySQL-13%20tables-4479A1?logo=mysql&logoColor=white)](https://www.mysql.com/)

</div>

---

## Table of Contents

- [What is ASPAR?](#what-is-aspar)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Getting Started](#getting-started)
- [Project Structure](#project-structure)
- [Database Schema](#database-schema-13-tables)
- [Core Business Rules](#core-business-rules)
- [API Endpoints](#api-endpoints)
- [Student Journey](#student-journey)
- [Team](#team)
- [License](#license)

---

## What is ASPAR?

Most learning platforms recommend content. ASPAR does something different — it acts as an AI mentor that:

1. **Assesses** where you currently stand through an AI-generated placement test
2. **Builds** a personalized 5-level skill tree for your exact dream career
3. **Guides** you with a roadmap focused on your current skill — what to learn, not how
4. **Tests** your mastery before letting you progress to the next skill
5. **Adapts** the entire roadmap based on your real test performance

The actual learning happens outside the platform — YouTube, books, documentation, courses. ASPAR's job is to track, test, and guide, not to replace the resources students already use.

---

## Features

| Feature | Description |
|---|---|
| 🎯 **Placement Test** | AI-generated assessment across Levels 1–3 to find your starting point |
| 🌳 **Skill Tree** | A full 5-level, categorized skill tree generated uniquely for your career |
| 🗺️ **Adaptive Roadmap** | Per-skill guidance: why this skill matters, what to focus on, what resource types to seek |
| 📝 **Skill Tests** | Prove mastery of each skill (≥80%) before the next one unlocks |
| 🚀 **Level-Up Tests** | Complete a level to advance — the roadmap regenerates automatically |
| 📊 **Progress Tracking** | Score-history graph, learned-skills list, current level badge |
| 📄 **OCR Upload** | Upload a photo or PDF of your transcript — AI extracts your grades automatically |
| 🔄 **Career Change** | After repeated struggle, AI suggests three data-driven alternative careers |
| 🔒 **Secure Auth** | JWT authentication, bcrypt password hashing, protected routes |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | React 18 · Vite · React Router · Recharts |
| **Backend** | Python Flask (stateless REST API) |
| **Database** | MySQL via PyMySQL (13 tables) |
| **Auth** | JWT (PyJWT) + bcrypt |
| **AI Engine** | Groq API — Llama 3.3 70B (9 independent functions) |
| **OCR** | Tesseract + Pillow + PyMuPDF (images & multi-page PDFs) |

---

## Architecture

```
┌──────────────────────┐       HTTPS / REST (JWT)      ┌──────────────────────┐
│    React Frontend    │ ◄───────────────────────────► │   Flask Backend API  │
│      (Vite SPA)      │                                │  (app.py + routes/)  │
└──────────────────────┘                                └──────────┬───────────┘
                                                                    │
                                          ┌─────────────────────────┼────────────────┐
                                          │                         │                │
                                   ┌──────▼──────┐       ┌─────────▼────────┐  ┌────▼──────────┐
                                   │    MySQL    │       │     Groq API     │  │   Tesseract    │
                                   │ (13 tables) │       │   (9 AI funcs)   │  │      OCR       │
                                   └─────────────┘       └──────────────────┘  └────────────────┘
```

### The 9 AI functions

Each function below is an independent, separately testable call — nothing is bundled into a single monolithic prompt.

| # | Function | Purpose |
|---|---|---|
| 1 | `generate_placement_questions` | Generates 8 questions spanning Levels 1–3 |
| 2 | `decide_placement_level` | Makes a holistic decision on the student's starting level (1–3) |
| 3 | `generate_skill_tree` | Builds the full 5-level skill tree in one call |
| 4 | `generate_test_questions` | Produces skill-test or level-up-test questions |
| 5 | `grade_answers` | Scores each answer and detects knowledge gaps |
| 6 | `generate_roadmap` | Creates roadmap guidance for the current skill (what + resource types) |
| 7 | `evaluate_progress` | Decides `level_up` / `retain` / `ease_roadmap` / `flag_unfit` |
| 8 | `suggest_alternative_careers` | Recommends three data-driven career alternatives |
| 9 | `structure_ocr_text` | Converts raw OCR output into clean subject/grade/GPA rows |

---

## Getting Started

### Prerequisites

- Python 3.12+
- Node.js 18+
- XAMPP (for MySQL)
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed on your system
- A free [Groq API key](https://console.groq.com)

### 1. Clone the repository

```bash
git clone https://github.com/pradeepNath/ASPAR.git
cd aspar
```

### 2. Backend setup

```bash
cd backend

# Create and activate a virtual environment
python -m venv venv

# Windows
venv\Scripts\activate
# Mac / Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

**Configure environment variables**

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

```env
# Database (XAMPP defaults)
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=
DB_NAME=aspar_db

# JWT — generate a strong secret with:
# python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=your_long_random_secret_here
JWT_EXPIRES_HOURS=24

# Groq API (free at console.groq.com)
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile

# Tesseract (Windows only — leave blank on Mac/Linux if it's on PATH)
TESSERACT_CMD=
```

**Create the database** (start XAMPP MySQL first)

```bash
mysql -u root < schema.sql
```

Or import `schema.sql` through phpMyAdmin's Import tab.

**Start the backend**

```bash
python app.py
```

Visit `http://localhost:5000/api/health` — you should see:

```json
{ "status": "ok", "database": "connected" }
```

### 3. Frontend setup

```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:5173`

> The Vite dev server automatically proxies all `/api/*` requests to Flask on port 5000 — no CORS configuration needed during development.

---

## Project Structure

```
aspar/
├── backend/
│   ├── app.py                     # Flask entry point, blueprint registration
│   ├── schema.sql                 # Full MySQL schema (13 tables)
│   ├── requirements.txt
│   ├── .env.example
│   ├── config/
│   │   └── db.py                  # PyMySQL connection helper
│   ├── routes/
│   │   ├── auth.py                # POST /register, /login
│   │   ├── profile.py             # Dream career, manual academics
│   │   ├── academic_upload.py     # OCR upload → AI structuring → confirm
│   │   ├── quiz.py                # Start quiz, submit answers (all 3 test types)
│   │   ├── grading.py             # AI grading + placement level decision
│   │   ├── skills.py              # Generate tree, fetch tree, complete skill
│   │   ├── roadmap.py             # Generate + fetch roadmap
│   │   ├── progress.py            # Level-up evaluation, progress log
│   │   └── career.py              # Career suggestions + career switch
│   ├── services/
│   │   ├── groq_service.py        # All 9 AI functions (only file that calls Groq)
│   │   ├── ocr_service.py         # Image + multi-page PDF text extraction
│   │   └── fifo_service.py        # Quiz session FIFO cleanup
│   └── utils/
│       └── auth.py                # JWT generation + @token_required decorator
│
└── frontend/
    └── src/
        ├── pages/
        │   ├── Landing.jsx         # Public landing page
        │   ├── Register.jsx        # Account creation
        │   ├── Login.jsx           # Sign in + onboarding state detection
        │   ├── DreamSetup.jsx      # Onboarding step 1: dream career
        │   ├── AcademicResults.jsx # Onboarding step 2: grades (+ add-more)
        │   ├── PlacementTest.jsx   # Onboarding step 3: placement test
        │   ├── Dashboard.jsx       # Main hub: roadmap + skills + level-up
        │   ├── Quiz.jsx            # Shared quiz engine (skill + level-up)
        │   ├── Grading.jsx         # Results display after any test
        │   ├── SkillTree.jsx       # Full visual skill tree
        │   ├── Progress.jsx        # Score graph + learned skills list
        │   └── CareerChange.jsx    # Alternative career suggestion flow
        ├── components/
        │   ├── Navbar.jsx          # Persistent nav (authenticated pages)
        │   └── ProtectedRoute.jsx  # JWT route guard
        └── utils/
            └── api.js              # Axios instance with JWT interceptor + auto-logout
```

---

## Database Schema (13 tables)

| Domain | Tables |
|---|---|
| Identity | `users` |
| Profile | `student_profiles`, `academic_results` |
| Skill System | `skill_levels`, `skill_tree`, `learned_skills`, `last_attempt_log` |
| Quiz Engine | `quiz_sessions`, `quiz_questions`, `quiz_answers`, `quiz_scores` |
| Roadmap & Progress | `roadmaps`, `progress_log` |

**Key design decisions**

- **Append-only academics** — every upload adds new rows; nothing is ever overwritten
- **Sequential skill unlocking** — enforced by `sequence_order` + `status` in `skill_tree`
- **FIFO session cleanup** — the last 2 level-up sessions and last 1 skill session are kept (questions/answers only); scores and progress records are permanent
- **4-hour cooldown** — `last_attempt_log` tracks failed skill-test retries

---

## Core Business Rules

- **Roadmap, not recommendation** — the AI states *what* to learn and *what kind* of resource to look for. It never gives specific links, course names, or step-by-step instructions.
- **Sequential unlocking** — one skill at a time, in order, within the student's current level only.
- **80% threshold** — required to pass both skill tests and level-up tests. Placement itself uses pure AI holistic judgment rather than a fixed score cutoff.
- **Career change is always opt-in** — only offered after three consecutive failed level-up attempts (score < 80%), and never forced on the student.

---

## API Endpoints

| Method | Endpoint | Auth |
|---|---|---|
| POST | `/api/auth/register` | — |
| POST | `/api/auth/login` | — |
| POST | `/api/profile/dream` | ✓ |
| POST | `/api/academics/manual` | ✓ |
| POST | `/api/academics/upload` | ✓ |
| POST | `/api/academics/upload/confirm` | ✓ |
| GET | `/api/academics` | ✓ |
| POST | `/api/quiz/start` | ✓ |
| POST | `/api/quiz/submit` | ✓ |
| POST | `/api/grading/run` | ✓ |
| GET | `/api/skills/tree` | ✓ |
| POST | `/api/skills/generate` | ✓ |
| POST | `/api/skills/complete` | ✓ |
| GET | `/api/roadmap` | ✓ |
| POST | `/api/roadmap/generate` | ✓ |
| POST | `/api/progress/evaluate` | ✓ |
| GET | `/api/progress/log` | ✓ |
| POST | `/api/career/suggest` | ✓ |
| POST | `/api/career/switch` | ✓ |

All `✓` routes require an `Authorization: Bearer <token>` header.

---

## Student Journey

```
                                                Register / Login
                                                      │
                                                      ▼
                     Set Dream Career  →  Add Academic Results (manual / OCR upload / skip)
                                                      │
                                                      ▼
            Placement Test  →  AI decides starting level  →  Skill tree generated  →  Roadmap created
                                                      │
                                                      ▼
                                 ┌─────────────────────────────────────────┐
                                 │                MAIN LOOP                │
                                 │                                         │
                                 │           Study independently           │
                                 │                    │                    │
                                 │                    ▼                    │
                                 │        Skill Test  →  ≥80% pass         │
                                 │           (next skill unlocks)          │
                                 │                    │                    │
                                 │                    ▼                    │
                                 │      All skills in level learned        │
                                 │                    │                    │
                                 │                    ▼                    │
                                 │      Level-Up Test  →  ≥80% pass        │
                                 │        (advance to next level)          │
                                 │                    │                    │
                                 │                    ▼                    │
                                 │          Roadmap regenerated            │
                                 │                                         │
                                 │          [3 consecutive fails]          │
                                 │                    │                    │
                                 └────────────────────▼────────────────────┘
                                          Career Change (opt-in)
                                                      │
                                                      ▼
                                       AI suggests 3 alternative careers
   ```

---

## Team

**Final Year Project — Bachelor in Computer Science Education**
**Far Western University, Faculty of Education**
**Course: CS. Ed 477 — Project Work (Seventh Semester)**

| Member | Role |
|---|---|
| [Your Name] | Project Leader — Architecture, Full-Stack Development, AI Integration |
| [Member 2] | Documentation — Introduction & Front Matter |
| [Member 3] | Documentation — Background Study & Literature Review |
| [Member 4] | Documentation — System Analysis & Diagrams |
| [Member 5] | Documentation — System Design & Conclusion |

---

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

**ASPAR — Built for FWU CS Ed 477 Final Year Project**
*Far Western University · Faculty of Education · 2024/2025*

</div>