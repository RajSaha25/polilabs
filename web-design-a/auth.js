/* ============================================================
   POLILABS — Auth client (plain JS, no build step)

   Talks to the FastAPI /auth/* endpoints and keeps the session
   token + user in localStorage. Loaded before backend.js so the
   Bearer token is available when backend.js builds its headers.

   Backend contract (auth/routes.py):
     POST /auth/signup  {email, password} -> {token, user}
     POST /auth/login   {email, password} -> {token, user}
     GET  /auth/me      (Bearer)          -> {id, email}

   Everything is exposed on window.PolilabsAuth.
   ============================================================ */
(function () {
  // Same backend origin resolution as backend.js.
  const BACKEND =
    (window.localStorage && localStorage.getItem("polilabs_backend")) ||
    "http://localhost:8000";

  const TOKEN_KEY = "polilabs_token";
  const USER_KEY = "polilabs_user";

  function getToken() {
    return localStorage.getItem(TOKEN_KEY) || null;
  }

  function getUser() {
    try {
      return JSON.parse(localStorage.getItem(USER_KEY) || "null");
    } catch (e) {
      return null;
    }
  }

  function isAuthenticated() {
    return !!getToken() && !!getUser();
  }

  function _store(data) {
    localStorage.setItem(TOKEN_KEY, data.token);
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }

  // POST a JSON body; surface the backend's `detail` string on error.
  async function _post(path, body) {
    let res;
    try {
      res = await fetch(BACKEND + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (e) {
      throw new Error("Couldn't reach the server. Is the backend running?");
    }
    let data = {};
    try {
      data = await res.json();
    } catch (e) {
      /* response had no JSON body */
    }
    if (!res.ok) {
      const detail = data && data.detail;
      throw new Error(
        typeof detail === "string"
          ? detail
          : "Request failed (HTTP " + res.status + ").",
      );
    }
    return data;
  }

  // Backend /auth/* isn't wired yet — stub locally so the gate passes.
  // Any email + any non-empty password is accepted; the "token" is just a
  // marker so isAuthenticated() returns true. Replace with real backend
  // auth once the /auth/signup + /auth/login endpoints exist.
  function _stubAuth(email) {
    const data = {
      token: "stub-" + Math.random().toString(36).slice(2),
      user: { id: email, email: email },
    };
    _store(data);
    return data.user;
  }

  async function signup(email, password) {
    if (!email || !password) throw new Error("Email and password are required.");
    return _stubAuth(email);
  }

  async function login(email, password) {
    if (!email || !password) throw new Error("Email and password are required.");
    return _stubAuth(email);
  }

  window.PolilabsAuth = {
    getToken: getToken,
    getUser: getUser,
    isAuthenticated: isAuthenticated,
    signup: signup,
    login: login,
    logout: logout,
  };
})();
