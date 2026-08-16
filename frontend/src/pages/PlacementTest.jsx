import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import api from "../utils/api";

const PHASES = { LOADING:"loading", ANSWERING:"answering", GRADING:"grading", DONE:"done", ERROR:"error" };

function OnboardingNav() {
  const user = JSON.parse(localStorage.getItem("user") || "{}");
  return (
    <nav style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"14px 32px", borderBottom:"1px solid var(--border)", background:"var(--bg)" }}>
      <span className="navbar-brand"><span className="b1">AS</span><span className="b2">PAR</span></span>
      {user?.name && <span style={{ color:"var(--text-3)", fontSize:"0.85rem" }}>🔥 {user.name.split(" ")[0]}</span>}
    </nav>
  );
}

function QuestionCard({ q, answer, onAnswer }) {
  const isSelected = (opt) => answer === opt;

  return (
    <div style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:12, padding:"22px 24px", marginBottom:16 }}>
      <div style={{ fontWeight:700, color:"#fff", marginBottom:16, fontSize:"0.95rem", display:"flex", gap:10 }}>
        <span style={{ color:"var(--primary-lt)", flexShrink:0 }}>Q{q.question_number}.</span>
        <span>{q.question_text}</span>
      </div>

      {q.question_type === "mcq" ? (
        <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
          {(q.options || []).map(opt => (
            <label key={opt} onClick={() => onAnswer(opt)} style={{
              display:"flex", alignItems:"center", gap:12, cursor:"pointer",
              padding:"12px 16px", borderRadius:9,
              border:"1.5px solid",
              borderColor: isSelected(opt) ? "var(--primary)" : "rgba(255,255,255,0.08)",
              background: isSelected(opt) ? "rgba(99,102,241,0.12)" : "rgba(255,255,255,0.02)",
              transition:"all 0.15s",
            }}>
              {/* Custom radio */}
              <div style={{
                width:18, height:18, borderRadius:"50%", flexShrink:0,
                border: isSelected(opt) ? "5px solid var(--primary)" : "2px solid rgba(255,255,255,0.25)",
                background: isSelected(opt) ? "#fff" : "transparent",
                transition:"all 0.15s",
              }}/>
              <span style={{ fontSize:"0.9rem", color: isSelected(opt) ? "#fff" : "var(--text-2)" }}>{opt}</span>
            </label>
          ))}
        </div>
      ) : (
        <textarea
          value={answer || ""}
          onChange={e => onAnswer(e.target.value)}
          placeholder="Write your answer here..."
          rows={4}
          style={{
            width:"100%", padding:"12px 14px",
            background:"rgba(255,255,255,0.03)",
            border:"1px solid rgba(255,255,255,0.1)",
            borderRadius:9, color:"#fff", fontSize:"0.9rem",
            fontFamily:"var(--font)", resize:"vertical", outline:"none",
            transition:"border-color 0.2s",
          }}
          onFocus={e => e.target.style.borderColor = "var(--primary)"}
          onBlur={e  => e.target.style.borderColor = "rgba(255,255,255,0.1)"}
        />
      )}
    </div>
  );
}

export default function PlacementTest() {
  const navigate  = useNavigate();
  const [phase,     setPhase]     = useState(PHASES.LOADING);
  const [session,   setSession]   = useState(null);
  const [answers,   setAnswers]   = useState({});
  const [results,   setResults]   = useState(null);
  const [error,     setError]     = useState("");
  const [statusMsg, setStatusMsg] = useState("Generating your placement test…");

  const dots = ["done", "done", "done", "active"];

  useEffect(() => { startQuiz(); }, []);

  async function startQuiz() {
    setPhase(PHASES.LOADING); setStatusMsg("Generating your placement test…");
    try {
      const res = await api.post("/quiz/start", { test_type:"placement" });
      setSession(res.data);
      const init = {}; res.data.questions.forEach(q => { init[q.id] = ""; });
      setAnswers(init);
      setPhase(PHASES.ANSWERING);
    } catch (err) {
      setError(err.response?.data?.error || "Could not start test. Please refresh.");
      setPhase(PHASES.ERROR);
    }
  }

  function setAnswer(qId, val) { setAnswers(prev => ({ ...prev, [qId]: val })); }

  async function handleSubmit() {
    setError("");
    const unanswered = session.questions.filter(q => !(answers[q.id]||"").trim());
    if (unanswered.length) { setError(`Please answer all ${unanswered.length} remaining question(s).`); return; }

    setPhase(PHASES.GRADING); setStatusMsg("Submitting your answers…");
    try {
      const answerList = session.questions.map(q => ({ question_id:q.id, answer_text:answers[q.id] }));
      await api.post("/quiz/submit", { session_id:session.session_id, answers:answerList });
      setStatusMsg("AI is grading your test…");
      const gradingRes = await api.post("/grading/run", { session_id:session.session_id });
      setResults(gradingRes.data);
      setStatusMsg("Building your skill tree…");
      await api.post("/skills/generate");
      setStatusMsg("Creating your personalised roadmap…");
      await api.post("/roadmap/generate");
      setPhase(PHASES.DONE);
    } catch (err) {
      setError(err.response?.data?.error || "Something went wrong. Please try again.");
      setPhase(PHASES.ANSWERING);
    }
  }

  const Spinner = ({ msg }) => (
    <div style={{ minHeight:"100vh", background:"var(--bg)", display:"flex", flexDirection:"column" }}>
      <OnboardingNav />
      <div style={{ flex:1, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", gap:20 }}>
        <div className="spinner" style={{ width:48, height:48 }} />
        <p style={{ color:"var(--text-2)", fontSize:"0.95rem", margin:0 }}>{msg}</p>
      </div>
    </div>
  );

  if (phase === PHASES.LOADING || phase === PHASES.GRADING) return <Spinner msg={statusMsg} />;

  if (phase === PHASES.ERROR) return (
    <div style={{ minHeight:"100vh", background:"var(--bg)", display:"flex", flexDirection:"column" }}>
      <OnboardingNav />
      <div style={{ flex:1, display:"flex", alignItems:"center", justifyContent:"center", padding:24 }}>
        <div style={{ textAlign:"center" }}>
          <div className="alert alert-error" style={{ marginBottom:16 }}>{error}</div>
          <button className="btn btn-grad" onClick={startQuiz}>Try again</button>
        </div>
      </div>
    </div>
  );

  if (phase === PHASES.DONE && results) {
    const pl = results.placement;
    return (
      <div style={{ minHeight:"100vh", background:"var(--bg)", display:"flex", flexDirection:"column" }}>
        <OnboardingNav />
        <div style={{ flex:1, display:"flex", flexDirection:"column", alignItems:"center", padding:"40px 20px" }}>
          <div style={{ width:"100%", maxWidth:680 }}>
            {/* Result header */}
            <div style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:16, padding:"28px 32px", marginBottom:20, textAlign:"center" }}>
              <div style={{ display:"inline-flex", alignItems:"center", gap:8, background:"rgba(99,102,241,0.15)", border:"1px solid rgba(99,102,241,0.35)", borderRadius:20, padding:"6px 18px", marginBottom:14 }}>
                <span style={{ color:"var(--primary-lt)", fontWeight:800, fontSize:"1.1rem" }}>Level {pl?.starting_level}</span>
                <span style={{ color:"var(--text-3)", fontSize:"0.82rem" }}>— Your Starting Point</span>
              </div>
              <h1 style={{ marginBottom:8 }}>Placement Complete! 🎉</h1>
              <p style={{ margin:0, fontSize:"0.95rem" }}>You scored <strong style={{ color:"#fff" }}>{results.total_score_percent}%</strong>. {pl?.reasoning}</p>
            </div>

            {/* Per-question breakdown */}
            <h2 style={{ marginBottom:14 }}>Question Breakdown</h2>
            {results.results.map(r => (
              <div key={r.question_number} style={{
                background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:10,
                padding:"16px 20px", marginBottom:10,
                borderLeft:`4px solid ${r.score_out_of_10 >= 7 ? "var(--success)" : r.score_out_of_10 >= 4 ? "var(--warning)" : "var(--danger)"}`,
              }}>
                <div style={{ display:"flex", justifyContent:"space-between", marginBottom:6 }}>
                  <span style={{ fontWeight:600, color:"#fff", fontSize:"0.9rem" }}>Q{r.question_number}. {r.question_text}</span>
                  <span style={{ fontWeight:800, color: r.score_out_of_10 >= 7 ? "var(--success)" : r.score_out_of_10 >= 4 ? "var(--warning)" : "var(--danger)", marginLeft:12, whiteSpace:"nowrap" }}>
                    {r.score_out_of_10}/10
                  </span>
                </div>
                <p style={{ margin:"0 0 4px", fontSize:"0.82rem", color:"var(--text-3)" }}>Your answer: <span style={{ color:"var(--text-2)" }}>{r.student_answer}</span></p>
                {r.correct_answer && <p style={{ margin:"0 0 4px", fontSize:"0.82rem", color:"var(--text-3)" }}>Correct: <span style={{ color:"var(--success)" }}>{r.correct_answer}</span></p>}
                <p style={{ margin:0, fontSize:"0.8rem", color:"var(--text-3)" }}>{r.feedback}</p>
              </div>
            ))}

            {results.knowledge_gaps?.length > 0 && (
              <div className="alert alert-info" style={{ marginTop:8 }}>
                <strong>Areas to strengthen:</strong> {results.knowledge_gaps.join(", ")}
              </div>
            )}

            <button className="btn btn-grad btn-full" style={{ marginTop:16 }} onClick={() => navigate("/dashboard")}>
              Go to My Dashboard →
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Answering UI
  const answered = session.questions.filter(q => (answers[q.id]||"").trim()).length;
  const total    = session.questions.length;

  return (
    <div style={{ minHeight:"100vh", background:"var(--bg)", display:"flex", flexDirection:"column" }}>
      <OnboardingNav />
      <div style={{ flex:1, display:"flex", flexDirection:"column", alignItems:"center", padding:"32px 20px" }}>
        {/* Step dots */}
        <div className="step-dots">{dots.map((s,i) => <div key={i} className={`step-dot ${s}`}/>)}</div>

        <div style={{ width:"100%", maxWidth:680 }}>
          {/* Header */}
          <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:6 }}>
            <h1 style={{ margin:0 }}>Placement Test</h1>
            <span style={{ background:"rgba(6,182,212,0.15)", border:"1px solid rgba(6,182,212,0.3)", color:"#67e8f9", borderRadius:20, padding:"4px 14px", fontSize:"0.82rem", fontWeight:700 }}>
              {answered}/{total} answered
            </span>
          </div>
          <p style={{ marginBottom:28 }}>Answer every question to the best of your ability. The AI uses your answers to decide your starting level.</p>

          {error && <div className="alert alert-error">{error}</div>}

          {/* Questions */}
          {session.questions.map(q => (
            <QuestionCard key={q.id} q={q} answer={answers[q.id]} onAnswer={val => setAnswer(q.id, val)} />
          ))}

          {/* Progress + Submit */}
          <div style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:12, padding:"16px 20px", marginTop:8 }}>
            <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:10 }}>
              <span style={{ color:"var(--text-3)", fontSize:"0.82rem" }}>{total - answered} questions remaining</span>
              <span style={{ color:"var(--text-3)", fontSize:"0.82rem" }}>{Math.round(answered/total*100)}% complete</span>
            </div>
            <div style={{ height:4, background:"rgba(255,255,255,0.08)", borderRadius:2, overflow:"hidden", marginBottom:16 }}>
              <div style={{ height:"100%", background:"var(--grad)", borderRadius:2, width:`${answered/total*100}%`, transition:"width 0.3s" }}/>
            </div>
            <button className="btn btn-grad btn-full btn-lg" onClick={handleSubmit} disabled={answered < total}>
              {answered < total ? `Answer all questions (${total - answered} remaining)` : "Submit & Get Results →"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}