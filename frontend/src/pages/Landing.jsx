import { Link } from "react-router-dom";

export default function Landing() {
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)", display: "flex", flexDirection: "column" }}>
      {/* Navbar */}
      <nav style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "16px 40px", borderBottom: "1px solid var(--border)", position: "sticky", top: 0, background: "rgba(10,10,15,0.95)", backdropFilter: "blur(12px)", zIndex: 100 }}>
        <span className="navbar-brand"><span className="b1">AS</span><span className="b2">PAR</span></span>
        <Link to="/login" style={{ color: "var(--text-2)", textDecoration: "none", padding: "8px 20px", border: "1px solid var(--border)", borderRadius: 8, fontSize: "0.88rem", fontWeight: 600, transition: "all 0.2s" }}>Sign In</Link>
      </nav>

      {/* Hero */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "80px 24px 60px", textAlign: "center", position: "relative" }}>
        {/* glow */}
        <div style={{ position: "absolute", width: 600, height: 600, borderRadius: "50%", background: "radial-gradient(circle, rgba(99,102,241,0.12) 0%, transparent 70%)", top: "50%", left: "50%", transform: "translate(-50%,-50%)", pointerEvents: "none" }} />

        <div style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "5px 16px", border: "1px solid rgba(6,182,212,0.35)", borderRadius: 20, marginBottom: 32, background: "rgba(6,182,212,0.07)" }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--accent)", display: "inline-block" }} />
          <span style={{ fontSize: "0.72rem", fontWeight: 700, letterSpacing: "0.1em", color: "var(--accent)" }}>AI-POWERED LEARNING ROADMAP</span>
        </div>

        <h1 style={{ fontSize: "clamp(2.4rem, 6vw, 4rem)", fontWeight: 900, lineHeight: 1.1, marginBottom: 24, maxWidth: 680, color: "#fff" }}>
          Your Path to Your{" "}
          <span style={{ background: "var(--grad)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
            Dream Career
          </span>{" "}
          Starts Here
        </h1>

        <p style={{ fontSize: "1.05rem", color: "var(--text-2)", maxWidth: 540, margin: "0 auto 40px", lineHeight: 1.75 }}>
          ASPAR analyses your academic background, tests your knowledge, and builds a personalised roadmap that tells you exactly what to learn — so you can reach your dream career on your terms.
        </p>

        <div style={{ display: "flex", gap: 14, justifyContent: "center", flexWrap: "wrap" }}>
          <Link to="/register" className="btn btn-grad btn-lg">Get Started — It's Free</Link>
          <Link to="/login"    className="btn btn-ghost btn-lg">Sign In</Link>
        </div>
      </div>

      {/* How it works */}
      <div style={{ background: "var(--bg-card)", borderTop: "1px solid var(--border)", padding: "64px 24px" }}>
        <div style={{ maxWidth: 900, margin: "0 auto" }}>
          <p style={{ textAlign: "center", fontSize: "0.72rem", fontWeight: 700, letterSpacing: "0.12em", color: "var(--text-3)", marginBottom: 8 }}>HOW IT WORKS</p>
          <h2 style={{ textAlign: "center", fontSize: "1.8rem", marginBottom: 40, color: "#fff" }}>Five steps to your dream career</h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 16 }}>
            {[
              { n: "1", icon: "🎯", title: "Set your goal", desc: "Enter your dream career and why you want it." },
              { n: "2", icon: "📝", title: "Placement test", desc: "AI tests your current knowledge across levels." },
              { n: "3", icon: "🗺️", title: "Get your roadmap", desc: "A personalised 5-level skill tree is created." },
              { n: "4", icon: "📚", title: "Learn on your own", desc: "ASPAR guides what to study — you learn it." },
              { n: "5", icon: "🚀", title: "Prove & level up", desc: "Pass skill tests to unlock the next level." },
            ].map(({ n, icon, title, desc }) => (
              <div key={n} style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border)", borderRadius: 14, padding: "24px 18px", textAlign: "center" }}>
                <div style={{ width: 42, height: 42, borderRadius: "50%", background: "var(--grad)", margin: "0 auto 14px", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "1.15rem", boxShadow: "0 4px 14px rgba(99,102,241,0.35)" }}>
                  {icon}
                </div>
                <h3 style={{ color: "#fff", marginBottom: 6, fontSize: "0.92rem" }}>{title}</h3>
                <p style={{ color: "var(--text-3)", fontSize: "0.82rem", margin: 0, lineHeight: 1.6 }}>{desc}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div style={{ padding: "20px", textAlign: "center", borderTop: "1px solid var(--border)", color: "var(--text-3)", fontSize: "0.8rem" }}>
        ASPAR — AI-Based Student Performance Analysis and Roadmap System
      </div>
    </div>
  );
}