import { useEffect, useState } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Menu } from "lucide-react";
import Sidebar from "./components/Sidebar";
import Login from "./pages/Login";
import { useSession } from "./hooks/useSession";
import TopbarMenu from "./components/TopbarMenu";
import Discovery from "./pages/Discovery";
import RedlineDiffs from "./pages/RedlineDiffs";
import ClauseFindings from "./pages/ClauseFindings";
import Analytics from "./pages/Analytics";
import DraftContract from "./pages/DraftContract";
import Requests from "./pages/Requests";
import GoldenRules from "./pages/GoldenRules";
import Playbooks from "./pages/Playbooks";
import SuggestedRules from "./pages/SuggestedRules";

const CRUMB_BY_PATH: Record<string, string> = {
  "/discovery": "Redline Discovery",
  "/diffs": "Redline Diffs",
  "/clause-findings": "Clause Findings",
  "/analytics": "Reporting & Analytics",
  "/golden-rules": "Golden Rules",
  "/playbooks": "Playbooks",
  "/suggested-rules": "Suggested Rules",
  "/draft-contract": "Draft Contract",
  "/requests": "All Requests",
};

// Per-page free-text filtering (Discovery/RedlineDiffs/ClauseFindings/
// GoldenRules/Requests) still exists and still takes a `search` prop — only
// the shared nav-level search box that used to set it is gone. Each of those
// pages also has its own dedicated filter UI, so this isn't a capability
// loss, just one less redundant entry point.
const NO_SEARCH = "";

export default function App() {
  const location = useLocation();
  const crumb = CRUMB_BY_PATH[location.pathname] ?? "";
  // Below the layout breakpoint the sidebar is an off-canvas drawer: a fixed
  // 260px rail eats two thirds of a phone screen. Above it, this state is
  // inert — the sidebar is always in the layout and the toggle is hidden.
  const [navOpen, setNavOpen] = useState(false);
  const signedIn = useSession();
  // Path the visitor was denied, stashed in history state by the redirect
  // below so it never appears in the address bar.
  const deniedPath = (location.state as { from?: string } | null)?.from;
  const returnTo = deniedPath && deniedPath !== "/login" ? deniedPath : "/requests";

  // Navigating is the natural "done" signal for the drawer; without this you
  // tap a page and stare at the menu you just used.
  useEffect(() => setNavOpen(false), [location.pathname]);

  useEffect(() => {
    if (!navOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setNavOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navOpen]);

  // Signed out, every path REDIRECTS to /login rather than rendering the
  // sign-in screen in place. Rendering in place left the address bar showing
  // /requests while you were locked out, which reads like the page is there
  // and just failed to load. The path you were heading for rides along in
  // history state, not the URL, so signing in returns you to it without
  // putting it on screen.
  if (!signedIn) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace state={{ from: location.pathname }} />} />
      </Routes>
    );
  }

  return (
    <div className={navOpen ? "app nav-open" : "app"}>
      <Sidebar />
      {/* Tapping outside the drawer closes it. Hidden above the breakpoint. */}
      <button
        type="button"
        className="nav-scrim"
        aria-label="Close navigation"
        tabIndex={navOpen ? 0 : -1}
        onClick={() => setNavOpen(false)}
      />
      <div className="main">
        <div className="topbar">
          <button
            type="button"
            className="nav-toggle"
            aria-label="Open navigation"
            aria-expanded={navOpen}
            onClick={() => setNavOpen(true)}
          >
            <Menu size={18} />
          </button>
          <div className="crumbs">
            McLegal <span>/ {crumb}</span>
          </div>
          <div className="topbar-spacer" />
          <TopbarMenu />
        </div>
        <div className="page page-wide">
          <Routes>
            {/* All Requests is the landing page: it's the only view that
                covers the whole population, and the one an attorney starts
                from. Redline Discovery used to hold "/" and so was where a
                bare localhost:5175 dropped you. */}
            <Route path="/" element={<Navigate to="/requests" replace />} />
            {/* Signed in, /login has nothing to offer — bounce to wherever the
                visitor was originally headed, or the landing page. This is
                also the moment a fresh sign-in resolves, which is why the
                decision lives here and not in the form. */}
            <Route path="/login" element={<Navigate to={returnTo} replace />} />
            <Route path="/discovery" element={<Discovery search={NO_SEARCH} />} />
            <Route path="/diffs" element={<RedlineDiffs search={NO_SEARCH} />} />
            <Route path="/clause-findings" element={<ClauseFindings search={NO_SEARCH} />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/golden-rules" element={<GoldenRules search={NO_SEARCH} />} />
            <Route path="/playbooks" element={<Playbooks />} />
            <Route path="/suggested-rules" element={<SuggestedRules />} />
            <Route path="/draft-contract" element={<DraftContract />} />
            <Route path="/requests" element={<Requests search={NO_SEARCH} />} />
            <Route path="*" element={<Navigate to="/requests" replace />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}
