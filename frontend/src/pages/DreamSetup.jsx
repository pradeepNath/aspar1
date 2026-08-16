import { useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../utils/api";

// Minimal onboarding navbar
function OnboardingNav({ step, totalSteps }) {
  const navigate = useNavigate();
  const user = JSON.parse(localStorage.getItem("user") || "{}");
  return (
    <nav style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "14px 32px", borderBottom: "1px solid var(--border)", background: "var(--bg)" }}>
      <span className="navbar-brand"><span className="b1">AS</span><span className="b2">PAR</span></span>
      {user?.name && (
        <span style={{ color: "var(--text-3)", fontSize: "0.85rem", display: "flex", alignItems: "center", gap: 6 }}>
          🔥 {user.name.split(" ")[0]}
        </span>
      )}
    </nav>
  );
}

export default function DreamSetup() {
  const navigate = useNavigate();
  const [form,    setForm]    = useState({ dream_career: "", passion_statement: "" });
  const [error,   setError]   = useState("");
  const [loading, setLoading] = useState(false);
  const user = JSON.parse(localStorage.getItem("user") || "{}");

  // Step dots: 4 steps (welcome is done, now on step 1)
  const dots = ["done", "active", "pending", "pending"];

  function handleChange(e) { setForm({ ...form, [e.target.name]: e.target.value }); }

  async function handleSubmit(e) {
    e.preventDefault(); setError("");
    if (!form.dream_career.trim()) { setError("Please enter your dream career."); return; }
    setLoading(true);
    try {
      await api.post("/profile/dream", form);
      navigate("/setup/academics");
    } catch (err) {
      setError(err.response?.data?.error || "Could not save. Please try again.");
    } finally { setLoading(false); }
  }

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)", display: "flex", flexDirection: "column" }}>
      <OnboardingNav />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", padding: "32px 20px" }}>
        {/* Step dots */}
        <div className="step-dots">
          {dots.map((s, i) => <div key={i} className={`step-dot ${s}`} />)}
        </div>

        <div className="ob-card">
          <p className="ob-step-label">STEP 1 OF 4</p>
          <h1>What is your dream career?</h1>
          <p className="sub">Be specific. The more precise your goal, the better the AI can tailor your questions and roadmap.</p>

          {error && <div className="alert alert-error">{error}</div>}

          <form onSubmit={handleSubmit}>
            <div className="field">
              <label>DREAM CAREER</label>
              <div className="hint">Example: "Software Engineer at a tech company" or "Data Scientist"</div>
              <input name="dream_career" type="text" value={form.dream_career} onChange={handleChange}
                placeholder="e.g. Full Stack Software Engineer" />
            </div>
            <div className="field">
              <label>WHY DO YOU WANT THIS CAREER?</label>
              <div className="hint">Write at least 2-3 sentences about your passion and motivation.</div>
              <textarea name="passion_statement" value={form.passion_statement} onChange={handleChange}
                placeholder="I am passionate about this career because..." rows={5} />
            </div>
            <button className="btn btn-grad btn-full mt-8" type="submit" disabled={loading}>
              {loading ? "Saving…" : "Continue →"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}