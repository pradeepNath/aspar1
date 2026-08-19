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
import time
import logging
import itertools
from groq import Groq, RateLimitError, AuthenticationError, APIConnectionError

logger = logging.getLogger("groq_service")

# ============================================================
# Key rotation pool
# ============================================================
GROQ_KEYS = [
    os.environ[k] for k in sorted(os.environ)
    if k.startswith("GROQ_API_KEY")
]

if not GROQ_KEYS:
    raise RuntimeError(
        "No GROQ_API_KEY_* found in environment. "
        "Set GROQ_API_KEY_1 (at minimum) in .env."
    )


def _mask(key):
    """Last 6 chars only - enough to tell keys apart in logs without
    ever printing a usable key."""
    return f"...{key[-6:]}" if key else "None"


# Per-key cooldown timestamps - a key that just hit a rate limit or
# failed auth is skipped until its cooldown expires (or forever, for
# a dead/invalid key).
_cooldowns = {key: 0 for key in GROQ_KEYS}
_key_cycle = itertools.cycle(GROQ_KEYS)
_current_key = next(_key_cycle)
_client = Groq(api_key=_current_key)

logger.info(
    "groq_service: loaded %d key(s), starting on %s",
    len(GROQ_KEYS), _mask(_current_key),
)

# Default model - can be overridden via .env (GROQ_MODEL=...) without
# touching code, in case the supported model name changes again.
# NOTE: llama-3.3-70b-versatile was deprecated by Groq (announced
# June 17 2026); ASPAR now runs on openai/gpt-oss-120b, Groq's
# recommended replacement.
_MODEL = os.getenv("GROQ_MODEL")

# ------------------------------------------------------------
# Running token-usage totals (process lifetime, in-memory only -
# resets on every Render restart/deploy, not persisted to DB).
# Tracked per-key so you can see which key is absorbing the most
# load, plus a grand total across all keys.
# ------------------------------------------------------------
_usage_totals = {
    key: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}
    for key in GROQ_KEYS
}


def get_usage_summary():
    """
    Return current in-memory token usage totals, per key (masked) and
    combined. Call this from a debug/admin route if you want to check
    usage without digging through logs, e.g.:

        GET /debug/groq-usage -> jsonify(groq_service.get_usage_summary())
    """
    combined = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}
    per_key = {}
    for key, stats in _usage_totals.items():
        per_key[_mask(key)] = dict(stats)
        for field in combined:
            combined[field] += stats[field]
    return {"per_key": per_key, "combined": combined}


def _next_available_key():
    """Cycle through the pool once looking for a key off cooldown.
    If every key is on cooldown, returns the next one anyway - a
    live attempt is better than refusing outright."""
    for _ in range(len(GROQ_KEYS)):
        candidate = next(_key_cycle)
        if time.time() >= _cooldowns[candidate]:
            return candidate
    return candidate


def _rotate_key(cooldown_seconds=None):
    """Switch _client to the next available key. Called whenever the
    current key errors with a rate-limit, auth, or connection failure."""
    global _current_key, _client
    previous_key = _current_key
    if cooldown_seconds is not None:
        _cooldowns[_current_key] = time.time() + cooldown_seconds
    _current_key = _next_available_key()
    _client = Groq(api_key=_current_key)
    logger.info(
        "groq_service: rotated key %s -> %s%s",
        _mask(previous_key), _mask(_current_key),
        f" (cooldown {cooldown_seconds}s on {_mask(previous_key)})"
        if cooldown_seconds else "",
    )


# ============================================================
# Internal helper - NOT one of the 8 public functions.
# Every public function below funnels through this, so retry /
# JSON-parsing / error-handling / key-rotation / usage-logging
# logic all live in exactly one place.
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
        RuntimeError if every key in the pool is rate-limited, invalid,
        or unreachable.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    raw_text = _create_with_rotation(messages, temperature)

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
    retry_text = _create_with_rotation(messages, temperature)

    parsed = _try_parse_json(retry_text)
    if parsed is not None:
        return parsed

    raise ValueError(
        "Groq did not return valid JSON after one retry. "
        f"Last raw response: {retry_text[:500]}"
    )


def _create_with_rotation(messages, temperature):
    """
    Call chat.completions.create(), rotating through GROQ_KEYS on
    rate-limit, auth, or connection errors. Tries each key at most
    once per call to this function - if all keys fail, raises
    RuntimeError. This is independent from the JSON-retry logic in
    _call_groq(): a key can succeed at the API level but still return
    bad JSON, and vice versa.

    On every successful call, logs and accumulates token usage
    (prompt/completion/total) against the key that served it, using
    the `usage` object Groq returns alongside the response.
    """
    attempts = 0
    max_attempts = len(GROQ_KEYS)
    last_error = None

    while attempts < max_attempts:
        try:
            response = _client.chat.completions.create(
                model=_MODEL,
                messages=messages,
                temperature=temperature,
            )

            # --- Token usage logging ---
            usage = getattr(response, "usage", None)
            if usage is not None:
                prompt_t = getattr(usage, "prompt_tokens", 0) or 0
                completion_t = getattr(usage, "completion_tokens", 0) or 0
                total_t = getattr(usage, "total_tokens", prompt_t + completion_t)

                stats = _usage_totals[_current_key]
                stats["prompt_tokens"] += prompt_t
                stats["completion_tokens"] += completion_t
                stats["total_tokens"] += total_t
                stats["calls"] += 1

                logger.info(
                    "groq_service: call on key %s used %d tokens "
                    "(prompt=%d, completion=%d) | key total=%d over %d calls",
                    _mask(_current_key), total_t, prompt_t, completion_t,
                    stats["total_tokens"], stats["calls"],
                )
            else:
                logger.info(
                    "groq_service: call on key %s succeeded but no usage "
                    "data was returned by the SDK.",
                    _mask(_current_key),
                )

            return response.choices[0].message.content.strip()

        except RateLimitError as e:
            last_error = e
            attempts += 1
            logger.warning(
                "groq_service: rate limited on key %s (attempt %d/%d): %s",
                _mask(_current_key), attempts, max_attempts, e,
            )
            # Groq's 429 usually carries a Retry-After header; fall
            # back to a sane default if it's not present.
            wait = 60
            if e.response is not None:
                retry_after = e.response.headers.get("retry-after")
                if retry_after:
                    try:
                        wait = int(retry_after)
                    except ValueError:
                        pass
            _rotate_key(cooldown_seconds=wait)

        except AuthenticationError as e:
            last_error = e
            attempts += 1
            logger.error(
                "groq_service: auth failed on key %s - retiring it "
                "(attempt %d/%d): %s",
                _mask(_current_key), attempts, max_attempts, e,
            )
            # Dead/invalid key - retire it for the life of this process.
            _cooldowns[_current_key] = float("inf")
            _rotate_key()

        except APIConnectionError as e:
            last_error = e
            attempts += 1
            logger.warning(
                "groq_service: connection error on key %s (attempt %d/%d): %s",
                _mask(_current_key), attempts, max_attempts, e,
            )
            # Not necessarily this key's fault (network blip), but a
            # fresh attempt - possibly via a different network path -
            # costs little. Short cooldown only.
            _rotate_key(cooldown_seconds=5)

    logger.critical(
        "groq_service: all %d keys exhausted, invalid, or unreachable.",
        max_attempts,
    )
    raise RuntimeError(
        f"All {max_attempts} Groq keys exhausted, invalid, or unreachable."
    ) from last_error


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
- Do not reveal difficulty or include labels such as "Level 1" in the
  question text. Difficulty is for internal placement only.
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
#    Output: full 5-level categorized skill tree (JSON), with
#            skill_type classification and dependencies
# ============================================================
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
- Preserve the "concept" field from each question in the corresponding
  result. Do not invent or rename the concept.
- Finally, list 1-5 short topic names the student appears weak on as
  "knowledge_gaps" (based on the lowest-scoring questions). If the
  student did well across the board, this list can be empty.

Respond with ONLY a JSON object shaped like:
{{
  "results": [
    {{
    "question_number": 1,
    "concept": "Probability Distributions",
    "score_out_of_10": 8,
    "feedback": "..."
}}
  ],
  "total_score_percent": 80.0,
  "knowledge_gaps": ["..."]
}}
"""

    return _call_groq(system_prompt, user_prompt, expect_json=True)


# ============================================================
# 6. generate_roadmap
#    Input:  full context (dream, academics, skill tree, scores, gaps,
#             optional active_subskill for personalized remediation)
#    Output: roadmap text + resource-type suggestions
# ============================================================
def generate_roadmap(
    dream,
    academics,
    skill_tree,
    scores,
    gaps,
    active_subskill=None,
    completed_subskill=None,
):
    """
    Create a personalized roadmap without changing the shared core tree.

    If active_subskill exists, it becomes the current learning focus.
    If a remediation branch was just completed, explain the transition back
    to its parent core skill. Otherwise, use the current unlocked core skill.

    Args:
        dream: Career name.
        academics: Learner academic results.
        skill_tree: Visible shared-core skills for this learner, including
                    skill_name, category, skill_type, status, and level.
        scores: Learner's past test-score data.
        gaps: Demonstrated weak concepts.
        active_subskill: Optional learner-specific remediation object:
            {
              "skill_name": "...",
              "concept": "...",
              "reason": "...",
              "skill_type": "...",
              "parent_core_skill": "..."
            }
        completed_subskill: Most recently completed remediation object, with
            the same shape as active_subskill.
    """

    current_core_skill = next(
        (skill for skill in skill_tree if skill.get("status") == "unlocked"),
        None,
    )

    if active_subskill:
        focus_type = "personalized_subskill"
        focus = {
            "skill_name": active_subskill["skill_name"],
            "concept": active_subskill.get("concept", "Targeted practice"),
            "skill_type": active_subskill.get("skill_type", "mixed"),
            "parent_core_skill": active_subskill.get(
                "parent_core_skill",
                current_core_skill.get("skill_name") if current_core_skill else None,
            ),
            "reason": active_subskill.get("reason", ""),
        }
    elif completed_subskill and current_core_skill:
        focus_type = "return_to_core"
        focus = {
            "skill_name": current_core_skill["skill_name"],
            "concept": completed_subskill.get("concept", ""),
            "skill_type": current_core_skill.get("skill_type", "mixed"),
            "parent_core_skill": completed_subskill.get("parent_core_skill"),
            "completed_subskill": completed_subskill.get("skill_name"),
            "reason": completed_subskill.get("reason", ""),
        }
    elif current_core_skill:
        focus_type = "core_skill"
        focus = {
            "skill_name": current_core_skill["skill_name"],
            "concept": None,
            "skill_type": current_core_skill.get("skill_type", "mixed"),
            "parent_core_skill": None,
            "reason": None,
        }
    else:
        focus_type = "none"
        focus = None

    system_prompt = (
        "You are a mentor for ASPAR, an adaptive student roadmap system. "
        "You tell the learner WHAT to learn next and what TYPES of resources "
        "to seek. You never recommend named courses, links, or step-by-step "
        "tutorials. You NEVER change, add, remove, or reorder core skills. "
        "You ALWAYS return strict JSON only."
    )

    user_prompt = f"""
Dream career: "{dream}"

Academic results:
{json.dumps(academics)}

Shared core skill tree:
{json.dumps(skill_tree)}

Learner's past test scores:
{json.dumps(scores)}

Demonstrated knowledge gaps:
{json.dumps(gaps)}

Focus type: "{focus_type}"

Current focus:
{json.dumps(focus)}

Rules:

1. The shared core skill tree is fixed for all learners in this career.
   Do not suggest changing its skills, order, level, or dependencies.

2. If focus_type is "personalized_subskill":
   - The learner must focus on this remediation subskill first.
   - Explain that it supports the parent core skill.
   - Focus only on the demonstrated weak concept.
   - State that after mastering it, the learner returns to the normal
     core-skill sequence.

3. If focus_type is "core_skill":
   - Explain why this shared core skill is the next normal step.
   - Use academic results, scores, and gaps only to personalize the
    explanation and learning emphasis—not to change the core skill.

4. If focus_type is "return_to_core":
   - Acknowledge the completed remediation subskill by name.
   - Explain how it supports the current core skill and what to do next.
   - Keep the current core skill as the exact current_focus skill_name.

5. If focus_type is "none":
   - Return only an overview explaining that no current skill is available.

6. Make why_now and what_to_learn specific but scannable: each must be one
   or two short sentences, with concrete concepts or actions.

7. Create a compact learning mission:
   - estimated_effort: a realistic short estimate such as "2–3 focused sessions".
   - mission_steps: exactly 3 or 4 short, ordered actions. Each step must be
     practical and build on the previous one.
   - practice_task: one small, concrete task or artefact the learner can make.
   - success_checklist: exactly 3 observable statements that mean the learner
     is ready to take the test. Do not use vague statements such as "understand
     the topic".

8. Recommend resources appropriate to the career and skill—not just software
   resources. For example, use professional bodies and clinical guidelines for
   healthcare, portfolios and briefs for design, case studies for business,
   labs or simulations for science, and official references for technical work.
   Do not invent direct URLs or named videos.

Return ONLY this JSON object:

{{
  "focus_type": "core_skill",
  "overview": "One or two sentences about the learner's current stage.",
  "parent_core_skill": null,
  "current_focus": {{
    "skill_name": "Exact current skill name",
    "concept": null,
    "why_now": "Why this is the correct next focus for this learner.",
    "what_to_learn": "What the learner should focus on.",
    "estimated_effort": "2–3 focused sessions",
    "mission_steps": [
      "First practical action",
      "Second practical action",
      "Third practical action"
    ],
    "practice_task": "One small real-world task to complete before the test.",
    "success_checklist": [
      "I can demonstrate a specific outcome.",
      "I can demonstrate another specific outcome.",
      "I can explain or apply a specific outcome."
    ],
    "resource_types": [
      "Professional resource: specific search terms for this skill and career",
      "Practice resource: specific search terms for hands-on practice",
      "Video search: specific topic search terms"
    ],
    "return_to_core_sequence": false
  }},
  "next_core_skill": "The core skill to resume or continue"
}}
"""

    roadmap = _call_groq(
        system_prompt,
        user_prompt,
        expect_json=True,
        temperature=0.3,
    )

    # The model returns a simple list of resource search instructions. Convert
    # it to a small, safe structure for the UI; the UI creates the actual link
    # and the model never needs to invent a URL.
    current_focus = roadmap.get("current_focus") or {}
    resource_types = current_focus.get("resource_types")
    if not isinstance(resource_types, list):
        resource_types = []

    def _resource_item(resource_type):
        text = str(resource_type).strip()
        label, separator, query = text.partition(":")
        query = query.strip() if separator else text
        return {
            "label": (label.strip() or "Learning resource")[:80],
            "description": f"Search for {query}."[:180],
            "search_query": query[:180],
            "destination": "video" if "video" in label.lower() else "web",
        }

    current_focus["learning_resources"] = [
        _resource_item(item)
        for item in resource_types[:3]
        if isinstance(item, str) and item.strip()
    ]
    # Bound AI output so the mission stays useful and compact in the card.
    current_focus["estimated_effort"] = str(
        current_focus.get("estimated_effort") or "2–3 focused sessions"
    )[:80]
    current_focus["mission_steps"] = [
        str(step)[:180]
        for step in (current_focus.get("mission_steps") or [])[:4]
        if isinstance(step, str) and step.strip()
    ]
    current_focus["practice_task"] = str(
        current_focus.get("practice_task") or ""
    )[:240]
    current_focus["success_checklist"] = [
        str(item)[:160]
        for item in (current_focus.get("success_checklist") or [])[:3]
        if isinstance(item, str) and item.strip()
    ]
    roadmap["current_focus"] = current_focus

    # Protect the core path if the model returns an unexpected value.
    roadmap["focus_type"] = focus_type
    roadmap["parent_core_skill"] = (
        focus.get("parent_core_skill") if focus else None
    )

    if focus_type == "personalized_subskill":
        roadmap.setdefault("current_focus", {})
        roadmap["current_focus"]["skill_name"] = focus["skill_name"]
        roadmap["current_focus"]["concept"] = focus["concept"]
        roadmap["current_focus"]["return_to_core_sequence"] = True
        roadmap["next_core_skill"] = focus["parent_core_skill"]

    elif focus_type == "return_to_core" and current_core_skill:
        roadmap.setdefault("current_focus", {})
        roadmap["current_focus"]["skill_name"] = current_core_skill["skill_name"]
        roadmap["current_focus"]["completed_subskill"] = focus["completed_subskill"]
        roadmap["current_focus"]["return_to_core_sequence"] = True
        roadmap["next_core_skill"] = current_core_skill["skill_name"]

    elif focus_type == "core_skill" and current_core_skill:
        roadmap.setdefault("current_focus", {})
        roadmap["current_focus"]["skill_name"] = current_core_skill["skill_name"]
        roadmap["current_focus"]["return_to_core_sequence"] = False
        roadmap["next_core_skill"] = current_core_skill["skill_name"]

    return roadmap

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


# ============================================================
# 10. generate_personalized_subskills
#     (called ONLY after a learner performs poorly on a skill test)
#     Input:  existing core skill + concept-level performance data
#     Output: learner-specific remediation subskills
#
#     IMPORTANT:
#     - Creates temporary subskills only for demonstrated weak concepts.
#     - Never creates, removes, renames, or reorders shared core skills.
#     - After these subskills are completed, the learner returns to the
#       normal shared core-skill sequence.
# ============================================================
def generate_personalized_subskills(core_skill, concept_performance):
    """
    Create temporary learner-specific remediation steps.
    It cannot modify or replace any core skill.
    """
    weak_concepts = [
        item for item in concept_performance
        if float(item.get("score_percent", 100)) < 50
    ]

    if not weak_concepts:
        return []

    system_prompt = (
        "You create short learner-specific remediation subskills for ASPAR. "
        "You NEVER modify, add, remove, rename, or reorder shared core skills. "
        "You ALWAYS respond with strict JSON only."
    )

    user_prompt = f"""
Parent core skill:
{json.dumps(core_skill)}

Demonstrated weak concepts:
{json.dumps(weak_concepts)}

Create 1-3 temporary remediation subskills.

Rules:

- Every subskill must directly address one of the supplied weak concepts.
- Only create subskills for concepts with score_percent below 50.
- Do not invent unrelated weaknesses.
- These are beneath the parent core skill only.
- Do not create a new core skill.
- Do not modify, remove, rename, or reorder any existing core skill.
- Create at most one subskill for each weak concept.
- The skill should be specific enough for the learner to practice.
- Include the actual weak concept in "concept".
- Use "conceptual", "mathematical", "practical", or "mixed" for skill_type.

Return ONLY:

[
  {{
    "concept": "Exact weak concept",
    "skill_name": "Specific remediation skill",
    "skill_type": "practical",
    "reason": "The learner scored 30% on this concept."
  }}
]
"""
    return _call_groq(
        system_prompt,
        user_prompt,
        expect_json=True,
        temperature=0.2,
    )
