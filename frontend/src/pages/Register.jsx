import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api from "../utils/api";

export default function Register() {
  const navigate = useNavigate();
  const [form,    setForm]    = useState({ name: "", email: "", password: "" });
  const [error,   setError]   = useState("");
  const [loading, setLoading] = useState(false);

  function handleChange(e) { setForm({ ...form, [e.target.name]: e.target.value }); }

  async function handleSubmit(e) {
    e.preventDefault(); setError("");
    if (!form.name || !form.email || !form.password) { setError("All fields are required."); return; }
    if (form.password.length < 6) { setError("Password must be at least 6 characters."); return; }
    setLoading(true);
    try {
      await api.post("/auth/register", form);
      navigate("/login", { state: { message: "Account created! Please sign in." } });
    } catch (err) {
      setError(err.response?.data?.error || "Registration failed. Please try again.");
    } finally { setLoading(false); }
  }

  return (
    <div className="auth-bg">
      <div className="auth-card">
        <div className="auth-logo"><span>AS</span><span>PAR</span></div>
        <h1>Create your account</h1>
        <p className="sub">Start your journey to your dream career</p>

        {error && <div className="alert alert-error">{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className="field">
            <label>FULL NAME</label>
            <input name="name" type="text" value={form.name} onChange={handleChange} placeholder="Enter your full name" />
          </div>
          <div className="field">
            <label>EMAIL ADDRESS</label>
            <input name="email" type="email" value={form.email} onChange={handleChange} placeholder="Enter your email" />
          </div>
          <div className="field">
            <label>PASSWORD</label>
            <input name="password" type="password" value={form.password} onChange={handleChange} placeholder="At least 6 characters" />
          </div>
          <button className="btn btn-grad btn-full mt-8" type="submit" disabled={loading}>
            {loading ? "Creating Account…" : "Create Account"}
          </button>
        </form>

        <p className="text-center mt-16" style={{ color: "var(--text-3)", fontSize: "0.87rem" }}>
          Already have an account?{" "}
          <Link to="/login" style={{ color: "var(--primary-lt)", fontWeight: 600 }}>Sign in</Link>
        </p>
      </div>
    </div>
  );
}