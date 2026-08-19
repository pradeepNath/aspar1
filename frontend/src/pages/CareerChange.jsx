import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../components/Navbar";
import api from "../utils/api";

const STEP = { CONFIRM:"confirm", LOADING:"loading", SUGGESTIONS:"suggestions", REVIEW:"review", SWITCHING:"switching" };

export default function CareerChange() {
  const navigate = useNavigate();
  const [step,         setStep]         = useState(STEP.CONFIRM);
  const [alternatives, setAlternatives] = useState([]);
  const [selectedCareer, setSelectedCareer] = useState(null);
  const [error,        setError]        = useState("");
  const [switching,    setSwitching]    = useState(false);

  async function handleYes() {
    setError(""); setStep(STEP.LOADING);
    try {
      const res = await api.post("/career/suggest");
      setAlternatives(res.data.alternatives || []);
      setStep(STEP.SUGGESTIONS);
    } catch (err) {
      setError(err.response?.data?.error || "Could not load suggestions.");
      setStep(STEP.CONFIRM);
    }
  }

  async function handleSwitch() {
    if (!selectedCareer) return;
    setError(""); setSwitching(true);
    try {
      await api.post("/career/switch", { new_career: selectedCareer.career });
      navigate("/setup/placement", { state:{ message:`Your ${selectedCareer.career} placement is ready—let’s find the right starting point.` } });
    } catch (err) {
      setError(err.response?.data?.error || "Could not switch career.");
    } finally { setSwitching(false); }
  }

  if (step === STEP.LOADING || switching) return (
    <><Navbar />
    <div className="spinner-wrap" style={{ marginTop:100 }}>
      <div className="spinner"/><span>{switching ? "Switching career…" : "Finding the best matches for you…"}</span>
    </div></>
  );

  return (
    <><Navbar />
    <div className="main-layout" style={{ maxWidth:660 }}>

      {step === STEP.CONFIRM && (
        <div style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:16, padding:"36px 40px" }}>
          <div style={{ fontSize:"3rem", marginBottom:16 }}>🧭</div>
          <h1>Explore a different direction</h1>
          <p style={{ lineHeight:1.75, marginBottom:8 }}>
            Recent level-up attempts suggest that your current path may need a different kind of support. This is not a verdict on your potential—just a chance to compare paths that may suit your current strengths better.
          </p>
          <p style={{ marginBottom:24 }}>
            You can explore suggestions with no commitment, or keep your current career and continue learning.
          </p>
          {error && <div className="alert alert-error">{error}</div>}
          <div style={{ display:"flex", gap:12, flexWrap:"wrap" }}>
            <button className="btn btn-grad" onClick={handleYes}>Explore career matches</button>
            <button className="btn btn-ghost" onClick={() => navigate("/dashboard")}>No, keep going</button>
          </div>
        </div>
      )}

      {step === STEP.SUGGESTIONS && (
        <>
          <h1 style={{ marginBottom:6 }}>Career paths to explore</h1>
          <p style={{ marginBottom:24 }}>These are suggestions based on your academic background and recent learning evidence—not limits on what you can pursue.</p>
          {error && <div className="alert alert-error">{error}</div>}
          <div style={{ display:"flex", flexDirection:"column", gap:14, marginBottom:24 }}>
            {alternatives.map((alt, i) => (
              <div key={i} style={{ background:"var(--bg-card)", border:`1px solid ${selectedCareer?.career === alt.career ? "rgba(129,140,248,.7)" : "var(--border)"}`, borderRadius:14, padding:"22px 24px", display:"flex", justifyContent:"space-between", alignItems:"flex-start", gap:16, boxShadow:selectedCareer?.career === alt.career ? "0 0 0 3px rgba(99,102,241,.12)" : "none", transition:"all .18s" }}>
                <div style={{ flex:1 }}>
                  <h2 style={{ marginBottom:8 }}>{alt.career}</h2>
                  <p style={{ margin:0, lineHeight:1.65, fontSize:"0.9rem" }}>{alt.reasoning}</p>
                </div>
                <button className={`btn btn-sm ${selectedCareer?.career === alt.career ? "btn-grad" : "btn-ghost"}`} style={{ whiteSpace:"nowrap", flexShrink:0 }} onClick={() => { setSelectedCareer(alt); setStep(STEP.REVIEW); }} disabled={switching}>
                  Review choice →
                </button>
              </div>
            ))}
          </div>
          <button className="btn btn-ghost" onClick={() => navigate("/dashboard")}>Keep my current career</button>
        </>
      )}

      {step === STEP.REVIEW && selectedCareer && (
        <div style={{ maxWidth:680, margin:"0 auto", background:"var(--bg-card)", border:"1px solid rgba(129,140,248,.35)", borderRadius:16, padding:"32px 34px" }}>
          <button className="btn btn-ghost btn-sm" style={{ marginBottom:22 }} onClick={() => setStep(STEP.SUGGESTIONS)}>← Back to suggestions</button>
          <div style={{ fontSize:"2.4rem", marginBottom:12 }}>🌱</div>
          <div style={{ color:"var(--primary-lt)", fontSize:".7rem", fontWeight:800, letterSpacing:".1em", marginBottom:5 }}>NEW CAREER PATH</div>
          <h1 style={{ marginBottom:8 }}>{selectedCareer.career}</h1>
          <p style={{ fontSize:".9rem", lineHeight:1.65, marginBottom:22 }}>{selectedCareer.reasoning}</p>

          <div style={{ display:"grid", gap:10, padding:"16px", borderRadius:11, background:"rgba(99,102,241,.07)", border:"1px solid rgba(99,102,241,.2)", marginBottom:22 }}>
            <div style={{ color:"#fff", fontWeight:700, fontSize:".86rem" }}>What happens next</div>
            {[
              ["✓", "Your current career history stays saved as a record."],
              ["→", `You will take a fresh placement test for ${selectedCareer.career}.`],
              ["→", "A new skill tree and roadmap will be created for that path."],
              ["i", "Progress does not automatically transfer between different careers."],
            ].map(([icon, text]) => <div key={text} style={{ display:"flex", gap:9, color:"var(--text-2)", fontSize:".8rem", lineHeight:1.45 }}><span style={{ color:icon === "✓" ? "#6ee7b7" : "#a5b4fc", fontWeight:800, minWidth:12 }}>{icon}</span>{text}</div>)}
          </div>

          {error && <div className="alert alert-error">{error}</div>}
          <div style={{ display:"flex", gap:10, flexWrap:"wrap" }}>
            <button className="btn btn-grad" onClick={handleSwitch} disabled={switching}>Start {selectedCareer.career} placement →</button>
            <button className="btn btn-ghost" onClick={() => navigate("/dashboard")}>Keep current career</button>
          </div>
        </div>
      )}
    </div></>
  );
}
