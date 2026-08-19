import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../components/Navbar";
import api from "../utils/api";

export default function SkillTree() {
  const navigate = useNavigate();
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState("");
  const [skillData, setSkillData] = useState(null);
  const [expandedSkills, setExpandedSkills] = useState({});

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
  const personalizedSubskills = skillData?.personalized_subskills || [];

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
    <div className="main-layout skill-tree-page">

      <div className="skill-tree-heading">
        <div>
          <h1>Skill Tree</h1>
          <p>Your personalised learning path — level by level.</p>
        </div>
        <div className="tree-progress-badge">
          Level {currentLevel} / 5
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {skills.length > 0 && <div className="skill-tree-canvas">
        <div className="tree-root" aria-hidden="true"><span>✦</span><small>Your path</small></div>

      {levels.map((lv, levelIndex) => {
        const isCurrentLv = lv === currentLevel;
        const isDone      = lv < currentLevel;

        return (
          <section key={lv} className={`tree-level ${isCurrentLv ? "is-current" : ""} ${isDone ? "is-complete" : ""}`}>
            <div className="tree-level-marker">
              <span>Level {lv}</span>
              {isCurrentLv && (
                <em>CURRENT</em>
              )}
              {isDone && <em>✓ Completed</em>}
            </div>

            <div className="tree-categories">
            {Object.entries(byLevel[lv]).map(([category, catSkills]) => (
              <div key={category} className="tree-category">
                <div className="tree-category-label">{category}</div>
                <div className="tree-core-skills">
                  {[...catSkills].sort((a,b) => a.sequence_order - b.sequence_order).map(s => {
                    const cfg = statusCfg[s.status] || statusCfg.locked;
                    const childSubskills = personalizedSubskills.filter(sub => sub.parent_skill_id === s.id);
                    const isExpanded = expandedSkills[s.id];
                    return (
                      <div key={s.id} className={`tree-core ${s.status} ${isExpanded ? "is-expanded" : ""}`}>
                        <div className="tree-core-node">
                          <div className="tree-skill-title">
                            <span>{s.skill_name}</span>
                            <span>{cfg.icon}</span>
                          </div>
                          <span className="tree-status" style={{ color:cfg.color }}>
                            {cfg.label}
                          </span>
                          <div className="tree-core-actions">
                            {s.status === "unlocked" && (
                              <button
                                className="btn btn-grad btn-sm"
                                onClick={() => navigate("/quiz", { state:{ test_type:"skill_test", skill_id:s.id } })}
                              >
                                Take test →
                              </button>
                            )}
                            {childSubskills.length > 0 && (
                              <button
                                className="tree-expand-btn"
                                type="button"
                                aria-expanded={Boolean(isExpanded)}
                                onClick={() => setExpandedSkills(current => ({ ...current, [s.id]: !current[s.id] }))}
                              >
                                <span>{isExpanded ? "−" : "+"}</span>
                                {isExpanded ? "Hide practice branches" : `Show ${childSubskills.length} practice branch${childSubskills.length === 1 ? "" : "es"}`}
                              </button>
                            )}
                          </div>
                        </div>

                        {/* Learner-specific remediation subskills. These are
                            returned separately by /skills/tree and must not
                            be mixed into the shared core skill list. */}
                        {isExpanded && childSubskills.length > 0 && (
                          <div className="tree-subskill-branches">
                          {childSubskills.map(sub => (
                            <div key={`subskill-${sub.id}`} className="tree-subskill">
                              <div className="tree-subskill-top">
                                <div>
                                  <div className="tree-subskill-label">
                                    PERSONALIZED SUBSKILL
                                  </div>
                                  <div className="tree-subskill-name">
                                    {sub.skill_name}
                                  </div>
                                  {sub.concept && (
                                    <div className="tree-subskill-concept">
                                      Gap: {sub.concept}
                                    </div>
                                  )}
                                </div>
                                <span className="tree-subskill-icon" style={{ color: sub.status === "learned" ? "var(--success)" : "#fbbf24" }}>
                                  {sub.status === "learned" ? "✓" : "⚠"}
                                </span>
                              </div>

                              {sub.reason && (
                                <p className="tree-subskill-reason">
                                  {sub.reason}
                                </p>
                              )}

                              {sub.status === "unlocked" && (
                                <button
                                  className="btn btn-sm"
                                  style={{ background:"rgba(245,158,11,0.15)", border:"1px solid rgba(245,158,11,0.35)", color:"#fcd34d" }}
                                  onClick={() => navigate("/quiz", {
                                    state:{
                                      test_type:"skill_test",
                                      skill_id:s.id,
                                      adaptive_skill_id:sub.id,
                                    },
                                  })}
                                >
                                  Practice subskill →
                                </button>
                              )}
                            </div>
                          ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
            </div>
            {levelIndex < levels.length - 1 && <div className="tree-trunk-segment" aria-hidden="true" />}
          </section>
        );
      })}
      </div>}

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
