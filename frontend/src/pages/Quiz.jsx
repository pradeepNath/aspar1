import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import Navbar from "../components/Navbar";
import api from "../utils/api";

const PHASES = { LOADING:"loading", ANSWERING:"answering", SUBMITTING:"submitting", ERROR:"error" };

function QuestionCard({ q, answer, onAnswer }) {
  const isSel = (opt) => answer === opt;
  return (
    <div style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:12, padding:"22px 24px", marginBottom:14 }}>
      <div style={{ fontWeight:700, color:"#fff", marginBottom:16, fontSize:"0.95rem", display:"flex", gap:10 }}>
        <span style={{ color:"var(--primary-lt)", flexShrink:0 }}>Q{q.question_number}.</span>
        <span>{q.question_text}</span>
      </div>
      {q.question_type === "mcq" ? (
        <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
          {(q.options||[]).map(opt => (
            <label key={opt} onClick={() => onAnswer(opt)} style={{
              display:"flex", alignItems:"center", gap:12, cursor:"pointer", padding:"12px 16px", borderRadius:9,
              border:`1.5px solid ${isSel(opt) ? "var(--primary)" : "rgba(255,255,255,0.08)"}`,
              background: isSel(opt) ? "rgba(99,102,241,0.12)" : "rgba(255,255,255,0.02)",
              transition:"all 0.15s",
            }}>
              <div style={{
                width:18, height:18, borderRadius:"50%", flexShrink:0,
                border: isSel(opt) ? "5px solid var(--primary)" : "2px solid rgba(255,255,255,0.25)",
                background: isSel(opt) ? "#fff" : "transparent", transition:"all 0.15s",
              }}/>
              <span style={{ fontSize:"0.9rem", color: isSel(opt) ? "#fff" : "var(--text-2)" }}>{opt}</span>
            </label>
          ))}
        </div>
      ) : (
        <textarea value={answer||""} onChange={e => onAnswer(e.target.value)} placeholder="Write your answer here..." rows={4}
          style={{ width:"100%", padding:"12px 14px", background:"rgba(255,255,255,0.03)", border:"1px solid rgba(255,255,255,0.1)", borderRadius:9, color:"#fff", fontSize:"0.9rem", fontFamily:"var(--font)", resize:"vertical", outline:"none" }}
          onFocus={e => e.target.style.borderColor="var(--primary)"}
          onBlur={e  => e.target.style.borderColor="rgba(255,255,255,0.1)"}
        />
      )}
    </div>
  );
}

export default function Quiz() {
  const navigate = useNavigate();
  const location = useLocation();
  const { test_type, skill_id } = location.state || {};
  const [phase,   setPhase]   = useState(PHASES.LOADING);
  const [session, setSession] = useState(null);
  const [answers, setAnswers] = useState({});
  const [error,   setError]   = useState("");
  const [status,  setStatus]  = useState("Loading your quiz…");

  useEffect(() => { if (!test_type) { navigate("/dashboard"); return; } startQuiz(); }, []);

  async function startQuiz() {
    setPhase(PHASES.LOADING);
    setStatus(test_type === "skill_test" ? "Generating skill test…" : "Generating level-up test…");
    try {
      const body = { test_type }; if (skill_id) body.skill_id = skill_id;
      const res  = await api.post("/quiz/start", body);
      setSession(res.data);
      const init = {}; res.data.questions.forEach(q => { init[q.id] = ""; });
      setAnswers(init); setPhase(PHASES.ANSWERING);
    } catch (err) {
      setError(err.response?.data?.error || "Could not start quiz."); setPhase(PHASES.ERROR);
    }
  }

  function setAnswer(qId, val) { setAnswers(prev => ({ ...prev, [qId]: val })); }

  async function handleSubmit() {
    const unanswered = session.questions.filter(q => !(answers[q.id]||"").trim());
    if (unanswered.length) { setError(`Please answer all ${unanswered.length} remaining question(s).`); return; }
    setError(""); setPhase(PHASES.SUBMITTING);
    try {
      setStatus("Submitting answers…");
      const answerList = session.questions.map(q => ({ question_id:q.id, answer_text:answers[q.id] }));
      await api.post("/quiz/submit", { session_id:session.session_id, answers:answerList });
      setStatus("AI is grading your answers…");
      const gradingRes = await api.post("/grading/run", { session_id:session.session_id });
      const grading    = gradingRes.data;

      let skillResult = null, progressResult = null;
      if (test_type === "skill_test" && grading.total_score_percent >= 80) {
        setStatus("Unlocking next skill…");
        const sr = await api.post("/skills/complete", { skill_id });
        skillResult = sr.data;
      }
      if (test_type === "level_up") {
        setStatus("Evaluating your progress…");
        const pr = await api.post("/progress/evaluate", { session_id:session.session_id, total_score_percent:grading.total_score_percent, knowledge_gaps:grading.knowledge_gaps||[] });
        progressResult = pr.data;
      }
      navigate("/grading", { state:{ grading, test_type, skill_id, skillResult, progressResult } });
    } catch (err) {
      setError(err.response?.data?.error || "Submission failed."); setPhase(PHASES.ANSWERING);
    }
  }

  if (phase === PHASES.LOADING || phase === PHASES.SUBMITTING) return (
    <>
      <Navbar />
      <div className="spinner-wrap" style={{ marginTop:100 }}>
        <div className="spinner" style={{ width:48, height:48 }}/><span>{status}</span>
      </div>
    </>
  );

  if (phase === PHASES.ERROR) return (
    <>
      <Navbar />
      <div className="main-layout" style={{ maxWidth:680 }}>
        <div className="alert alert-error">{error}</div>
        <button className="btn btn-ghost" onClick={() => navigate("/dashboard")}>← Back to Dashboard</button>
      </div>
    </>
  );

  const answered = session.questions.filter(q => (answers[q.id]||"").trim()).length;
  const total    = session.questions.length;
  const title    = test_type === "skill_test" ? "Skill Test" : `Level ${session.level} — Level-Up Test`;

  return (
    <>
      <Navbar />
      <div className="main-layout" style={{ maxWidth:680 }}>
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:6 }}>
          <h1 style={{ margin:0 }}>{title}</h1>
          <span style={{ background:"rgba(6,182,212,0.15)", border:"1px solid rgba(6,182,212,0.3)", color:"#67e8f9", borderRadius:20, padding:"4px 14px", fontSize:"0.82rem", fontWeight:700 }}>
            {answered}/{total} answered
          </span>
        </div>
        <p style={{ marginBottom:24 }}>
          {test_type === "skill_test" ? "You need ≥80% to mark this skill as learned." : "You need ≥80% to advance to the next level."}
        </p>

        {error && <div className="alert alert-error">{error}</div>}

        {session.questions.map(q => (
          <QuestionCard key={q.id} q={q} answer={answers[q.id]} onAnswer={val => setAnswer(q.id, val)} />
        ))}

        {/* Progress + submit */}
        <div style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:12, padding:"16px 20px", marginTop:8 }}>
          <div style={{ display:"flex", justifyContent:"space-between", marginBottom:8 }}>
            <span style={{ color:"var(--text-3)", fontSize:"0.82rem" }}>{total - answered} remaining</span>
            <span style={{ color:"var(--text-3)", fontSize:"0.82rem" }}>{Math.round(answered/total*100)}%</span>
          </div>
          <div style={{ height:4, background:"rgba(255,255,255,0.08)", borderRadius:2, overflow:"hidden", marginBottom:16 }}>
            <div style={{ height:"100%", background:"var(--grad)", borderRadius:2, width:`${answered/total*100}%`, transition:"width 0.3s" }}/>
          </div>
          <button className="btn btn-grad btn-full btn-lg" onClick={handleSubmit} disabled={answered < total}>
            {answered < total ? `Answer all questions (${total - answered} remaining)` : "Submit answers →"}
          </button>
        </div>

        <button className="btn btn-ghost btn-sm mt-16" onClick={() => navigate("/dashboard")}>← Cancel & return to Dashboard</button>
      </div>
    </>
  );
}