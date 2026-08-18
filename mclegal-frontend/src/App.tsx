import { Routes, Route, useLocation } from "react-router-dom";
import Sidebar from "./components/Sidebar";
import Discovery from "./pages/Discovery";
import RedlineDiffs from "./pages/RedlineDiffs";
import ClauseFindings from "./pages/ClauseFindings";
import Placeholder from "./pages/Placeholder";

const CRUMB_BY_PATH: Record<string, string> = {
  "/": "Redline Discovery",
  "/diffs": "Redline Diffs",
  "/clause-findings": "Clause Findings",
  "/golden-rules": "Golden Rules",
  "/suggested-rules": "Suggested Rules",
};

export default function App() {
  const location = useLocation();
  const crumb = CRUMB_BY_PATH[location.pathname] ?? "";

  return (
    <div className="app">
      <Sidebar />
      <div className="main">
        <div className="topbar">
          <div className="crumbs">
            McLegal <span>/ {crumb}</span>
          </div>
        </div>
        <div className="page page-wide">
          <Routes>
            <Route path="/" element={<Discovery />} />
            <Route path="/diffs" element={<RedlineDiffs />} />
            <Route path="/clause-findings" element={<ClauseFindings />} />
            <Route
              path="/golden-rules"
              element={<Placeholder title="Golden Rules" note="Known negotiation positions per clause — not seeded yet." />}
            />
            <Route
              path="/suggested-rules"
              element={<Placeholder title="Suggested Rules" note="AI-suggested rules mined from redline history — future work." />}
            />
          </Routes>
        </div>
      </div>
    </div>
  );
}
