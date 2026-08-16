/**
 * components/ProtectedRoute.jsx
 * ------------------------------
 * Wraps any route that requires a logged-in user.
 * If no JWT token is found in localStorage, redirects to /login.
 *
 * Usage in App.jsx:
 *   <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
 */

import { Navigate } from "react-router-dom";

export default function ProtectedRoute({ children }) {
  const token = localStorage.getItem("token");
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return children;
}