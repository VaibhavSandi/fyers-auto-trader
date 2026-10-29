import { useEffect, useState } from "react";
import { Routes, Route, NavLink } from "react-router-dom";
import Setup from "./pages/Setup";
import Dashboard from "./pages/Dashboard";
import Journal from "./pages/Journal";
import Diagnostics from "./pages/Diagnostics";
import ResearchLab from "./pages/ResearchLab";
import LearningCenter from "./pages/LearningCenter";
import { api } from "./api";

export default function App() {
  const [mode, setMode] = useState<string | null>(null);

  useEffect(() => {
    const load = () => api.getDashboard().then((d) => setMode(d.trading_mode)).catch(() => {});
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="app-shell">
      <div className="navbar">
        <div className="title">🤖 FYERS Auto Trader</div>
        <nav>
          <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>Dashboard</NavLink>
          <NavLink to="/journal" className={({ isActive }) => (isActive ? "active" : "")}>Journal</NavLink>
          <NavLink to="/research" className={({ isActive }) => (isActive ? "active" : "")}>Research Lab</NavLink>
          <NavLink to="/learning" className={({ isActive }) => (isActive ? "active" : "")}>Learning Center</NavLink>
          <NavLink to="/diagnostics" className={({ isActive }) => (isActive ? "active" : "")}>Diagnostics</NavLink>
          <NavLink to="/setup" className={({ isActive }) => (isActive ? "active" : "")}>Setup</NavLink>
        </nav>
        {mode && <span className={`mode-pill ${mode}`}>{mode === "live" ? "🔴 LIVE MODE" : "🟡 PAPER MODE"}</span>}
      </div>

      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/journal" element={<Journal />} />
        <Route path="/research" element={<ResearchLab />} />
        <Route path="/learning" element={<LearningCenter />} />
        <Route path="/diagnostics" element={<Diagnostics />} />
        <Route path="/setup" element={<Setup />} />
      </Routes>
    </div>
  );
}
