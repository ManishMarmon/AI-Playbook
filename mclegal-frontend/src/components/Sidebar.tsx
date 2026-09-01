import { NavLink } from "react-router-dom";
import { FileSearch, GitCompare, ScanSearch, BarChart3, BookOpen, Library, Lightbulb, FileSignature, ClipboardList } from "lucide-react";

// Two sections, split by audience rather than by pipeline stage. Redlines is
// what an attorney opens to do the work; Diagnostics is how the work is shown
// to be sound — the classifier's decisions, the raw diffs behind each finding,
// and the roll-ups for whoever is asking about spend and volume.
const SECTIONS = [
  {
    label: "Redlines",
    items: [
      { to: "/requests", label: "All Requests", icon: ClipboardList },
      { to: "/playbooks", label: "Playbooks", icon: Library },
      { to: "/draft-contract", label: "Draft Contract", icon: FileSignature },
      { to: "/golden-rules", label: "Golden Rules", icon: BookOpen },
      { to: "/suggested-rules", label: "Suggested Rules", icon: Lightbulb },
    ],
  },
  {
    label: "Diagnostics",
    items: [
      { to: "/discovery", label: "Redline Discovery", icon: FileSearch },
      { to: "/diffs", label: "Redline Diffs", icon: GitCompare },
      { to: "/clause-findings", label: "Clause Findings", icon: ScanSearch },
      { to: "/analytics", label: "Reporting & Analytics", icon: BarChart3 },
    ],
  },
];

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <img
          src="/marmon-mark-white.png"
          alt="Marmon"
          className="brand-mark"
          style={{ objectFit: "contain", background: "transparent", width: 50, height: 50 }}
        />
        <div className="brand-name">
          McLegal
          <small>Redline Intelligence</small>
        </div>
      </div>

      {SECTIONS.map((section) => (
        <nav key={section.label} className="nav-section" aria-label={section.label}>
          <div className="nav-label">{section.label}</div>
          {section.items.map(({ to, label, icon: Icon }) => (
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
      ))}

      <div className="nav-foot">
        <div className="avatar">MN</div>
        <div className="who">Marmon Legal</div>
      </div>
    </aside>
  );
}
