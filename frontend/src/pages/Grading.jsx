import { useNavigate, useLocation } from "react-router-dom";
import Navbar from "../components/Navbar";

export default function Grading() {
  const navigate = useNavigate();
  const location = useLocation();
  const { grading, test_type, skillResult, progressResult } = location.state || {};

  if (!grading) { navigate("/dashboard"); return null; }

  const score  = grading.total_score_percent || 0;
  const passed = score >= 80;
  const gaps   = grading.knowledge_gaps || [];

  // Banner config
  let bannerBg    = passed ? "rgba(16,185,129,0.12)" : "rgba(239,68,68,0.12)";
  let bannerBorder= passed ? "rgba(16,185,129,0.3)"  : "rgba(239,68,68,0.3)";
  let bannerColor = passed ? "#6ee7b7" : "#fca5a5";
  let bannerTitle = passed ? `${score}% — Passed! 🎉` : `${score}% — Not passed yet`;
  let bannerMsg   = "";

  if (test_type === "skill_test") {
    if (passed && skillResult?.next_skill)   bannerMsg = `Skill learned! Next up: "${skillResult.next_skill.skill_name}"`;
    else if (passed && !skillResult?.next_skill) bannerMsg = "All skills at this level learned! Take the Level-Up Test when ready.";
    else bannerMsg = "You need ≥80% to mark this skill as learned. Review feedback and retry after 4 hours.";
  } else if (test_type === "level_up" && progressResult) {
    const d = progressResult.decision;
    if (d === "level_up")       { bannerMsg = `🚀 Advanced to Level ${progressResult.new_level}! Your roadmap has been updated.`; }
    else if (d === "retain")    { bannerMsg = "Good progress! Keep practising — you need ≥80% to level up."; }
    else if (d === "ease_roadmap") { bannerMsg = "Your roadmap has been adjusted to better support your learning."; }
    else if (d === "flag_unfit")   { bannerBg = "rgba(245,158,11,0.12)"; bannerBorder = "rgba(245,158,11,0.3)"; bannerColor = "#fcd34d"; bannerMsg = "The AI suggests exploring alternative career paths."; }
    if (progressResult.reasoning) bannerMsg += " " + progressResult.reasoning;
  }

  return (
    <><Navbar />
    <div className="main-layout" style={{ maxWidth:720 }}>

      {/* Banner */}
      <div style={{ background:bannerBg, border:`1px solid ${bannerBorder}`, borderRadius:12, padding:"20px 24px", marginBottom:20 }}>
        <h2 style={{ color:bannerColor, margin:"0 0 6px", fontSize:"1.2rem" }}>{bannerTitle}</h2>
        {bannerMsg && <p style={{ margin:0, color:"var(--text-2)", fontSize:"0.9rem", lineHeight:1.6 }}>{bannerMsg}</p>}
      </div>

      {/* Knowledge gaps */}
      {gaps.length > 0 && (
        <div className="alert alert-info" style={{ marginBottom:20 }}>
          <strong>Areas to revisit:</strong> {gaps.join(", ")}
        </div>
      )}

      {/* Question breakdown */}
      <h2 style={{ marginBottom:14 }}>Question Breakdown</h2>
      <div style={{ display:"flex", flexDirection:"column", gap:10, marginBottom:24 }}>
        {(grading.results||[]).map(r => {
          const scoreColor = r.score_out_of_10 >= 7 ? "var(--success)" : r.score_out_of_10 >= 4 ? "var(--warning)" : "var(--danger)";
          return (
            <div key={r.question_number} style={{
              background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:10, padding:"16px 20px",
              borderLeft:`4px solid ${scoreColor}`,
            }}>
              <div style={{ display:"flex", justifyContent:"space-between", marginBottom:8 }}>
                <span style={{ fontWeight:700, color:"#fff", fontSize:"0.9rem", flex:1, marginRight:12 }}>
                  Q{r.question_number}. {r.question_text}
                </span>
                <span style={{ fontWeight:800, color:scoreColor, whiteSpace:"nowrap" }}>{r.score_out_of_10}/10</span>
              </div>
              <p style={{ margin:"0 0 3px", fontSize:"0.82rem", color:"var(--text-3)" }}>
                Your answer: <span style={{ color:"var(--text-2)" }}>{r.student_answer}</span>
              </p>
              {r.correct_answer && (
                <p style={{ margin:"0 0 3px", fontSize:"0.82rem", color:"var(--text-3)" }}>
                  Correct: <span style={{ color:"var(--success)" }}>{r.correct_answer}</span>
                </p>
              )}
              <p style={{ margin:0, fontSize:"0.8rem", color:"var(--text-3)" }}>{r.feedback}</p>
            </div>
          );
        })}
      </div>

      {/* Actions */}
      <div style={{ display:"flex", gap:12, flexWrap:"wrap" }}>
        <button className="btn btn-grad" onClick={() => navigate("/dashboard")}>Back to Dashboard</button>
        {test_type === "level_up" && progressResult?.decision === "flag_unfit" && (
          <button className="btn btn-danger" onClick={() => navigate("/career-change")}>Explore Alternative Careers</button>
        )}
        {test_type === "level_up" && progressResult?.decision === "level_up" && (
          <button className="btn btn-success-soft" onClick={() => navigate("/skills")}>See New Skill Tree →</button>
        )}
        <button className="btn btn-ghost" onClick={() => navigate("/progress")}>View Progress Graph</button>
      </div>
    </div></>
  );
}