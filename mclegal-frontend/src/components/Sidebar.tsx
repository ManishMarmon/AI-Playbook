import { NavLink } from "react-router-dom";
import { Search, FileSearch, GitCompare, ScanSearch, BarChart3, BookOpen, Lightbulb, FileSignature } from "lucide-react";

const NAV = [
  { to: "/", label: "Redline Discovery", icon: FileSearch },
  { to: "/diffs", label: "Redline Diffs", icon: GitCompare },
  { to: "/clause-findings", label: "Clause Findings", icon: ScanSearch },
  { to: "/analytics", label: "Reporting & Analytics", icon: BarChart3 },
  { to: "/golden-rules", label: "Golden Rules", icon: BookOpen },
  { to: "/suggested-rules", label: "Suggested Rules", icon: Lightbulb },
  { to: "/draft-contract", label: "Draft Contract", icon: FileSignature },
];

export default function Sidebar({ search, onSearchChange }: { search: string; onSearchChange: (value: string) => void }) {
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
        <input
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search requests, clauses..."
          aria-label="Search requests, clauses, and vendors"
        />
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
