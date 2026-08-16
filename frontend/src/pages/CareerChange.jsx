import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Navbar from "../components/Navbar";
import api from "../utils/api";

const STEP = { CONFIRM:"confirm", LOADING:"loading", SUGGESTIONS:"suggestions", SWITCHING:"switching" };

export default function CareerChange() {
  const navigate = useNavigate();
  const [step,         setStep]         = useState(STEP.CONFIRM);
  const [alternatives, setAlternatives] = useState([]);
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

  async function handleSwitch(career) {
    setError(""); setSwitching(true);
    try {
      await api.post("/career/switch", { new_career: career });
      navigate("/setup/placement", { state:{ message:`Starting fresh as a ${career}!` } });
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
          <div style={{ fontSize:"3rem", marginBottom:16 }}>🤔</div>
          <h1>Time to reassess?</h1>
          <p style={{ lineHeight:1.75, marginBottom:8 }}>
            Based on your recent level-up test results, the AI thinks this career path might not be the best fit right now. That's completely okay — everyone's strengths are different.
          </p>
          <p style={{ marginBottom:24 }}>
            Would you like to explore <strong style={{ color:"#fff" }}>3 alternative careers</strong> that better match your demonstrated strengths? Or you can continue — the roadmap will be adjusted to give you more support.
          </p>
          {error && <div className="alert alert-error">{error}</div>}
          <div style={{ display:"flex", gap:12, flexWrap:"wrap" }}>
            <button className="btn btn-grad" onClick={handleYes}>Yes, show me alternatives</button>
            <button className="btn btn-ghost" onClick={() => navigate("/dashboard")}>No, keep going</button>
          </div>
        </div>
      )}

      {step === STEP.SUGGESTIONS && (
        <>
          <h1 style={{ marginBottom:6 }}>Careers that match your strengths</h1>
          <p style={{ marginBottom:24 }}>Based on your academic background and test performance, here are 3 paths where you're likely to excel.</p>
          {error && <div className="alert alert-error">{error}</div>}
          <div style={{ display:"flex", flexDirection:"column", gap:14, marginBottom:24 }}>
            {alternatives.map((alt, i) => (
              <div key={i} style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:14, padding:"22px 24px", display:"flex", justifyContent:"space-between", alignItems:"flex-start", gap:16 }}>
                <div style={{ flex:1 }}>
                  <h2 style={{ marginBottom:8 }}>{alt.career}</h2>
                  <p style={{ margin:0, lineHeight:1.65, fontSize:"0.9rem" }}>{alt.reasoning}</p>
                </div>
                <button className="btn btn-grad btn-sm" style={{ whiteSpace:"nowrap", flexShrink:0 }} onClick={() => handleSwitch(alt.career)} disabled={switching}>
                  Choose this →
                </button>
              </div>
            ))}
          </div>
          <button className="btn btn-ghost" onClick={() => navigate("/dashboard")}>Keep my current career</button>
        </>
      )}
    </div></>
  );
}