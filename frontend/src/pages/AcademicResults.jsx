/**
 * pages/AcademicResults.jsx
 * --------------------------
 * Used in TWO contexts:
 *
 * 1. ONBOARDING (/setup/academics) — first-time setup, step 2 of 4.
 *    Shows step dots. On save → /setup/placement.
 *
 * 2. DASHBOARD ADD-MORE (/academics/add) — student wants to add more
 *    results after initial setup. Shows existing results, no step dots.
 *    On save → /dashboard.
 *
 * Both paths support:
 *   - Upload (OCR → AI extract → editable table → confirm save)
 *   - Manual entry (dynamic add/remove rows)
 *   - Skip (onboarding only)
 *
 * After saving, both methods can be used again on the next visit —
 * rows are always APPENDED, never overwritten.
 */

import { useState, useRef, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import Navbar from "../components/Navbar";
import api from "../utils/api";

function OnboardingNav() {
  const user = JSON.parse(localStorage.getItem("user") || "{}");
  return (
    <nav style={{ display:"flex", justifyContent:"space-between", alignItems:"center", padding:"14px 32px", borderBottom:"1px solid var(--border)", background:"var(--bg)" }}>
      <span className="navbar-brand"><span className="b1">AS</span><span className="b2">PAR</span></span>
      {user?.name && <span style={{ color:"var(--text-3)", fontSize:"0.85rem" }}>🔥 {user.name.split(" ")[0]}</span>}
    </nav>
  );
}

const EMPTY_ROW = () => ({ subject:"", grade:"", gpa:"" });

export default function AcademicResults() {
  const navigate  = useNavigate();
  const location  = useLocation();

  // Detect context: onboarding vs dashboard add-more
  const isOnboarding = location.pathname === "/setup/academics";

  // mode: null = show picker, "manual" = show table, "upload" = show table after OCR
  const [mode,        setMode]        = useState(null);
  const [rows,        setRows]        = useState([EMPTY_ROW()]);
  const [existing,    setExisting]    = useState([]);   // previously saved records
  const [error,       setError]       = useState("");
  const [info,        setInfo]        = useState("");
  const [loading,     setLoading]     = useState(false);
  const [ocrLoading,  setOcrLoading]  = useState(false);
  const [loadingExist,setLoadingExist]= useState(!isOnboarding);
  const fileRef = useRef(null);
  const dots = ["done", "done", "active", "pending"];

  // Load existing records when in dashboard add-more mode
  useEffect(() => {
    if (!isOnboarding) {
      api.get("/academics")
        .then(res => setExisting(res.data.academics || []))
        .catch(() => {})
        .finally(() => setLoadingExist(false));
    }
  }, [isOnboarding]);

  function updateRow(i, field, val) {
    const n = [...rows]; n[i] = { ...n[i], [field]: val }; setRows(n);
  }
  function addRow()    { setRows([...rows, EMPTY_ROW()]); }
  function removeRow(i){ setRows(rows.filter((_,idx) => idx !== i)); }

  async function handleFileChange(e) {
    const file = e.target.files[0];
    if (!file) return;
    // Reset file input so the same file can be re-uploaded if needed
    e.target.value = "";
    setError(""); setInfo(""); setOcrLoading(true);
    try {
      const fd = new FormData(); fd.append("file", file);
      const res = await api.post("/academics/upload", fd, {
        headers: { "Content-Type": "multipart/form-data" }
      });
      const extracted = (res.data.rows || []).map(r => ({
        subject: r.subject || "",
        grade:   r.grade   || "",
        gpa:     r.gpa != null ? String(r.gpa) : "",
      }));
      setRows(extracted.length ? extracted : [EMPTY_ROW()]);
      setMode("upload");
      setInfo(`AI extracted ${extracted.length} record(s). Review and edit before saving.`);
    } catch (err) {
      setError(err.response?.data?.error || "OCR failed. Try a clearer image or enter manually.");
      // Stay on picker so student can choose manual instead
      setMode(null);
    } finally {
      setOcrLoading(false);
    }
  }

  async function handleSave() {
    setError("");
    const valid = rows.filter(r => r.subject.trim());
    if (!valid.length) { setError("Add at least one subject."); return; }
    setLoading(true);
    try {
      const payload = valid.map(r => ({
        subject: r.subject.trim(),
        grade:   r.grade.trim() || null,
        gpa:     r.gpa !== "" ? parseFloat(r.gpa) : null,
      }));
      if (mode === "upload") {
        await api.post("/academics/upload/confirm", { rows: payload });
      } else {
        await api.post("/academics/manual", { rows: payload });
      }
      if (isOnboarding) {
        navigate("/setup/placement");
      } else {
        navigate("/dashboard", { state: { message: "Academic results saved successfully." } });
      }
    } catch (err) {
      setError(err.response?.data?.error || "Could not save. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  function handleAddAnother() {
    // After OCR upload, let student add another file or switch to manual
    setRows([EMPTY_ROW()]);
    setMode(null);
    setInfo("");
    setError("");
  }

  // ── Dashboard add-more layout ─────────────────────────────
  if (!isOnboarding) {
    return (
      <>
        <Navbar />
        <div className="main-layout" style={{ maxWidth: 740 }}>
          <div style={{ display:"flex", alignItems:"center", gap:12, marginBottom:24 }}>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate("/dashboard")}>← Back</button>
            <h1 style={{ margin:0 }}>Add Academic Results</h1>
          </div>

          {/* Existing records */}
          {loadingExist ? (
            <div className="spinner-wrap" style={{ padding:"24px 0" }}>
              <div className="spinner" style={{ width:28, height:28 }}/><span>Loading existing records…</span>
            </div>
          ) : existing.length > 0 && (
            <div style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:12, padding:"20px 24px", marginBottom:24 }}>
              <p style={{ fontSize:"0.72rem", fontWeight:700, letterSpacing:"0.08em", color:"var(--text-3)", marginBottom:12 }}>
                ALREADY SAVED ({existing.length} records)
              </p>
              <div style={{ display:"flex", flexWrap:"wrap", gap:8 }}>
                {existing.map((r, i) => (
                  <div key={i} style={{ background:"rgba(99,102,241,0.08)", border:"1px solid rgba(99,102,241,0.2)", borderRadius:8, padding:"6px 12px", fontSize:"0.83rem" }}>
                    <span style={{ color:"#fff", fontWeight:600 }}>{r.subject}</span>
                    {r.grade && <span style={{ color:"var(--text-3)", marginLeft:6 }}>{r.grade}</span>}
                    {r.gpa   && <span style={{ color:"var(--text-3)", marginLeft:4 }}>· {r.gpa} GPA</span>}
                    <span style={{ color:"var(--text-3)", fontSize:"0.72rem", marginLeft:6 }}>({r.source})</span>
                  </div>
                ))}
              </div>
              <p style={{ fontSize:"0.78rem", color:"var(--text-3)", margin:"12px 0 0" }}>
                New records will be <strong style={{ color:"var(--text-2)" }}>appended</strong> — existing records are never deleted.
              </p>
            </div>
          )}

          {error && <div className="alert alert-error">{error}</div>}
          {info  && <div className="alert alert-info">{info}</div>}

          {/* Mode picker */}
          {mode === null && !ocrLoading && (
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:16, marginBottom:20 }}>
              {[
                { icon:"📄", title:"Upload Document", desc:"Photo or PDF of your transcript. AI reads and fills it in for you.", action:()=>fileRef.current.click() },
                { icon:"✏️", title:"Enter Manually",  desc:"Type your subjects and grades directly into the form.", action:()=>setMode("manual") },
              ].map(({ icon, title, desc, action }) => (
                <button key={title} onClick={action} style={{
                  background:"rgba(255,255,255,0.03)", border:"1px solid var(--border)", borderRadius:14,
                  padding:"28px 20px", textAlign:"center", cursor:"pointer", color:"inherit",
                  transition:"all 0.2s", fontFamily:"var(--font)"
                }}
                  onMouseEnter={e=>{e.currentTarget.style.borderColor="rgba(99,102,241,0.4)";e.currentTarget.style.background="rgba(99,102,241,0.06)"}}
                  onMouseLeave={e=>{e.currentTarget.style.borderColor="var(--border)";e.currentTarget.style.background="rgba(255,255,255,0.03)"}}
                >
                  <div style={{ fontSize:"2rem", marginBottom:12 }}>{icon}</div>
                  <div style={{ fontWeight:700, color:"#fff", marginBottom:6 }}>{title}</div>
                  <div style={{ fontSize:"0.83rem", color:"var(--text-2)", lineHeight:1.5 }}>{desc}</div>
                </button>
              ))}
            </div>
          )}
          <input ref={fileRef} type="file" accept="image/*,.pdf" style={{ display:"none" }} onChange={handleFileChange} />

          {ocrLoading && (
            <div className="spinner-wrap">
              <div className="spinner"/><span>Reading your document with AI…</span>
            </div>
          )}

          {(mode === "manual" || mode === "upload") && !ocrLoading && (
            <div style={{ background:"var(--bg-card)", border:"1px solid var(--border)", borderRadius:12, padding:"20px 24px" }}>
              <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:14 }}>
                <p style={{ fontSize:"0.72rem", fontWeight:700, letterSpacing:"0.08em", color:"var(--text-3)", margin:0 }}>
                  {mode === "upload" ? "REVIEW EXTRACTED RECORDS" : "NEW RECORDS TO ADD"}
                </p>
                <button className="btn btn-ghost btn-sm" onClick={handleAddAnother}>
                  ← Change method
                </button>
              </div>

              <table style={{ width:"100%", borderCollapse:"collapse", marginBottom:16 }}>
                <thead>
                  <tr>
                    {["Subject / Course","Grade","GPA",""].map(h => (
                      <th key={h} style={{ padding:"8px 10px", textAlign:"left", fontSize:"0.72rem", fontWeight:700, letterSpacing:"0.08em", color:"var(--text-3)", borderBottom:"1px solid var(--border)" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr key={i}>
                      <td style={{ padding:"6px 6px 6px 0" }}>
                        <input value={row.subject} onChange={e=>updateRow(i,"subject",e.target.value)} placeholder="Mathematics"/>
                      </td>
                      <td style={{ padding:"6px 4px" }}>
                        <input value={row.grade} onChange={e=>updateRow(i,"grade",e.target.value)} placeholder="A"/>
                      </td>
                      <td style={{ padding:"6px 4px" }}>
                        <input value={row.gpa} onChange={e=>updateRow(i,"gpa",e.target.value)} placeholder="3.8" type="number" step="0.01" min="0" max="4"/>
                      </td>
                      <td style={{ padding:"6px 0 6px 4px", width:32 }}>
                        {rows.length > 1 && (
                          <button onClick={()=>removeRow(i)} style={{ background:"none", border:"none", cursor:"pointer", color:"var(--danger)", fontSize:"1.1rem" }}>×</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", flexWrap:"wrap", gap:12 }}>
                <button className="btn btn-ghost btn-sm" onClick={addRow}>+ Add row</button>
                <div style={{ display:"flex", gap:10 }}>
                  {mode === "upload" && (
                    <button className="btn btn-outline btn-sm" onClick={()=>fileRef.current.click()}>
                      📄 Upload another file
                    </button>
                  )}
                  <button className="btn btn-grad" onClick={handleSave} disabled={loading}>
                    {loading ? "Saving…" : `Save ${rows.filter(r=>r.subject.trim()).length} record(s) →`}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </>
    );
  }

  // ── Onboarding layout ─────────────────────────────────────
  return (
    <div style={{ minHeight:"100vh", background:"var(--bg)", display:"flex", flexDirection:"column" }}>
      <OnboardingNav />
      <div style={{ flex:1, display:"flex", flexDirection:"column", alignItems:"center", padding:"32px 20px" }}>
        <div className="step-dots">{dots.map((s,i)=><div key={i} className={`step-dot ${s}`}/>)}</div>

        <div className="ob-card" style={{ maxWidth: 720 }}>
          <p className="ob-step-label">STEP 2 OF 4</p>
          <h1>Your academic results</h1>
          <p className="sub">How would you like to add your results?</p>

          {error && <div className="alert alert-error">{error}</div>}
          {info  && <div className="alert alert-info">{info}</div>}

          {/* Mode picker */}
          {mode === null && !ocrLoading && (
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:16, marginBottom:20 }}>
              {[
                { icon:"📄", title:"Upload Document", desc:"Photo or PDF of your transcript. AI reads and fills it in for you.", action:()=>fileRef.current.click() },
                { icon:"✏️", title:"Enter Manually",  desc:"Type your subjects and grades directly into the form.", action:()=>setMode("manual") },
              ].map(({ icon, title, desc, action }) => (
                <button key={title} onClick={action} style={{
                  background:"rgba(255,255,255,0.03)", border:"1px solid var(--border)", borderRadius:14,
                  padding:"28px 20px", textAlign:"center", cursor:"pointer", color:"inherit",
                  transition:"all 0.2s", fontFamily:"var(--font)"
                }}
                  onMouseEnter={e=>{e.currentTarget.style.borderColor="rgba(99,102,241,0.4)";e.currentTarget.style.background="rgba(99,102,241,0.06)"}}
                  onMouseLeave={e=>{e.currentTarget.style.borderColor="var(--border)";e.currentTarget.style.background="rgba(255,255,255,0.03)"}}
                >
                  <div style={{ fontSize:"2rem", marginBottom:12 }}>{icon}</div>
                  <div style={{ fontWeight:700, color:"#fff", marginBottom:6 }}>{title}</div>
                  <div style={{ fontSize:"0.83rem", color:"var(--text-2)", lineHeight:1.5 }}>{desc}</div>
                </button>
              ))}
            </div>
          )}
          <input ref={fileRef} type="file" accept="image/*,.pdf" style={{ display:"none" }} onChange={handleFileChange} />

          {ocrLoading && (
            <div className="spinner-wrap">
              <div className="spinner"/><span>Reading your document with AI…</span>
            </div>
          )}

          {(mode === "manual" || mode === "upload") && !ocrLoading && (
            <>
              {mode === "upload" && (
                <div style={{ display:"flex", justifyContent:"flex-end", marginBottom:8 }}>
                  <button className="btn btn-ghost btn-sm" onClick={handleAddAnother}>
                    ← Try a different method
                  </button>
                </div>
              )}
              <table style={{ width:"100%", borderCollapse:"collapse", marginBottom:16 }}>
                <thead>
                  <tr>
                    {["Subject / Course","Grade","GPA",""].map(h=>(
                      <th key={h} style={{ padding:"8px 10px", textAlign:"left", fontSize:"0.72rem", fontWeight:700, letterSpacing:"0.08em", color:"var(--text-3)", borderBottom:"1px solid var(--border)" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row,i)=>(
                    <tr key={i}>
                      <td style={{ padding:"6px 6px 6px 0" }}><input value={row.subject} onChange={e=>updateRow(i,"subject",e.target.value)} placeholder="Mathematics"/></td>
                      <td style={{ padding:"6px 4px" }}><input value={row.grade} onChange={e=>updateRow(i,"grade",e.target.value)} placeholder="A"/></td>
                      <td style={{ padding:"6px 4px" }}><input value={row.gpa} onChange={e=>updateRow(i,"gpa",e.target.value)} placeholder="3.8" type="number" step="0.01" min="0" max="4"/></td>
                      <td style={{ padding:"6px 0 6px 4px", width:32 }}>
                        {rows.length>1&&<button onClick={()=>removeRow(i)} style={{ background:"none", border:"none", cursor:"pointer", color:"var(--danger)", fontSize:"1.1rem" }}>×</button>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button className="btn btn-ghost btn-sm mb-16" onClick={addRow}>+ Add row</button>
              <div style={{ display:"flex", gap:12 }}>
                <button className="btn btn-grad" onClick={handleSave} disabled={loading}>
                  {loading ? "Saving…" : "Save & Continue →"}
                </button>
                {mode === "upload" && (
                  <button className="btn btn-outline btn-sm" onClick={()=>fileRef.current.click()}>
                    📄 Upload another file
                  </button>
                )}
              </div>
            </>
          )}

          <div className="divider"/>
          <button className="btn btn-ghost btn-sm" onClick={()=>navigate("/setup/placement")} style={{ color:"var(--text-3)" }}>
            Skip this step →
          </button>
        </div>
      </div>
    </div>
  );
}