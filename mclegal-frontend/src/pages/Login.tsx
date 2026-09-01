import { useState } from "react";
import { ArrowRight, Eye, EyeOff, KeyRound } from "lucide-react";
import { signIn } from "../hooks/useSession";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  // Only opens the session. Where to land afterwards is decided by App's
  // signed-in /login route: navigating from here raced the session update —
  // the redirect fired while `signedIn` was still false, so the signed-out
  // catch-all caught it and sent it straight back to /login.
  function enter(e?: React.FormEvent) {
    e?.preventDefault();
    signIn();
  }

  return (
    <div className="login-screen">
      <div className="login-card">
        <aside className="login-brand">
          <div className="login-lockup">
            <img src="/marmon-mark-white.png" alt="" className="login-brand-mark" />
            <span className="login-lockup-name">Marmon Holdings, Inc.</span>
          </div>
          <LoginArt />
          <div>
            <h2 className="login-brand-title">Built for the legal team</h2>
            <p className="login-brand-copy">
              McLegal reads every negotiated redline across Marmon's contract requests and turns
              them into playbook positions you can take into the next negotiation — with the
              contract, the version, and the author behind every rule.
            </p>
          </div>
        </aside>

        <main className="login-form-side">
          <div className="login-form-inner">
            <div className="login-wordmark">
              McLegal<span>.</span>
            </div>
            <h1 className="login-title">Welcome back</h1>
            <p className="login-sub">Sign in to continue to Redline Intelligence.</p>

            <button type="button" className="login-sso" onClick={() => enter()}>
              <KeyRound size={16} />
              Continue with single sign-on
            </button>

            <div className="login-divider">
              <span>or with email</span>
            </div>

            <form onSubmit={enter}>
              <div className="field">
                <label htmlFor="login-email">Email</label>
                <input
                  id="login-email"
                  className="input"
                  type="email"
                  autoComplete="username"
                  placeholder="you@marmon.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>

              <div className="field">
                <label htmlFor="login-password">Password</label>
                <div className="login-password">
                  <input
                    id="login-password"
                    className="input"
                    type={showPassword ? "text" : "password"}
                    // Off on purpose: nothing verifies this yet, so a browser
                    // shouldn't be offering to remember it against this form.
                    // Drop this line when real authentication lands.
                    autoComplete="off"
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                  <button
                    type="button"
                    className="login-password-toggle"
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    onClick={() => setShowPassword((s) => !s)}
                  >
                    {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                  </button>
                </div>
              </div>

              <button type="submit" className="btn accent login-submit">
                Log in
                <ArrowRight size={16} />
              </button>
            </form>

            <p className="login-foot muted text-body-xs">
              Need access? Contact Marmon Legal.
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}

/** Abstract redline illustration — a document with a struck line and an
 *  inserted one. Drawn inline rather than sourced as an image so the panel
 *  carries no external asset and matches the theme's own colors. */
function LoginArt() {
  return (
    <svg className="login-art" viewBox="0 0 260 170" role="img" aria-label="A contract with tracked changes">
      <rect x="26" y="14" width="150" height="142" rx="10" fill="rgba(255,255,255,0.10)" />
      <rect x="46" y="30" width="150" height="142" rx="10" fill="#fff" opacity="0.96" />
      <rect x="62" y="48" width="86" height="7" rx="3.5" fill="#0F2E8A" opacity="0.75" />
      <rect x="62" y="66" width="118" height="5" rx="2.5" fill="#0B0D14" opacity="0.16" />
      <rect x="62" y="80" width="104" height="5" rx="2.5" fill="#0B0D14" opacity="0.16" />
      <rect x="62" y="97" width="92" height="6" rx="3" fill="oklch(0.58 0.18 25)" opacity="0.5" />
      <line x1="60" y1="100" x2="156" y2="100" stroke="oklch(0.58 0.18 25)" strokeWidth="1.6" />
      <rect x="62" y="114" width="110" height="6" rx="3" fill="oklch(0.62 0.12 150)" opacity="0.55" />
      <rect x="62" y="131" width="70" height="5" rx="2.5" fill="#0B0D14" opacity="0.16" />
      <circle cx="196" cy="104" r="22" fill="none" stroke="#F5BC1F" strokeWidth="5" />
      <line x1="212" y1="120" x2="228" y2="136" stroke="#F5BC1F" strokeWidth="5" strokeLinecap="round" />
    </svg>
  );
}
