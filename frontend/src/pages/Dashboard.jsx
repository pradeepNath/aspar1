import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../components/Navbar";
import api from "../utils/api";

export default function Dashboard() {
  const navigate = useNavigate();
  const [loading,      setLoading]      = useState(true);
  const [refreshing,   setRefreshing]   = useState(false);
  const [error,        setError]        = useState("");
  const [roadmap,      setRoadmap]      = useState(null);
  const [skillData,    setSkillData]    = useState(null);
  const [levelUpReady, setLevelUpReady] = useState(false);
  const [flagUnfit,    setFlagUnfit]    = useState(false);

  useEffect(() => { fetchAll(); }, []);

  async function refreshRoadmap() {
    setRefreshing(true);
    try {
      const res = await api.post("/roadmap/generate");
      setRoadmap(res.data);
    } catch (err) {
      setError(err.response?.data?.error || "Could not refresh roadmap.");
    } finally { setRefreshing(false); }
  }

  async function fetchAll() {
    setLoading(true); setError("");
    try {
      const [rmRes, skRes, prRes] = await Promise.all([
        api.get("/roadmap").catch(() => ({ data: null })),
        api.get("/skills/tree"),
        api.get("/progress/log").catch(() => ({ data: { progress_log: [] } })),
      ]);
      setRoadmap(rmRes.data);
      setSkillData(skRes.data);
      const lv = skRes.data.current_level;
      const lvSkills = (skRes.data.skills || []).filter(s => s.level === lv);
      setLevelUpReady(lvSkills.length > 0 && lvSkills.every(s => s.status === "learned"));

      // Same metric as the backend (routes/progress.py and
      // routes/career.py): consecutive recent level-up attempts that
      // scored below 80%, based on the actual score number rather than
      // the AI-chosen status label. Checking status === "eased" used to
      // under-count struggling students whenever a single attempt
      // happened to land on "retained" in between failures.
      const recentLog = (prRes.data?.progress_log || []).slice(-10).reverse();
      let failStreak = 0;
      for (const r of recentLog) {
        if (r.total_score != null && r.total_score < 80) failStreak++;
        else break;
      }
      setFlagUnfit(failStreak >= 3);
    } catch (err) {
      setError(err.response?.data?.error || "Could not load dashboard.");
    } finally { setLoading(false); }
  }

  if (loading) return <><Navbar /><div className="spinner-wrap" style={{ marginTop:100 }}><div className="spinner"/><span>Loading your dashboard…</span></div></>;

  const lv            = skillData?.current_level || 1;
  const skills        = skillData?.skills || [];
  const lvSkills      = skills.filter(s => s.level === lv);
  const prevSkills    = skills.filter(s => s.level < lv);
  const learnedCount  = lvSkills.filter(s => s.status === "learned").length;
  const user          = JSON.parse(localStorage.getItem("user") || "{}");

  // The skill tree (skillData) is always fresh - fetched on every
  // dashboard load - so it is the source of truth for which skill is
  // actually unlocked right now. The roadmap can occasionally lag
  // behind (e.g. if roadmap regeneration failed silently after a
  // skill test), so we cross-check: if the roadmap's current_skill
  // doesn't match the real unlocked skill, prefer the real one's name
  // and fall back to the roadmap's guidance text only when the names
  // do agree. If they disagree, the AI guidance is stale enough to be
  // misleading, so we show a lightweight "study this" prompt instead.
  const actualUnlockedSkill = lvSkills.find(s => s.status === "unlocked");
  const roadmapMatchesReality =
    !roadmap?.current_skill ||
    !actualUnlockedSkill ||
    roadmap.current_skill.skill_name === actualUnlockedSkill.skill_name;

  return (
    <>
      <Navbar />

      {/* Hero */}
      <div style={{ background: "linear-gradient(135deg, #0d1117 0%, #1a1a2e 60%, #13131f 100%)", borderBottom: "1px solid var(--border)", padding: "32px 28px 36px" }}>
        <div style={{ maxWidth: 1000, margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 16 }}>
          <div>
            <p style={{ color: "var(--text-3)", fontSize: "0.78rem", marginBottom: 4 }}>
              {new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
            </p>
            <h1 style={{ fontSize: "1.8rem", marginBottom: 4 }}>
              Welcome back, {user?.name?.split(" ")[0] || "Student"}! 👋
            </h1>
            <p style={{ margin: 0, color: "var(--text-2)" }}>Here's your learning journey at a glance.</p>
          </div>
          <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            {/* Level badge */}
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", width: 70, height: 70, borderRadius: "50%", border: "2px solid rgba(99,102,241,0.4)", background: "rgba(99,102,241,0.1)" }}>
              <span style={{ fontSize: "1.4rem", fontWeight: 900, color: "#fff", lineHeight: 1 }}>{lv}</span>
              <span style={{ fontSize: "0.6rem", color: "var(--text-3)", letterSpacing: "0.05em" }}>/ 5</span>
            </div>
            {/* Change Career — always visible */}
            <button onClick={() => navigate("/career-change")} className="btn btn-ghost btn-sm">
              🔄 Change Career
            </button>
          </div>
        </div>
      </div>

      <div className="main-layout">
        {error && <div className="alert alert-error">{error}</div>}

        {flagUnfit && (
          <div className="alert alert-warn" style={{ display:"flex", justifyContent:"space-between", alignItems:"center", flexWrap:"wrap", gap:12 }}>
            <span>⚠️ The AI suggests exploring alternative career paths based on your recent results.</span>
            <button className="btn btn-sm" style={{ background:"rgba(245,158,11,0.2)", border:"1px solid rgba(245,158,11,0.4)", color:"#fcd34d" }} onClick={() => navigate("/career-change")}>
              Explore alternatives →
            </button>
          </div>
        )}

        {skills.length === 0 && (
          <div style={{ background:"var(--bg-card)", border:"1px solid rgba(99,102,241,0.3)", borderRadius:14, padding:"28px", marginBottom:24, textAlign:"center" }}>
            <div style={{ fontSize:"2.5rem", marginBottom:12 }}>🚀</div>
            <h2 style={{ marginBottom:8 }}>Let's complete your setup!</h2>
            <p>You haven't taken your placement test yet. Finish setup to get your personalised skill tree and roadmap.</p>
            <button className="btn btn-grad" onClick={() => navigate("/setup/dream")}>Complete Setup →</button>
          </div>
        )}

        <div style={{ display:"flex", gap:20, flexWrap:"wrap" }}>

          {/* Roadmap */}
          <div style={{ flex:"1 1 340px" }}>
            <div className="card" style={{ height:"100%" }}>
              <div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:18 }}>
                <div style={{ width:34, height:34, borderRadius:9, background:"rgba(99,102,241,0.2)", display:"flex", alignItems:"center", justifyContent:"center" }}>📍</div>
                <h2 style={{ margin:0 }}>Your Roadmap</h2>
                {roadmap && <span style={{ marginLeft:"auto", fontSize:"0.72rem", color:"var(--text-3)", padding:"2px 8px", background:"var(--bg-card-2)", borderRadius:10, border:"1px solid var(--border)" }}>v{roadmap.version}</span>}
              </div>
              {roadmap ? (
                <>
                  <p style={{ lineHeight:1.75, color:"var(--text)", margin:"0 0 18px", fontSize:"0.9rem" }}>
                    {roadmap.overview}
                  </p>

                  {actualUnlockedSkill ? (
                    roadmapMatchesReality && roadmap.current_skill ? (
                      <div style={{
                        background:"rgba(99,102,241,0.07)",
                        border:"1px solid rgba(99,102,241,0.25)",
                        borderRadius:11, padding:"16px 18px",
                      }}>
                        <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:10 }}>
                          <span style={{ fontSize:"0.68rem", fontWeight:800, letterSpacing:"0.08em", color:"var(--primary-lt)", background:"rgba(99,102,241,0.18)", padding:"3px 9px", borderRadius:12 }}>
                            CURRENT SKILL
                          </span>
                          <span style={{ fontWeight:700, color:"#fff", fontSize:"0.92rem" }}>
                            {roadmap.current_skill.skill_name}
                          </span>
                        </div>

                        <p style={{ fontSize:"0.85rem", lineHeight:1.7, margin:"0 0 10px", color:"var(--text-2)" }}>
                          <span style={{ fontWeight:600, color:"var(--text)" }}>Why now: </span>
                          {roadmap.current_skill.why_now}
                        </p>

                        <p style={{ fontSize:"0.85rem", lineHeight:1.7, margin:"0 0 12px", color:"var(--text-2)" }}>
                          <span style={{ fontWeight:600, color:"var(--text)" }}>What to learn: </span>
                          {roadmap.current_skill.what_to_learn}
                        </p>

                        {roadmap.current_skill.resource_types?.length > 0 && (
                          <div>
                            <p style={{ fontSize:"0.68rem", fontWeight:700, letterSpacing:"0.08em", color:"var(--text-3)", marginBottom:7 }}>
                              LOOK FOR
                            </p>
                            <div style={{ display:"flex", gap:6, flexWrap:"wrap" }}>
                              {roadmap.current_skill.resource_types.map((rt,i) => (
                                <span key={i} style={{ background:"rgba(6,182,212,0.1)", color:"#67e8f9", border:"1px solid rgba(6,182,212,0.25)", borderRadius:20, padding:"3px 10px", fontSize:"0.78rem" }}>{rt}</span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      // Roadmap is stale/out of sync with the real unlocked
                      // skill (or has no current_skill at all) - fall back
                      // to a simple, always-accurate prompt rather than
                      // showing AI guidance about the wrong skill.
                      <div style={{
                        background:"rgba(99,102,241,0.07)",
                        border:"1px solid rgba(99,102,241,0.25)",
                        borderRadius:11, padding:"16px 18px",
                      }}>
                        <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:10 }}>
                          <span style={{ fontSize:"0.68rem", fontWeight:800, letterSpacing:"0.08em", color:"var(--primary-lt)", background:"rgba(99,102,241,0.18)", padding:"3px 9px", borderRadius:12 }}>
                            CURRENT SKILL
                          </span>
                          <span style={{ fontWeight:700, color:"#fff", fontSize:"0.92rem" }}>
                            {actualUnlockedSkill.skill_name}
                          </span>
                        </div>
                        <p style={{ fontSize:"0.85rem", lineHeight:1.7, margin:0, color:"var(--text-2)" }}>
                          This is your next skill to focus on. Refreshing the roadmap will pull in
                          a tailored explanation and resource suggestions for it.
                        </p>
                        <button
                          className="btn btn-grad btn-sm"
                          style={{ marginTop:12 }}
                          onClick={refreshRoadmap}
                          disabled={refreshing}
                        >
                          {refreshing ? "Refreshing…" : "Refresh roadmap →"}
                        </button>
                      </div>
                    )
                  ) : (
                    <div style={{ textAlign:"center", padding:"20px 0", color:"var(--text-3)", fontSize:"0.85rem" }}>
                      🎉 Every skill at this level is learned — take the Level-Up Test to continue.
                    </div>
                  )}
                </>
              ) : (
                <div style={{ textAlign:"center", padding:"32px 0", color:"var(--text-3)" }}>
                  <div style={{ fontSize:"2rem", marginBottom:8 }}>🗺️</div>
                  <p style={{ margin:0 }}>No roadmap yet. Complete the placement test first.</p>
                </div>
              )}
            </div>
          </div>

          {/* Skills */}
          <div style={{ flex:"1 1 280px" }}>
            <div className="card">
              <div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:16 }}>
                <div style={{ width:34, height:34, borderRadius:9, background:"rgba(16,185,129,0.15)", display:"flex", alignItems:"center", justifyContent:"center" }}>🎯</div>
                <h2 style={{ margin:0 }}>Level {lv} Skills</h2>
              </div>

              {/* Progress bar */}
              {lvSkills.length > 0 && (
                <div style={{ marginBottom:16 }}>
                  <div style={{ display:"flex", justifyContent:"space-between", fontSize:"0.75rem", color:"var(--text-3)", marginBottom:6 }}>
                    <span>Progress</span><span>{learnedCount}/{lvSkills.length} learned</span>
                  </div>
                  <div style={{ height:5, background:"rgba(255,255,255,0.08)", borderRadius:3, overflow:"hidden" }}>
                    <div style={{ height:"100%", borderRadius:3, background:"var(--grad)", width:`${lvSkills.length ? learnedCount/lvSkills.length*100 : 0}%`, transition:"width 0.4s ease" }}/>
                  </div>
                </div>
              )}

              {/* Prev skills */}
              {prevSkills.length > 0 && (
                <div style={{ marginBottom:14, padding:"10px 12px", background:"rgba(16,185,129,0.07)", borderRadius:8, border:"1px solid rgba(16,185,129,0.2)" }}>
                  <p style={{ fontSize:"0.7rem", fontWeight:700, letterSpacing:"0.08em", color:"var(--success)", margin:"0 0 6px" }}>COMPLETED</p>
                  <div style={{ display:"flex", flexWrap:"wrap", gap:4 }}>
                    {prevSkills.map(s=><span key={s.id} style={{ fontSize:"0.78rem", color:"var(--success)", display:"flex", alignItems:"center", gap:3 }}>✓ {s.skill_name}</span>)}
                  </div>
                </div>
              )}

              <div style={{ display:"flex", flexDirection:"column", gap:8, marginBottom:16 }}>
                {lvSkills.length === 0 && <p style={{ color:"var(--text-3)", fontSize:"0.88rem" }}>No skills loaded yet.</p>}
                {lvSkills.map(s => (
                  <div key={s.id} className={`skill-card ${s.status}`} style={{ display:"flex", alignItems:"center", justifyContent:"space-between" }}>
                    <div>
                      <div style={{ fontWeight:600, fontSize:"0.88rem", color:"#fff" }}>{s.skill_name}</div>
                      <div style={{ fontSize:"0.73rem", color:"var(--text-3)" }}>{s.category}</div>
                    </div>
                    <div style={{ display:"flex", gap:8, alignItems:"center" }}>
                      {s.status==="learned"  && <span style={{ color:"var(--success)", fontWeight:800 }}>✓</span>}
                      {s.status==="locked"   && <span style={{ fontSize:"0.9rem" }}>🔒</span>}
                      {s.status==="unlocked" && (
                        <button className="btn btn-grad btn-sm" style={{ fontSize:"0.75rem", padding:"5px 12px" }}
                          onClick={() => navigate("/quiz", { state:{ test_type:"skill_test", skill_id:s.id } })}>
                          Test →
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              <button
                onClick={() => navigate("/quiz", { state:{ test_type:"level_up" } })}
                disabled={!levelUpReady}
                className={`btn btn-full ${levelUpReady ? "btn-success-soft" : "btn-ghost"}`}
                style={{ fontWeight:700 }}
              >
                {levelUpReady ? "🚀 Take Level-Up Test" : `🔒 Level-Up Test (${lvSkills.length - learnedCount} skills left)`}
              </button>
            </div>
          </div>
        </div>

        {/* Quick links */}
        <div style={{ display:"flex", gap:10, marginTop:20, flexWrap:"wrap" }}>
          {[
            ["🌳 Full Skill Tree",       "/skills"],
            ["📈 Progress & Scores",     "/progress"],
            ["📚 Add Academic Results",  "/academics/add"],
          ].map(([label,path])=>(
            <button key={path} onClick={()=>navigate(path)} className="btn btn-ghost btn-sm">{label}</button>
          ))}
        </div>
      </div>
    </>
  );
}