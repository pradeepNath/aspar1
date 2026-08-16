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

  useEffect(() => { fetchProgress(); }, []);

  async function fetchProgress() {
    setLoading(true); setError("");
    try {
      const res = await api.get("/progress/log");
      setData(res.data);
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
    <div className="main-layout">

      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:28 }}>
        <div>
          <h1>Progress</h1>
          <p style={{ margin:0 }}>Track your level-up test scores over time.</p>
        </div>
        <div style={{ background:"rgba(99,102,241,0.15)", border:"1px solid rgba(99,102,241,0.35)", borderRadius:20, padding:"8px 20px", fontWeight:800, color:"var(--primary-lt)", fontSize:"0.95rem" }}>
          Level {currentLevel} / 5
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {/* Score chart */}
      <div style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:14, padding:"24px 28px", marginBottom:20 }}>
        <h2 style={{ marginBottom:4 }}>Level-Up Test Scores</h2>

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
      <div style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:14, padding:"24px 28px" }}>
        <h2 style={{ marginBottom:16 }}>Learned Skills ({learnedSkills.length})</h2>

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

      <button className="btn btn-ghost btn-sm mt-16" onClick={() => navigate("/dashboard")}>← Back to Dashboard</button>
    </div></>
  );
}