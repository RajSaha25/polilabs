/* global React, PolilabsAuth */

// Polilabs — AuthScreen. The login / create-account gate shown before
// the research workspace. Talks to window.PolilabsAuth; on success it
// calls onAuthed(user) and the app shell (Root, in app.jsx) swaps in.

function AuthScreen({ onAuthed }) {
  const { useState } = React;
  const [mode, setMode] = useState("login"); // "login" | "signup"
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const isSignup = mode === "signup";

  function switchMode(next) {
    setMode(next);
    setError(null);
  }

  async function submit(e) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      const fn = isSignup ? PolilabsAuth.signup : PolilabsAuth.login;
      const user = await fn(email.trim(), password);
      onAuthed(user);
    } catch (err) {
      setError((err && err.message) || "Something went wrong. Try again.");
      setBusy(false);
    }
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-eyebrow">Research workspace</div>
        <div className="auth-brand">polilabs</div>
        <div className="auth-tagline">
          Queryable, citation-accurate US federal legislation — 191 bills
          across the 118th and 119th Congress.
        </div>

        <div className="auth-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            className={"auth-tab" + (isSignup ? "" : " is-active")}
            aria-selected={!isSignup}
            onClick={() => switchMode("login")}
          >
            Sign in
          </button>
          <button
            type="button"
            role="tab"
            className={"auth-tab" + (isSignup ? " is-active" : "")}
            aria-selected={isSignup}
            onClick={() => switchMode("signup")}
          >
            Create account
          </button>
        </div>

        <form className="auth-form" onSubmit={submit}>
          <label className="auth-label">
            <span>Email</span>
            <input
              className="auth-input"
              type="email"
              value={email}
              autoComplete="email"
              required
              autoFocus
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>

          <label className="auth-label">
            <span>Password</span>
            <input
              className="auth-input"
              type="password"
              value={password}
              autoComplete={isSignup ? "new-password" : "current-password"}
              required
              minLength={isSignup ? 8 : undefined}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>

          {isSignup && (
            <div className="auth-hint">At least 8 characters.</div>
          )}

          {error && <div className="auth-error">{error}</div>}

          <button className="auth-submit" type="submit" disabled={busy}>
            {busy
              ? "Working…"
              : isSignup
                ? "Create account"
                : "Sign in"}
          </button>
        </form>

        <div className="auth-switch">
          {isSignup ? (
            <span>
              Already have an account?{" "}
              <button type="button" onClick={() => switchMode("login")}>
                Sign in
              </button>
            </span>
          ) : (
            <span>
              New to polilabs?{" "}
              <button type="button" onClick={() => switchMode("signup")}>
                Create an account
              </button>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

window.AuthScreen = AuthScreen;
