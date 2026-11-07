import { useEffect, useState } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { api, authConfig, getUser, setUser, ssoLogout, type DevUser } from "./api";
import Blackboard from "./pages/Blackboard";
import Builder from "./pages/Builder";
import Courses from "./pages/Courses";
import Drafts from "./pages/Drafts";
import Grading from "./pages/Grading";
import Login from "./pages/Login";
import Materials from "./pages/Materials";
import Programs, { QaApp } from "./pages/Programs";
import TeamMetrics from "./pages/TeamMetrics";
import Version from "./pages/Version";

export default function App() {
  const [mode, setMode] = useState<string | null>(null);
  const [user, setU] = useState<DevUser | null>(null);
  const [isTeam, setIsTeam] = useState(false);
  const [role, setRole] = useState<"faculty" | "viewer">("faculty");
  const [notice, setNotice] = useState<string | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    authConfig().then(async (c) => {
      setMode(c.mode);
      setNotice(c.notice ?? null);
      if (c.mode === "sso" || c.mode === "open") {
        // sso: the session cookie says who it is. open: no sign-in; the server uses one shared demo account.
        const m = await api.me().catch(() => null);
        if (m) setU({ email: m.email, name: m.name });
        else if (c.mode === "open") setUnreachable(true);
      } else {
        setU(getUser());
      }
    });
  }, []);
  useEffect(() => {
    if (!user) return;
    api.whoami().then((w) => setRole(w.role)).catch(() => setRole("faculty"));
    api.me().then((m) => setIsTeam(m.is_team)).catch(() => setIsTeam(false));
  }, [user]);

  if (mode === null) return <p className="muted" style={{ padding: 24 }}>Loading… (a sleeping prototype server can take up to a minute to wake)</p>;
  if (unreachable)
    return (
      <div className="login card stack" role="alert">
        <h1>EduForge</h1>
        <p>The server didn't answer. If it was asleep it may need another moment.</p>
        <button className="primary" onClick={() => window.location.reload()}>Try again</button>
      </div>
    );
  if (!user)
    return (
      <Login
        sso={mode === "sso"}
        onSignIn={(u) => {
          setUser(u);
          setU(u);
        }}
      />
    );

  const signOut = () => {
    if (mode === "sso") ssoLogout();
    setUser(null);
    setU(null);
  };
  if (role === "viewer") return <QaApp name={user.name} onSignOut={signOut} />;

  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          EduForge<small>Course Registry</small>
        </Link>
        <span className="spacer" />
        <Link to="/programs" className="who" style={{ color: "inherit" }}>Program coverage</Link>
        {isTeam && <Link to="/team/metrics" className="who" style={{ color: "inherit" }}>Team metrics</Link>}
        <span className="who">{user.name}</span>
        {mode !== "open" && <button
          onClick={() => {
            if (mode === "sso") ssoLogout();
            setUser(null);
            setU(null);
          }}
        >
          Sign out
        </button>}
      </header>
      {notice && <div className="notice-bar" role="note">{notice}</div>}
      <main>
        <Routes>
          <Route path="/" element={<Courses />} />
          <Route path="/v/:id" element={<Version />} />
          <Route path="/v/:id/drafts" element={<Drafts />} />
          <Route path="/v/:id/materials" element={<Materials />} />
          <Route path="/v/:id/builder" element={<Builder />} />
          <Route path="/v/:id/grading" element={<Grading />} />
          <Route path="/v/:id/blackboard" element={<Blackboard />} />
          <Route path="/programs" element={<Programs />} />
          <Route path="/team/metrics" element={<TeamMetrics />} />
        </Routes>
      </main>
    </>
  );
}
