import { Link, useNavigate, useLocation } from "react-router-dom";

export default function Navbar() {
  const navigate = useNavigate();
  const location = useLocation();
  const user = JSON.parse(localStorage.getItem("user") || "{}");

  function handleLogout() {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    navigate("/login");
  }

  const links = [
    { to: "/dashboard", label: "Dashboard" },
    { to: "/skills",    label: "Skill Tree" },
    { to: "/progress",  label: "Progress" },
  ];

  return (
    <nav className="navbar">
      <Link to="/dashboard" className="navbar-brand">
        <span className="b1">AS</span><span className="b2">PAR</span>
      </Link>
      <div className="navbar-links">
        {links.map(({ to, label }) => (
          <Link key={to} to={to} className={location.pathname === to ? "active" : ""}>{label}</Link>
        ))}
        {user?.name && <span className="nav-user">👤 {user.name.split(" ")[0]}</span>}
        <button onClick={handleLogout}>Sign Out</button>
      </div>
    </nav>
  );
}