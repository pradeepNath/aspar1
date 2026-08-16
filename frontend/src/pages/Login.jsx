import { useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import api from "../utils/api";

export default function Login() {
  const navigate  = useNavigate();
  const location  = useLocation();
  const [form,    setForm]    = useState({ email: "", password: "" });
  const [error,   setError]   = useState("");
  const [loading, setLoading] = useState(false);
  const regMessage = location.state?.message;

  function handleChange(e) { setForm({ ...form, [e.target.name]: e.target.value }); }

  async function handleSubmit(e) {
    e.preventDefault(); setError("");
    if (!form.email || !form.password) { setError("Email and password are required."); return; }
    setLoading(true);
    try {
      const res = await api.post("/auth/login", form);
      localStorage.setItem("token", res.data.token);
      localStorage.setItem("user",  JSON.stringify(res.data.user));

      // Check onboarding state
      try {
        const skRes = await api.get("/skills/tree");
        if (skRes.data?.skills?.length > 0) {
          navigate("/dashboard");
        } else {
          // skills empty — check if profile exists
          try {
            await api.get("/academics");
            navigate("/setup/academics");
          } catch {
            navigate("/setup/dream");
          }
        }
      } catch {
        navigate("/setup/dream");
      }
    } catch (err) {
      setError(err.response?.data?.error || "Invalid email or password.");
    } finally { setLoading(false); }
  }

  return (
    <div className="auth-bg">
      <div className="auth-card">
        <Link to="/" className="auth-back">← Back</Link>
        <div className="auth-logo"><span>AS</span><span>PAR</span></div>
        <h1>Welcome back</h1>
        <p className="sub">Sign in to continue your journey</p>

        {regMessage && <div className="alert alert-success">{regMessage}</div>}
        {error      && <div className="alert alert-error">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="field">
            <label>EMAIL ADDRESS</label>
            <input name="email" type="email" value={form.email} onChange={handleChange} placeholder="Enter your email" />
          </div>
          <div className="field">
            <label>PASSWORD</label>
            <input name="password" type="password" value={form.password} onChange={handleChange} placeholder="Enter your password" />
          </div>
          <button className="btn btn-grad btn-full mt-8" type="submit" disabled={loading}>
            {loading ? "Signing in…" : "Sign In"}
          </button>
        </form>

        <p className="text-center mt-16" style={{ color: "var(--text-3)", fontSize: "0.87rem" }}>
          Don't have an account?{" "}
          <Link to="/register" style={{ color: "var(--primary-lt)", fontWeight: 600 }}>Create one</Link>
        </p>
      </div>
    </div>
  );
}