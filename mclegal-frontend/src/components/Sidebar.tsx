import { NavLink } from "react-router-dom";
import { Search, FileSearch, GitCompare, ScanSearch, BookOpen, Lightbulb } from "lucide-react";

const NAV = [
  { to: "/", label: "Redline Discovery", icon: FileSearch },
  { to: "/diffs", label: "Redline Diffs", icon: GitCompare },
  { to: "/clause-findings", label: "Clause Findings", icon: ScanSearch },
  { to: "/golden-rules", label: "Golden Rules", icon: BookOpen },
  { to: "/suggested-rules", label: "Suggested Rules", icon: Lightbulb },
];

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">
          <span style={{ fontWeight: 700, color: "var(--ink)" }}>M</span>
        </div>
        <div className="brand-name">
          McLegal
          <small>Redline Intelligence</small>
        </div>
      </div>

      <div className="nav-search">
        <Search size={14} />
        <input placeholder="Search requests, clauses..." />
      </div>

      <nav className="nav-section">
        <div className="nav-label">Redlines</div>
        {NAV.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => "nav-item" + (isActive ? " active" : "")}
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="nav-foot">
        <div className="avatar">MN</div>
        <div className="who">
          Marmon Legal
          <small>McLegal PoC</small>
        </div>
      </div>
    </aside>
  );
}
