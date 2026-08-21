import { useState } from "react";
import { Routes, Route, useLocation } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import Discovery from "./pages/Discovery";
import RedlineDiffs from "./pages/RedlineDiffs";
import ClauseFindings from "./pages/ClauseFindings";
import Analytics from "./pages/Analytics";
import DraftContract from "./pages/DraftContract";
import Requests from "./pages/Requests";
import GoldenRules from "./pages/GoldenRules";
import Placeholder from "./pages/Placeholder";

const CRUMB_BY_PATH: Record<string, string> = {
  "/": "Redline Discovery",
  "/diffs": "Redline Diffs",
  "/clause-findings": "Clause Findings",
  "/analytics": "Reporting & Analytics",
  "/golden-rules": "Golden Rules",
  "/suggested-rules": "Suggested Rules",
  "/draft-contract": "Draft Contract",
  "/requests": "All Requests",
};

export default function App() {
  const location = useLocation();
  const crumb = CRUMB_BY_PATH[location.pathname] ?? "";
  const [search, setSearch] = useState("");

  return (
    <div className="app">
      <Sidebar search={search} onSearchChange={setSearch} />
      <div className="main">
        <div className="topbar">
          <div className="crumbs">
            McLegal <span>/ {crumb}</span>
          </div>
        </div>
        <div className="page page-wide">
          <Routes>
            <Route path="/" element={<Discovery search={search} />} />
            <Route path="/diffs" element={<RedlineDiffs search={search} />} />
            <Route path="/clause-findings" element={<ClauseFindings search={search} />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/golden-rules" element={<GoldenRules search={search} />} />
            <Route
              path="/suggested-rules"
              element={<Placeholder title="Suggested Rules" note="AI-suggested rules mined from redline history — future work." />}
            />
            <Route path="/draft-contract" element={<DraftContract />} />
            <Route path="/requests" element={<Requests search={search} />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
