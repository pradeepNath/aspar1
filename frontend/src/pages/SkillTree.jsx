import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../components/Navbar";
import api from "../utils/api";

export default function SkillTree() {
  const navigate = useNavigate();
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState("");
  const [skillData, setSkillData] = useState(null);

  useEffect(() => { fetchTree(); }, []);

  async function fetchTree() {
    setLoading(true); setError("");
    try {
      const res = await api.get("/skills/tree");
      setSkillData(res.data);
    } catch (err) {
      setError(err.response?.data?.error || "Could not load skill tree.");
    } finally { setLoading(false); }
  }

  if (loading) return (
    <><Navbar />
    <div className="spinner-wrap" style={{ marginTop:100 }}><div className="spinner"/><span>Loading skill tree…</span></div></>
  );

  const currentLevel = skillData?.current_level || 1;
  const skills       = skillData?.skills || [];

  // Group by level → category
  const byLevel = {};
  skills.forEach(s => {
    if (!byLevel[s.level]) byLevel[s.level] = {};
    if (!byLevel[s.level][s.category]) byLevel[s.level][s.category] = [];
    byLevel[s.level][s.category].push(s);
  });
  const levels = Object.keys(byLevel).map(Number).sort((a,b) => a-b);

  const statusCfg = {
    learned:  { label:"Learned",     color:"var(--success)",  bg:"rgba(16,185,129,0.08)",  border:"rgba(16,185,129,0.25)", icon:"✓" },
    unlocked: { label:"In progress", color:"#67e8f9",         bg:"rgba(6,182,212,0.08)",   border:"rgba(6,182,212,0.25)",  icon:"▶" },
    locked:   { label:"Locked",      color:"var(--text-3)",   bg:"rgba(255,255,255,0.02)", border:"rgba(255,255,255,0.06)",icon:"🔒" },
  };

  return (
    <><Navbar />
    <div className="main-layout">

      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:28 }}>
        <div>
          <h1>Skill Tree</h1>
          <p style={{ margin:0 }}>Your personalised learning path — level by level.</p>
        </div>
        <div style={{ background:"rgba(99,102,241,0.15)", border:"1px solid rgba(99,102,241,0.35)", borderRadius:20, padding:"8px 20px", fontWeight:800, color:"var(--primary-lt)", fontSize:"0.95rem", whiteSpace:"nowrap" }}>
          Level {currentLevel} / 5
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {levels.map(lv => {
        const isCurrentLv = lv === currentLevel;
        const isDone      = lv < currentLevel;

        return (
          <div key={lv} style={{ marginBottom:36 }}>
            {/* Level header */}
            <div style={{
              display:"flex", alignItems:"center", gap:12, marginBottom:18,
              padding:"12px 20px", borderRadius:10,
              background: isCurrentLv ? "rgba(99,102,241,0.12)" : isDone ? "rgba(16,185,129,0.08)" : "rgba(255,255,255,0.03)",
              border:"1px solid",
              borderColor: isCurrentLv ? "rgba(99,102,241,0.35)" : isDone ? "rgba(16,185,129,0.25)" : "var(--border)",
            }}>
              <span style={{ fontWeight:800, fontSize:"1rem", color: isCurrentLv ? "var(--primary-lt)" : isDone ? "var(--success)" : "var(--text-3)" }}>
                Level {lv}
              </span>
              {isCurrentLv && (
                <span style={{ background:"rgba(99,102,241,0.25)", color:"var(--primary-lt)", borderRadius:10, padding:"2px 10px", fontSize:"0.72rem", fontWeight:700, letterSpacing:"0.06em" }}>
                  CURRENT
                </span>
              )}
              {isDone && <span style={{ color:"var(--success)", fontSize:"0.82rem", fontWeight:600 }}>✓ Completed</span>}
            </div>

            {Object.entries(byLevel[lv]).map(([category, catSkills]) => (
              <div key={category} style={{ marginBottom:18 }}>
                <p style={{ fontSize:"0.72rem", fontWeight:700, letterSpacing:"0.1em", color:"var(--text-3)", marginBottom:10, paddingLeft:2 }}>
                  {category.toUpperCase()}
                </p>
                <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(200px, 1fr))", gap:10 }}>
                  {catSkills.sort((a,b) => a.sequence_order - b.sequence_order).map(s => {
                    const cfg = statusCfg[s.status] || statusCfg.locked;
                    return (
                      <div key={s.id} style={{
                        background: cfg.bg,
                        border:`1.5px solid ${cfg.border}`,
                        borderRadius:10, padding:"14px 16px",
                        display:"flex", flexDirection:"column", gap:8,
                        opacity: s.status === "locked" ? 0.55 : 1,
                        transition:"all 0.2s",
                      }}>
                        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", gap:8 }}>
                          <span style={{ fontWeight:700, fontSize:"0.88rem", color:"#fff", lineHeight:1.3 }}>{s.skill_name}</span>
                          <span style={{ fontSize:"1rem", flexShrink:0 }}>{cfg.icon}</span>
                        </div>
                        <span style={{ display:"inline-block", alignSelf:"flex-start", background:`${cfg.bg}`, border:`1px solid ${cfg.border}`, color:cfg.color, borderRadius:12, padding:"2px 9px", fontSize:"0.72rem", fontWeight:700 }}>
                          {cfg.label}
                        </span>
                        {s.status === "unlocked" && (
                          <button
                            className="btn btn-grad btn-sm"
                            style={{ marginTop:2, fontSize:"0.78rem", padding:"7px 14px" }}
                            onClick={() => navigate("/quiz", { state:{ test_type:"skill_test", skill_id:s.id } })}
                          >
                            Take test →
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        );
      })}

      {skills.length === 0 && !error && (
        <div style={{ textAlign:"center", padding:"60px 20px", color:"var(--text-3)" }}>
          <div style={{ fontSize:"3rem", marginBottom:12 }}>🌱</div>
          <p>No skills yet. Complete your placement test to generate your skill tree.</p>
          <button className="btn btn-grad" onClick={() => navigate("/setup/placement")}>Take Placement Test</button>
        </div>
      )}
    </div></>
  );
}