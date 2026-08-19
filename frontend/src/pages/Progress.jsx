import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer } from "recharts";
import Navbar from "../components/Navbar";
import api from "../utils/api";

// Custom dark tooltip for recharts
const DarkTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:8, padding:"10px 14px", fontSize:"0.85rem" }}>
      <p style={{ color:"var(--text-3)", margin:"0 0 4px" }}>Attempt {label}</p>
      <p style={{ color:"#fff", fontWeight:700, margin:0 }}>{payload[0].value}%</p>
    </div>
  );
};

const CustomDot = ({ cx, cy, payload }) => {
  const colors = { leveled_up:"#10b981", retained:"#6366f1", eased:"#f59e0b" };
  const fill = colors[payload?.status] || "#6366f1";
  return <circle cx={cx} cy={cy} r={5} fill={fill} stroke="var(--bg)" strokeWidth={2}/>;
};

export default function Progress() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState("");
  const [data,    setData]    = useState(null);
  const [skillData, setSkillData] = useState(null);

  useEffect(() => { fetchProgress(); }, []);

  async function fetchProgress() {
    setLoading(true); setError("");
    try {
      const [progressRes, skillsRes] = await Promise.all([
        api.get("/progress/log"),
        api.get("/skills/tree"),
      ]);
      setData(progressRes.data);
      setSkillData(skillsRes.data);
    } catch (err) {
      setError(err.response?.data?.error || "Could not load progress.");
    } finally { setLoading(false); }
  }

  if (loading) return (
    <><Navbar />
    <div className="spinner-wrap" style={{ marginTop:100 }}><div className="spinner"/><span>Loading progress…</span></div></>
  );

  const currentLevel  = data?.current_level || 1;
  const log           = data?.progress_log  || [];
  const learnedSkills = data?.learned_skills || [];
  const skills = skillData?.skills || [];
  const currentSkills = skills.filter(skill => skill.level === currentLevel);
  const completedAtLevel = currentSkills.filter(skill => skill.status === "learned").length;
  const currentSkill = currentSkills.find(skill => skill.status === "unlocked");
  const progressPercent = currentSkills.length ? Math.round(completedAtLevel / currentSkills.length * 100) : 0;
  const levelHistory = [1, 2, 3, 4, 5];

  const chartData = log.map((row, i) => ({
    attempt: row.attempt_number || i + 1,
    score:   row.total_score,
    status:  row.status,
  }));

  const byLevel = {};
  learnedSkills.forEach(s => {
    if (!byLevel[s.level]) byLevel[s.level] = [];
    byLevel[s.level].push(s);
  });

  return (
    <><Navbar />
    <div className="main-layout" style={{ maxWidth:1080 }}>

      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", gap:20, flexWrap:"wrap", marginBottom:24 }}>
        <div>
          <h1>Progress</h1>
          <p style={{ margin:0 }}>See what you have mastered and what moves your journey forward.</p>
        </div>
        <div style={{ background:"rgba(99,102,241,0.15)", border:"1px solid rgba(99,102,241,0.35)", borderRadius:20, padding:"8px 20px", fontWeight:800, color:"var(--primary-lt)", fontSize:"0.95rem" }}>
          Level {currentLevel} / 5
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fit, minmax(210px, 1fr))", gap:12, marginBottom:20 }}>
        {[
          ["CURRENT LEVEL", `Level ${currentLevel}`, "Your active stage", "#a5b4fc"],
          ["SKILLS MASTERED", `${learnedSkills.length}`, `${completedAtLevel}/${currentSkills.length || 0} at this level`, "#6ee7b7"],
          ["LEVEL PROGRESS", `${progressPercent}%`, `${Math.max(currentSkills.length - completedAtLevel, 0)} skills left`, "#67e8f9"],
        ].map(([label, value, detail, color]) => (
          <div key={label} style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:12, padding:"15px 17px" }}>
            <div style={{ color:"var(--text-3)", fontSize:"0.66rem", fontWeight:800, letterSpacing:".09em" }}>{label}</div>
            <div style={{ color, fontSize:"1.45rem", fontWeight:850, lineHeight:1.25, marginTop:4 }}>{value}</div>
            <div style={{ color:"var(--text-2)", fontSize:".75rem", marginTop:2 }}>{detail}</div>
          </div>
        ))}
      </div>

      <div style={{ display:"grid", gridTemplateColumns:"minmax(0, 1.2fr) minmax(280px, .8fr)", gap:20, marginBottom:20 }}>
        <section style={{ background:"linear-gradient(135deg, rgba(99,102,241,.14), rgba(19,19,31,.95) 55%)", border:"1px solid rgba(129,140,248,.3)", borderRadius:14, padding:"22px 24px" }}>
          <div style={{ display:"flex", justifyContent:"space-between", gap:12, alignItems:"flex-start", marginBottom:16 }}>
            <div>
              <div style={{ color:"#a5b4fc", fontSize:".68rem", fontWeight:800, letterSpacing:".09em", marginBottom:4 }}>YOUR CURRENT MILESTONE</div>
              <h2 style={{ margin:0 }}>{currentSkill ? currentSkill.skill_name : `Complete Level ${currentLevel}`}</h2>
            </div>
            <span style={{ color:"#c4b5fd", background:"rgba(99,102,241,.18)", borderRadius:20, padding:"4px 10px", fontSize:".72rem", fontWeight:700, whiteSpace:"nowrap" }}>{completedAtLevel}/{currentSkills.length || 0} complete</span>
          </div>
          <p style={{ fontSize:".84rem", lineHeight:1.6, margin:"0 0 13px", color:"var(--text-2)" }}>
            {currentSkill
              ? `Focus on ${currentSkill.skill_name} next. Passing its skill test unlocks the next step in your Level ${currentLevel} path.`
              : `Every available skill at this level is complete. You are ready to prove your level-up knowledge.`}
          </p>
          <div style={{ height:8, overflow:"hidden", borderRadius:10, background:"rgba(255,255,255,.08)", marginBottom:15 }}>
            <div style={{ height:"100%", width:`${progressPercent}%`, minWidth:progressPercent ? 8 : 0, background:"var(--grad)", borderRadius:10, transition:"width .4s ease" }}/>
          </div>
          {currentSkill ? (
            <button className="btn btn-grad btn-sm" onClick={() => navigate("/quiz", { state:{ test_type:"skill_test", skill_id:currentSkill.id } })}>Continue skill →</button>
          ) : (
            <button className="btn btn-success-soft btn-sm" onClick={() => navigate("/quiz", { state:{ test_type:"level_up" } })}>Take Level-Up Test →</button>
          )}
        </section>

        <section style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:14, padding:"22px 20px" }}>
          <div style={{ color:"var(--text-3)", fontSize:".68rem", fontWeight:800, letterSpacing:".09em", marginBottom:15 }}>YOUR JOURNEY</div>
          <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", gap:4 }}>
            {levelHistory.map(level => {
              const state = level < currentLevel ? "done" : level === currentLevel ? "active" : "locked";
              const colors = { done:"#10b981", active:"#818cf8", locked:"#334155" };
              return <div key={level} style={{ display:"flex", flexDirection:"column", alignItems:"center", flex:1, position:"relative" }}>
                {level < 5 && <div style={{ position:"absolute", top:14, left:"60%", width:"80%", height:2, background:level < currentLevel ? "rgba(16,185,129,.5)" : "rgba(255,255,255,.08)" }}/>} 
                <div style={{ position:"relative", zIndex:1, display:"grid", placeItems:"center", width:30, height:30, borderRadius:"50%", background:`${colors[state]}22`, border:`1px solid ${colors[state]}`, color:colors[state], fontSize:".72rem", fontWeight:800 }}>{state === "done" ? "✓" : level}</div>
                <span style={{ color:state === "active" ? "#c4b5fd" : "var(--text-3)", fontSize:".62rem", marginTop:5, fontWeight:700 }}>L{level}</span>
              </div>;
            })}
          </div>
          <p style={{ margin:"16px 0 0", color:"var(--text-2)", fontSize:".77rem", lineHeight:1.5 }}>Complete all skills in a level, then pass its Level-Up Test to advance.</p>
        </section>
      </div>

      <div style={{ display:"grid", gridTemplateColumns:"minmax(0, 1.2fr) minmax(280px, .8fr)", gap:20 }}>
      {/* Score chart */}
      <div style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:14, padding:"22px 24px" }}>
        <h2 style={{ marginBottom:4 }}>Level-Up History</h2>
        <p style={{ fontSize:".8rem", margin:"0 0 14px" }}>Your scores after completing a full level.</p>

        {chartData.length === 0 ? (
          <div style={{ textAlign:"center", padding:"40px 0", color:"var(--text-3)" }}>
            <div style={{ fontSize:"2.5rem", marginBottom:8 }}>📊</div>
            <p style={{ margin:0 }}>No level-up tests taken yet. Complete all skills at your current level to unlock the test.</p>
          </div>
        ) : (
          <>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={chartData} margin={{ top:10, right:20, left:0, bottom:10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)"/>
                <XAxis dataKey="attempt" tick={{ fill:"var(--text-3)", fontSize:12 }} label={{ value:"Attempt #", position:"insideBottom", offset:-4, fill:"var(--text-3)", fontSize:11 }}/>
                <YAxis domain={[0,100]} tickFormatter={v=>`${v}%`} tick={{ fill:"var(--text-3)", fontSize:12 }}/>
                <Tooltip content={<DarkTooltip/>}/>
                <ReferenceLine y={80} stroke="rgba(16,185,129,0.5)" strokeDasharray="5 5" label={{ value:"Pass 80%", position:"right", fill:"#10b981", fontSize:11 }}/>
                <Line type="monotone" dataKey="score" stroke="var(--primary)" strokeWidth={2.5} dot={<CustomDot/>} activeDot={{ r:7, fill:"var(--primary)" }}/>
              </LineChart>
            </ResponsiveContainer>

            {/* Legend */}
            <div style={{ display:"flex", gap:18, marginTop:12, flexWrap:"wrap" }}>
              {[["Levelled up","#10b981"],["Retained","#6366f1"],["Roadmap eased","#f59e0b"]].map(([label,color])=>(
                <div key={label} style={{ display:"flex", alignItems:"center", gap:6, fontSize:"0.8rem", color:"var(--text-3)" }}>
                  <div style={{ width:8, height:8, borderRadius:"50%", background:color }}/>{label}
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Learned skills */}
      <div style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:14, padding:"22px 20px" }}>
        <h2 style={{ marginBottom:4 }}>Mastered Skills</h2>
        <p style={{ fontSize:".8rem", margin:"0 0 14px" }}>{learnedSkills.length} skills completed so far.</p>

        {learnedSkills.length === 0 ? (
          <div style={{ textAlign:"center", padding:"32px 0", color:"var(--text-3)" }}>
            <div style={{ fontSize:"2rem", marginBottom:8 }}>🎯</div>
            <p style={{ margin:0 }}>No skills learned yet. Start with your first skill test on the Dashboard.</p>
          </div>
        ) : (
          Object.entries(byLevel).sort(([a],[b])=>Number(a)-Number(b)).map(([lv, lvSkills])=>(
            <div key={lv} style={{ marginBottom:20 }}>
              <p style={{ fontSize:"0.72rem", fontWeight:700, letterSpacing:"0.1em", color:"var(--text-3)", marginBottom:10 }}>
                LEVEL {lv}
              </p>
              <div style={{ display:"flex", flexWrap:"wrap", gap:8 }}>
                {lvSkills.map(s => (
                  <div key={s.skill_id} style={{
                    display:"flex", alignItems:"center", gap:6,
                    padding:"6px 14px", borderRadius:20,
                    background:"rgba(16,185,129,0.1)",
                    border:"1px solid rgba(16,185,129,0.25)",
                    fontSize:"0.84rem", color:"#6ee7b7", fontWeight:500,
                  }}>
                    <span style={{ fontWeight:800 }}>✓</span>
                    <span style={{ color:"#fff" }}>{s.skill_name}</span>
                    <span style={{ color:"var(--text-3)", fontSize:"0.75rem" }}>· {s.category}</span>
                  </div>
                ))}
              </div>
            </div>
          ))
        )}
      </div>
      </div>

      <button className="btn btn-ghost btn-sm mt-16" onClick={() => navigate("/dashboard")}>← Back to Dashboard</button>
    </div></>
  );
}
