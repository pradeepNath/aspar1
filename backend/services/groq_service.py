"""
services/groq_service.py
-------------------------
ALL calls to the Groq LLM live in this file, and ONLY in this file.
No other module should import the groq client directly - routes call
these functions, and these functions are the only place that talk to
the AI.

Design rules (from the architecture doc, Section 8):
  - Each of the 8 functions below is its OWN prompt + OWN API call.
  - Never combine two reasoning steps into one call, even if it would
    "save a request" - this is intentional, so each step is
    independently testable and explainable for the project defense.
  - The AI is asked to return STRICT JSON for anything structured
    (questions, skill tree, grading, etc). We wrap parsing in
    try/except and retry once before failing - this protects the app
    from an occasional malformed response without crashing the request.

Every function can be called directly with dummy/sample inputs (e.g. in
a Python shell or a quick test script) to see exactly what it returns -
useful for debugging each AI step in isolation before wiring it into a
route.
"""

import os
import json
from groq import Groq

# A single shared client, built once when this module is imported.
# The API key is read from .env (loaded by app.py via load_dotenv()).
_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Default model - can be overridden via .env (GROQ_MODEL=...) without
# touching code, in case the supported Llama model name changes.
_MODEL = os.getenv("GROQ_MODEL")


# ============================================================
# Internal helper - NOT one of the 8 public functions.
# Every public function below funnels through this, so retry /
# JSON-parsing / error-handling logic lives in exactly one place.
# ============================================================
def _call_groq(system_prompt, user_prompt, expect_json=True, temperature=0.4):
    """
    Send one system+user prompt pair to Groq and return the response.

    Args:
        system_prompt: instructions that set the AI's role/behaviour.
        user_prompt:   the actual task + data for this call.
        expect_json:   if True, the response is parsed as JSON. If the
                        first attempt returns invalid JSON, we retry
                        ONCE with a stricter follow-up instruction
                        before raising - this matches the "retry once
                        before failing gracefully" rule in the design doc.
        temperature:   lower = more consistent/deterministic, which is
                        what we want for grading and structured data.

    Returns:
        A dict/list (if expect_json=True) or a plain string otherwise.

    Raises:
        ValueError if expect_json=True and both attempts fail to
        produce valid JSON. Callers (routes) should catch this and
        return a clean error response to the frontend rather than
        letting it crash the request.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    response = _client.chat.completions.create(
        model=_MODEL,
        messages=messages,
        temperature=temperature,
    )
    raw_text = response.choices[0].message.content.strip()

    if not expect_json:
        return raw_text

    parsed = _try_parse_json(raw_text)
    if parsed is not None:
        return parsed

    # --- Retry once with a stricter instruction ---
    messages.append({"role": "assistant", "content": raw_text})
    messages.append({
        "role": "user",
        "content": (
            "Your previous response was not valid JSON. "
            "Reply again with ONLY valid JSON - no markdown code fences, "
            "no explanation, no extra text before or after the JSON."
        ),
    })
    retry_response = _client.chat.completions.create(
        model=_MODEL,
        messages=messages,
        temperature=temperature,
    )
    retry_text = retry_response.choices[0].message.content.strip()

    parsed = _try_parse_json(retry_text)
    if parsed is not None:
        return parsed

    raise ValueError(
        "Groq did not return valid JSON after one retry. "
        f"Last raw response: {retry_text[:500]}"
    )


def _try_parse_json(text):
    """
    Try to parse `text` as JSON, stripping common wrappers the model
    sometimes adds (e.g. ```json ... ``` code fences). Returns the
    parsed object, or None if parsing fails.
    """
    cleaned = text.strip()

    # Strip ```json ... ``` or ``` ... ``` fences if present
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return None


# ============================================================
# 1. generate_placement_questions
#    Input:  dream career, academic results
#    Output: 8 MCQ/theory questions spanning Levels 1-3
# ============================================================
def generate_placement_questions(dream, academics):
    """
    Generate the one-time Placement Test (Test Type 1).

    Args:
        dream:     string, the student's dream career
                    (e.g. "Software Developer")
        academics: list of dicts, e.g.
                    [{"subject": "Math", "grade": "A", "gpa": 3.8}, ...]
                    Can be an empty list if the student skipped this step.

    Returns:
        A list of exactly 8 question dicts:
        [
          {
            "question_number": 1,
            "question_text": "...",
            "question_type": "mcq" | "theory",
            "options": ["A", "B", "C", "D"]  # only for mcq, else null
            "correct_answer": "B"            # only for mcq, else null
          },
          ...
        ]
    """
    system_prompt = (
        "You are an exam-question generator for ASPAR, a student "
        "roadmap platform. You design fair, level-appropriate "
        "placement questions. You ALWAYS respond with strict JSON only."
    )

    user_prompt = f"""
Generate a PLACEMENT TEST of exactly 8 questions for a student whose
dream career is: "{dream}".

Their academic results so far (may be empty): {json.dumps(academics)}

Rules:
- Questions must span difficulty Levels 1 to 3 only (no student starts
  above Level 3), with a mix spanning that range.
- Use a mix of "mcq" and "theory" question types.
- For "mcq" questions, include exactly 4 options and a correct_answer
  that exactly matches one of the options.
- For "theory" questions, set "options" and "correct_answer" to null.
- Base topics on the dream career and the student's academic strengths/
  weaknesses if academics are provided.

Respond with ONLY a JSON array of 8 objects, each shaped like:
{{
  "question_number": 1,
  "question_text": "...",
  "question_type": "mcq",
  "options": ["...", "...", "...", "..."],
  "correct_answer": "..."
}}
"""

    return _call_groq(system_prompt, user_prompt, expect_json=True)


# ============================================================
# 2. decide_placement_level
#    Input:  profile + placement answers/scores
#    Output: starting level (1-3) + brief reasoning
# ============================================================
def decide_placement_level(dream, academics, answers, scores):
    """
    Decide the student's STARTING LEVEL (1-3) after the placement test.

    This is a SEPARATE call from question generation/grading on purpose -
    the design doc specifies pure AI judgment here, combining BOTH test
    performance AND academic background, with no fixed percentage cutoff.

    Args:
        dream:     dream career string
        academics: list of academic result dicts (may be empty)
        answers:   list of dicts, e.g.
                    [{"question_text": "...", "student_answer": "..."}]
        scores:    list of dicts, e.g.
                    [{"question_text": "...", "score_out_of_10": 7.5}]

    Returns:
        {
          "starting_level": 1 | 2 | 3,
          "reasoning": "short explanation of why this level was chosen"
        }
    """
    system_prompt = (
        "You are an academic placement advisor for ASPAR. You decide "
        "a student's STARTING LEVEL (1, 2, or 3) for their dream career "
        "track, using holistic judgment - not a fixed percentage cutoff. "
        "You ALWAYS respond with strict JSON only."
    )

    user_prompt = f"""
Dream career: "{dream}"

Academic results (may be empty): {json.dumps(academics)}

Placement test answers: {json.dumps(answers)}

Per-question scores (out of 10): {json.dumps(scores)}

Based on BOTH the test performance AND the academic background, decide
the student's starting level for their roadmap. Levels range 1-3 only
(placement never assigns Level 4 or 5).

Respond with ONLY a JSON object shaped like:
{{
  "starting_level": 2,
  "reasoning": "A short (1-3 sentence) explanation of this decision."
}}
"""

    return _call_groq(system_prompt, user_prompt, expect_json=True)


# ============================================================
# 3. generate_skill_tree
#    Input:  profile + starting level
#    Output: full 5-level categorized skill tree (JSON)
# ============================================================
"""
REPLACE these two functions in backend/services/groq_service.py
"""

def generate_skill_tree(dream, academics, placement_level):
    """
    Generate the full 5-level skill tree WITH:
    - skill_type classification (conceptual/mathematical/practical/mixed)
    - skill_category (core — all skills in universal tree are core)
    - dependencies between skills (which skill needs which prerequisite)

    Works for ANY career — not just IT.
    AI classifies skill types based on career context.

    Returns:
        {
          "skills": [
            {
              "level": 1,
              "category": "Foundations",
              "skill_name": "Introduction to HR",
              "sequence_order": 1,
              "skill_type": "conceptual",
              "skill_category": "core"
            },
            ...
          ],
          "dependencies": [
            {"skill_name": "OOP", "depends_on": "Python Basics"},
            {"skill_name": "ML Models", "depends_on": "Linear Algebra"},
            {"skill_name": "ML Models", "depends_on": "Statistics"},
            ...
          ]
        }

    skill_type must be one of:
      conceptual  — understanding theories, principles, definitions
      mathematical — calculations, formulas, quantitative reasoning
      practical   — hands-on tasks, real-world application, procedures
      mixed       — combination of the above

    dependencies is a flat list of pairs. A skill can have multiple
    prerequisites (multiple entries with the same skill_name).
    Dependencies must only reference skills that exist in the skills list.
    """
    system_prompt = (
        "You are a curriculum designer for ASPAR. You design complete "
        "5-level skill trees for ANY career — not just tech. You classify "
        "each skill by type and define dependency relationships between skills. "
        "You ALWAYS respond with strict JSON only."
    )

    user_prompt = f"""
Dream career: "{dream}"
Academic background (may be empty): {json.dumps(academics)}
Student's placement level: {placement_level} (1-3)

Generate a COMPLETE skill tree covering ALL 5 levels for this career.

Rules:
1. Cover levels 1-5. Aim for 4-8 skills per level in 1-3 categories.
2. For EACH skill, classify skill_type as exactly one of:
   - "conceptual"   : understanding theories, principles, definitions, history
   - "mathematical" : calculations, formulas, statistics, quantitative analysis
   - "practical"    : hands-on tasks, procedures, real-world application, tools
   - "mixed"        : requires both theory AND practical/mathematical elements
   
   Base classification on the career context — not just the skill name.
   A "Patient Assessment" skill for a Nurse is "practical".
   A "Financial Ratios" skill for an Accountant is "mathematical".
   A "HR Law Fundamentals" skill for an HR Manager is "conceptual".

3. For dependencies, list pairs where one skill MUST come before another.
   - Only list dependencies within the same career path
   - A skill CAN depend on multiple prerequisites
   - Do NOT create circular dependencies
   - Only reference skill_names that exist in your skills list
   - Focus on meaningful prerequisites, not every possible relationship

Respond with ONLY a JSON object shaped like:
{{
  "skills": [
    {{
      "level": 1,
      "category": "Category Name",
      "skill_name": "Skill Name",
      "sequence_order": 1,
      "skill_type": "conceptual",
      "skill_category": "core"
    }}
  ],
  "dependencies": [
    {{"skill_name": "Advanced Skill", "depends_on": "Basic Skill"}},
    {{"skill_name": "Advanced Skill", "depends_on": "Another Basic Skill"}}
  ]
}}
"""

    return _call_groq(system_prompt, user_prompt, expect_json=True)


def generate_test_questions(dream, academics, level, test_type, skill_name=None, skill_type=None):
    """
    Generate questions for a LEVEL-UP or SKILL test.
    NOW INCLUDES: concept field on each question for gap analysis.

    Each question has a "concept" field identifying which specific
    sub-topic within the skill it is testing. This is what enables
    gap analysis — instead of just "72% overall", we get:
      "Functions: 90%, OOP: 45%, Exception Handling: 50%"

    Args:
        dream:      dream career string
        academics:  list of academic result dicts
        level:      int, 1-5
        test_type:  "level_up" or "skill_test"
        skill_name: required for skill_test
        skill_type: optional — "conceptual"/"mathematical"/"practical"/"mixed"
                    used to adjust question style

    Returns list of question dicts, each with a "concept" field:
        {
          "question_number": 1,
          "question_text": "...",
          "question_type": "mcq",
          "concept": "Probability Distributions",
          "options": [...],
          "correct_answer": "..."
        }
    """
    if test_type not in ("level_up", "skill_test"):
        raise ValueError('test_type must be "level_up" or "skill_test"')
    if test_type == "skill_test" and not skill_name:
        raise ValueError('skill_name is required when test_type == "skill_test"')

    difficulty_guide = {
        1: "5 questions total, mostly MCQ.",
        2: "6 questions total, MCQ plus some theory.",
        3: "7 to 8 questions total, balanced MCQ/theory, more technical.",
        4: "8 to 9 questions total, mostly theory, scenario-based.",
        5: "10 questions total, all theory, professional scenarios.",
    }
    if level not in difficulty_guide:
        raise ValueError("level must be between 1 and 5")

    # Adjust question style based on skill type
    style_hint = ""
    if skill_type == "mathematical":
        style_hint = "Focus on calculation, formula application, and quantitative reasoning questions."
    elif skill_type == "practical":
        style_hint = "Focus on scenario-based, procedure-following, and real-world application questions."
    elif skill_type == "conceptual":
        style_hint = "Focus on definition, explanation, and principle-understanding questions."
    else:
        style_hint = "Mix conceptual understanding with practical application questions."

    system_prompt = (
        "You are an exam-question generator for ASPAR. You design fair, "
        "level-appropriate questions for ANY career. Each question MUST "
        "include a 'concept' field naming the specific sub-topic it tests. "
        "You ALWAYS respond with strict JSON only."
    )

    focus_line = (
        f'This is a SKILL TEST focused on: "{skill_name}" ({skill_type or "mixed"} skill).'
        if test_type == "skill_test"
        else "This is a LEVEL-UP TEST covering breadth of this level."
    )

    user_prompt = f"""
Dream career: "{dream}"
Academic background: {json.dumps(academics)}
Level: {level}
Test type: {test_type}
{focus_line}
Question style: {style_hint}
Difficulty: {difficulty_guide[level]}

CRITICAL: Every question MUST have a "concept" field.
The concept is the specific sub-topic this question tests.
Example for a Statistics skill:
  - concept: "Probability Distributions"
  - concept: "Hypothesis Testing"
  - concept: "Bayes Theorem"
  - concept: "Descriptive Statistics"

Different questions in the same skill test should test DIFFERENT concepts
so we can identify exactly where the student is strong or weak.

Rules for questions:
- For "mcq": 4 options, correct_answer matches one option exactly
- For "theory": options and correct_answer are null
- Number sequentially from 1

Respond with ONLY a JSON array:
[
  {{
    "question_number": 1,
    "question_text": "...",
    "question_type": "mcq",
    "concept": "Specific Sub-Topic Name",
    "options": ["...", "...", "...", "..."],
    "correct_answer": "..."
  }}
]
"""

    return _call_groq(system_prompt, user_prompt, expect_json=True)


# ============================================================
# 5. grade_answers
#    Input:  questions + student answers
#    Output: per-question score /10, feedback, knowledge gaps
# ============================================================
def grade_answers(questions, answers):
    """
    Grade a completed test (any test_type) in ONE call.

    Args:
        questions: list of dicts, e.g.
            [{"question_number": 1, "question_text": "...",
              "question_type": "mcq", "correct_answer": "B"}, ...]
        answers:   list of dicts, e.g.
            [{"question_number": 1, "answer_text": "B"}, ...]

    Returns:
        {
          "results": [
            {
              "question_number": 1,
              "score_out_of_10": 10,
              "feedback": "Correct - well done."
            },
            ...
          ],
          "total_score_percent": 87.5,
          "knowledge_gaps": ["Recursion", "Big-O notation"]
        }

    Notes:
        - For "mcq" questions the score will typically be 0 or 10, but
          the AI is still asked to grade them so feedback stays
          consistent and the route doesn't need separate MCQ/theory logic.
        - "knowledge_gaps" is a short list of topic names the student
          struggled with, used later by generate_roadmap() and
          evaluate_progress().
    """
    system_prompt = (
        "You are a fair, consistent grader for ASPAR. You grade student "
        "answers against the provided questions (and correct_answer for "
        "MCQs), giving a score out of 10 per question, short feedback, "
        "and an overall list of knowledge gaps. You ALWAYS respond with "
        "strict JSON only."
    )

    user_prompt = f"""
Questions: {json.dumps(questions)}

Student answers: {json.dumps(answers)}

Grade each question:
- For "mcq" questions, compare the student's answer to correct_answer.
- For "theory" questions, judge correctness/completeness of the
  written answer based on the question_text.
- Give a score_out_of_10 and 1-2 sentences of feedback per question.
- Then compute total_score_percent across all questions
  (sum of scores / (10 * number of questions) * 100, rounded to 1 decimal).
- Finally, list 1-5 short topic names the student appears weak on as
  "knowledge_gaps" (based on the lowest-scoring questions). If the
  student did well across the board, this list can be empty.

Respond with ONLY a JSON object shaped like:
{{
  "results": [
    {{"question_number": 1, "score_out_of_10": 8, "feedback": "..."}}
  ],
  "total_score_percent": 80.0,
  "knowledge_gaps": ["..."]
}}
"""

    return _call_groq(system_prompt, user_prompt, expect_json=True)


# ============================================================
# 6. generate_roadmap
#    Input:  full context (dream, academics, skill tree, scores, gaps)
#    Output: roadmap text + resource-type suggestions
# ============================================================
def generate_roadmap(dream, current_skill, learner_model):
    """
    Generate a personalized roadmap focused on the student's current
    unlocked skill, using their full learner model as evidence.
 
    IMPORTANT: ASPAR is a Roadmap System, not a Recommendation System.
    Say WHAT to learn and WHAT TYPE of resource to seek — never give
    specific links, course names, or step-by-step tutorials.
 
    Args:
        dream:          dream career string
        current_skill:  dict — the skill the student should focus on now
                         {"skill_name": "...", "skill_type": "...",
                          "category": "..."}
                         or None if no skill is currently unlocked
        learner_model:  dict from gap_analysis.get_learner_model()
                         Contains: skill_mastery, strong_skills,
                         weak_skills, persistent_gaps, academic_trend,
                         overall_trend, passion_statement, pass_rate
 
    Returns:
        {
          "overview": "1-2 sentence orientation for current level",
          "current_skill": {
            "skill_name": "...",
            "why_now": "...",
            "what_to_learn": "...",
            "resource_types": ["...", "..."]
          }
        }
 
    Equity in action: if learner_model shows weak_skills=["Statistics"]
    and current_skill is "Supervised Learning" (which depends on
    Statistics), the roadmap explicitly connects the two and tells
    THIS student to revisit Statistics fundamentals first — a student
    with strong Statistics skips straight to Supervised Learning content.
    """
    system_prompt = (
        "You are a mentor for ASPAR, a ROADMAP system - not a "
        "recommendation system. You tell students WHAT to learn next and "
        "WHAT KIND of resource to look for, focused on the single skill "
        "they should study right now. You practice EQUITY: you use the "
        "student's actual demonstrated strengths and weaknesses to decide "
        "what they specifically need - not a generic template every "
        "student gets. Two students at the same level with different "
        "skill histories should receive noticeably different guidance. "
        "You NEVER give specific links, named courses, or step-by-step "
        "tutorials - only general resource TYPES. "
        "You ALWAYS respond with strict JSON only."
    )
 
    if not current_skill:
        current_skill_line = "No skill is currently unlocked (student has completed all skills at this level)."
    else:
        current_skill_line = (
            f"Current skill to focus on: \"{current_skill['skill_name']}\" "
            f"(type: {current_skill.get('skill_type', 'mixed')}, "
            f"category: {current_skill.get('category', 'General')})"
        )
 
    skill_mastery_lines = "\n".join(
        f"  - {s['skill_name']} ({s['skill_type']}): {s['score']}% "
        f"[{s['trend']}, attempt #{s['attempts']}]"
        for s in learner_model.get("skill_mastery", [])
    ) or "  No skill tests taken yet."
 
    user_prompt = f"""
Dream career: "{dream}"
Student's passion statement: "{learner_model.get('passion_statement', '')}"
{current_skill_line}
 
STUDENT'S FULL EVIDENCE (this is what makes the roadmap equitable):
 
Per-skill test scores:
{skill_mastery_lines}
 
Strong skills (>=80%): {', '.join(learner_model.get('strong_skills', [])) or 'None yet'}
Weak skills (<60%): {', '.join(learner_model.get('weak_skills', [])) or 'None yet'}
Persistent gaps (struggled across multiple attempts): {', '.join(learner_model.get('persistent_gaps', [])) or 'None'}
 
Academic trend: {learner_model.get('academic_trend', 'insufficient_data')}
Overall learning trend: {learner_model.get('overall_trend', 'stable')}
Test pass rate: {learner_model.get('pass_rate', 0)}%
 
INSTRUCTIONS:
 
1. Write "overview" (1-2 sentences) orienting the student at their
   current level in general terms.
 
2. Write "current_skill" object about ONLY the current unlocked skill:
 
   - "skill_name": exact name from current_skill above
   - "why_now": 1-2 sentences. CRITICALLY: if any of the student's
     weak_skills or persistent_gaps are prerequisites or related to
     this current skill, name that connection explicitly. Example:
     "Since Supervised Learning relies heavily on probability theory,
     and your Statistics score of 43% shows this is a gap, strengthening
     that foundation first will make this skill much easier to grasp."
     If no weak skills are relevant, explain why this skill fits the
     natural progression instead.
 
   - "what_to_learn": 2-3 sentences. Adjust content based on
     skill_type: for "mathematical" skills emphasize formulas and
     calculation practice; for "practical" skills emphasize hands-on
     exercises and real scenarios; for "conceptual" skills emphasize
     reading and understanding principles; for "mixed" balance both.
     If the student has a relevant persistent_gap, explicitly say to
     address that specific sub-topic first.
 
   - "resource_types": 2-4 general resource types matched to skill_type.
     Mathematical -> "practice problem sets", "formula reference sheets"
     Practical -> "hands-on exercises", "case studies", "simulations"
     Conceptual -> "official documentation", "explanatory articles"
 
3. If the student's overall_trend is "declining", acknowledge it
   gently and suggest revisiting fundamentals before pushing forward.
   If "improving", acknowledge their progress genuinely.
 
4. If passion_statement is provided, connect the current skill to
   their stated motivation in one natural sentence.
 
Keep it concise - readable in under 20 seconds. Never use bullet
points inside the text fields - flowing sentences only.
 
Respond with ONLY a JSON object:
{{
  "overview": "...",
  "current_skill": {{
    "skill_name": "...",
    "why_now": "...",
    "what_to_learn": "...",
    "resource_types": ["...", "..."]
  }}
}}
 
If current_skill_line says no skill is unlocked, omit "current_skill"
entirely and just return {{"overview": "..."}}.
"""
 
    return _call_groq(system_prompt, user_prompt, expect_json=True)
 


# ============================================================
# 7. evaluate_progress
#    Input:  score history
#    Output: decision: level_up / retain / ease_roadmap / flag_unfit
# ============================================================
def evaluate_progress(previous_score, new_score, level, consecutive_no_improvement=0):
    """
    Decide what happens after a LEVEL-UP test, per Section 4 step 9 / 10:

        Improved AND new_score >= 80%        -> "level_up"
        Improved but new_score < 80%         -> "retain"
        No improvement                        -> "ease_roadmap"
        Repeated failure across multiple
        level-up tests                        -> "flag_unfit"

    Args:
        previous_score: float or None (None if this is the student's
                          first level-up test for this career)
        new_score:       float, this attempt's total_score_percent
        level:           int, the student's current level (1-5)
        consecutive_no_improvement: int, how many CONSECUTIVE level-up
                          tests in a row showed no improvement
                          (tracked by the route via progress_log).
                          Used to decide when to escalate to
                          "flag_unfit".

    Returns:
        {
          "decision": "level_up" | "retain" | "ease_roadmap" | "flag_unfit",
          "reasoning": "short explanation"
        }
    """
    system_prompt = (
        "You are a progress-evaluation engine for ASPAR. Given a "
        "student's level-up test score history, you decide one of: "
        "level_up, retain, ease_roadmap, or flag_unfit, following the "
        "rules given exactly. You ALWAYS respond with strict JSON only."
    )

    user_prompt = f"""
Current level: {level} (1-5)
Previous level-up test score (percent), or null if this is the first
attempt: {json.dumps(previous_score)}
New level-up test score (percent): {new_score}
Consecutive level-up tests in a row with NO improvement (before this
one): {consecutive_no_improvement}

Decide the outcome using these rules, in order:
1. If new_score shows improvement over previous_score AND new_score >= 80
   -> "level_up"
2. If new_score shows improvement over previous_score BUT new_score < 80
   -> "retain"
3. If new_score does NOT improve over previous_score:
   - If this brings consecutive_no_improvement to 3 or more (i.e. the
     student has now failed to improve 3+ times in a row)
     -> "flag_unfit"
   - Otherwise -> "ease_roadmap"
4. If previous_score is null (first attempt), treat reaching >= 80 as
   "level_up" and below 80 as "retain" (cannot be "ease_roadmap" or
   "flag_unfit" on a first attempt).

Respond with ONLY a JSON object shaped like:
{{
  "decision": "level_up",
  "reasoning": "A short (1-3 sentence) explanation of this decision."
}}
"""

    return _call_groq(system_prompt, user_prompt, expect_json=True)


# ============================================================
# 8. suggest_alternative_careers
#    Input:  performance history
#    Output: 3 alternative careers + reasoning
# ============================================================
def suggest_alternative_careers(performance_data):
    """
    Suggest 3 alternative careers when a student has been flagged
    "possibly unfit" for their current dream career (Section 4,
    "Career Change Flow"). This is ALWAYS opt-in - the student is
    asked first, and this function is only called if they say yes.

    Args:
        performance_data: dict summarizing the student's performance,
            e.g.
            {
              "dream_career": "Software Developer",
              "current_level": 2,
              "academics": [...],
              "score_history": [
                {"test_type": "level_up", "total_score_percent": 55},
                {"test_type": "level_up", "total_score_percent": 50},
                {"test_type": "level_up", "total_score_percent": 48}
              ],
              "knowledge_gaps": ["Algorithms", "Debugging"]
            }

    Returns:
        {
          "alternatives": [
            {"career": "UI/UX Designer", "reasoning": "..."},
            {"career": "Technical Writer", "reasoning": "..."},
            {"career": "QA Tester", "reasoning": "..."}
          ]
        }
    """
    system_prompt = (
        "You are a supportive career-guidance advisor for ASPAR. A "
        "student has been struggling repeatedly with their current "
        "dream career track. Based on their ACTUAL performance data, "
        "suggest 3 alternative careers that better match their "
        "demonstrated strengths - be encouraging, not discouraging. "
        "You ALWAYS respond with strict JSON only."
    )

    user_prompt = f"""
Student performance data: {json.dumps(performance_data)}

Suggest exactly 3 alternative career paths that better fit this
student's demonstrated strengths (from academics and score history),
while staying broadly related to their interests where possible. For
each, give a short, encouraging reason grounded in their actual data.

Respond with ONLY a JSON object shaped like:
{{
  "alternatives": [
    {{"career": "...", "reasoning": "..."}},
    {{"career": "...", "reasoning": "..."}},
    {{"career": "...", "reasoning": "..."}}
  ]
}}
"""

    return _call_groq(system_prompt, user_prompt, expect_json=True)


# ============================================================
# 9. structure_ocr_text  (called ONLY from academic_upload route)
#    Input:  raw OCR text from a scanned report card / transcript
#    Output: clean list of {subject, grade, gpa} rows
# ============================================================
def structure_ocr_text(raw_text):
    """
    Take noisy OCR output from a scanned academic document and extract
    structured subject/grade/GPA rows that the student can review and
    confirm before saving.

    This is a SEPARATE Groq call from the 8 main AI functions - it is
    only ever triggered by the OCR upload route, and only when the user
    uploads a file. It is NOT called for manual academic entry or skip.

    Args:
        raw_text: str, the messy OCR output from ocr_service.extract_text_from_file()

    Returns:
        A list of dicts:
        [
          {"subject": "Mathematics", "grade": "A", "gpa": 3.8},
          {"subject": "Physics",     "grade": "B+","gpa": 3.5},
          ...
        ]
        Fields "grade" and "gpa" may be null if the document does not
        contain them (e.g. some transcripts show grades only, no GPA).

    Note:
        The returned list is shown to the student in an editable table
        for review before saving - we do not auto-save OCR results.
    """
    system_prompt = (
        "You are a data-extraction assistant for ASPAR. You receive raw, "
        "possibly noisy OCR text from a scanned student academic document "
        "(report card, transcript, grade sheet, etc.) and extract clean "
        "structured rows. You ALWAYS respond with strict JSON only."
    )

    user_prompt = f"""
Below is raw OCR text extracted from a scanned academic document.
Extract every subject/course with its grade and GPA (if present).

Rules:
- Ignore headers, school names, student info, dates, and irrelevant text.
- For each subject found, produce one row with:
    "subject" (string, required),
    "grade"   (string or null - letter grade, percentage, or descriptor),
    "gpa"     (float or null - only if a numeric GPA is clearly shown).
- If a GPA value is shown for the whole document (e.g. "GPA: 3.7") but
  not per-subject, you may add it to each row that does not have its own
  GPA. Use null otherwise.
- If no subjects can be found at all, return an empty array [].

Raw OCR text:
\"\"\"
{raw_text}
\"\"\"

Respond with ONLY a JSON array of row objects shaped like:
{{
  "subject": "Mathematics",
  "grade": "A",
  "gpa": 3.8
}}
"""

    return _call_groq(system_prompt, user_prompt, expect_json=True)
