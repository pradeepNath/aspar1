/**
 * src/App.jsx
 * ------------
 * Root component. Defines ALL routes for the SPA using React Router v6.
 *
 * Public routes  (no JWT needed): /  /register  /login
 * Protected routes (need JWT):    everything else
 *
 * The <ProtectedRoute> wrapper checks localStorage for a token and
 * redirects to /login if missing — so every protected page is safe
 * without adding auth logic inside the page itself.
 */

import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import ProtectedRoute from "./components/ProtectedRoute";

// Public pages
import Landing        from "./pages/Landing";
import Register       from "./pages/Register";
import Login          from "./pages/Login";

// Protected pages — onboarding flow
import DreamSetup      from "./pages/DreamSetup";
import AcademicResults from "./pages/AcademicResults";
import PlacementTest   from "./pages/PlacementTest";

// Protected pages — main app
import Dashboard   from "./pages/Dashboard";
import Quiz        from "./pages/Quiz";
import Grading     from "./pages/Grading";
import SkillTree   from "./pages/SkillTree";
import Progress    from "./pages/Progress";
import CareerChange from "./pages/CareerChange";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* ---- Public ---- */}
        <Route path="/"         element={<Landing />} />
        <Route path="/register" element={<Register />} />
        <Route path="/login"    element={<Login />} />

        {/* ---- Protected — onboarding ---- */}
        <Route path="/setup/dream" element={
          <ProtectedRoute><DreamSetup /></ProtectedRoute>
        } />
        <Route path="/setup/academics" element={
          <ProtectedRoute><AcademicResults /></ProtectedRoute>
        } />
        <Route path="/setup/placement" element={
          <ProtectedRoute><PlacementTest /></ProtectedRoute>
        } />

        {/* ---- Protected — add academics after onboarding ---- */}
        <Route path="/academics/add" element={
          <ProtectedRoute><AcademicResults /></ProtectedRoute>
        } />

        {/* ---- Protected — main app ---- */}
        <Route path="/dashboard" element={
          <ProtectedRoute><Dashboard /></ProtectedRoute>
        } />
        <Route path="/quiz" element={
          <ProtectedRoute><Quiz /></ProtectedRoute>
        } />
        <Route path="/grading" element={
          <ProtectedRoute><Grading /></ProtectedRoute>
        } />
        <Route path="/skills" element={
          <ProtectedRoute><SkillTree /></ProtectedRoute>
        } />
        <Route path="/progress" element={
          <ProtectedRoute><Progress /></ProtectedRoute>
        } />
        <Route path="/career-change" element={
          <ProtectedRoute><CareerChange /></ProtectedRoute>
        } />

        {/* ---- Fallback ---- */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}