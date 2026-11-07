import { useEffect, useState } from "react";
import { Link, NavLink, Route, Routes, useLocation, useMatch } from "react-router-dom";
import { api, authConfig, getUser, setUser, ssoLogout, type DevUser } from "./api";
import Icon from "./components/Icon";
import { STATUS_LABEL } from "./components/util";
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
import type { Status } from "./types";

/** Fired by pages that change a version's status (lock, revise), so the sidebar refreshes. */
export const VERSION_CHANGED = "eduforge:version-changed";

interface CourseCtx {
  id: number;
  code: string | null;
  title: string | null;
  term: string | null;
  status: Status;
}

const SUBPAGES: Record<string, string> = {
  "": "Syllabus review",
  materials: "Course materials",
  drafts: "Draft Studio",
  builder: "Assessment Builder",
  grading: "Grading Assist",
  blackboard: "Blackboard",
};

function useCourseCtx(id: number | null): CourseCtx | null {
  const [ctx, setCtx] = useState<CourseCtx | null>(null);
  useEffect(() => {
    if (!id) {
      setCtx(null);
      return;
    }
    const load = () =>
      api
        .get(id)
        .then((v) => setCtx({ id, code: v.record.course.code, title: v.record.course.title, term: v.record.offering.term, status: v.status }))
        .catch(() => setCtx(null));
    load();
    window.addEventListener(VERSION_CHANGED, load);
    return () => window.removeEventListener(VERSION_CHANGED, load);
  }, [id]);
  return ctx && ctx.id === id ? ctx : null;
}

function Sidebar({ user, isTeam, ctx, gradingOn, lmsOn, onNavigate }: {
  user: DevUser; isTeam: boolean; ctx: CourseCtx | null; gradingOn: boolean; lmsOn: boolean; onNavigate: () => void;
}) {
  const locked = ctx?.status === "locked" || ctx?.status === "superseded";
  const item = (to: string, icon: string, label: string, opts: { end?: boolean; disabled?: string } = {}) =>
    opts.disabled ? (
      <span className="nav-item disabled" title={opts.disabled} aria-disabled="true">
        <Icon name={icon} /> <span>{label}</span>
      </span>
    ) : (
      <NavLink to={to} end={opts.end} className="nav-item" onClick={onNavigate}>
        <Icon name={icon} /> <span>{label}</span>
      </NavLink>
    );
  const needLock = "Lock the working version first";

  return (
    <nav className="sidebar" aria-label="Main">
      <div className="side-user">
        <span className="avatar"><Icon name="user" size={20} /></span>
        <div>
          <div className="side-name">{user.name}</div>
          <div className="side-role">Faculty</div>
        </div>
      </div>
      {item("/", "courses", "My Courses", { end: true })}
      {item("/programs", "coverage", "Program Coverage")}
      {isTeam && item("/team/metrics", "metrics", "Team Metrics")}

      {ctx && (
        <div className="side-course">
          <div className="side-course-head">
            <span className="code">{ctx.code ?? "Course"}</span>
            <span className="side-term">{ctx.term ?? ""} · {STATUS_LABEL[ctx.status]}</span>
          </div>
          {item(`/v/${ctx.id}`, "review", locked ? "Working Version" : "Review & Lock", { end: true })}
          {item(`/v/${ctx.id}/materials`, "materials", "Course Materials", { disabled: locked ? undefined : needLock })}
          {item(`/v/${ctx.id}/drafts`, "drafts", "Draft Studio", { disabled: locked ? undefined : needLock })}
          {item(`/v/${ctx.id}/builder`, "builder", "Assessment Builder", { disabled: locked ? undefined : needLock })}
          {gradingOn && item(`/v/${ctx.id}/grading`, "grading", "Grading Assist", { disabled: ctx.status === "locked" ? undefined : needLock })}
          {lmsOn && item(`/v/${ctx.id}/blackboard`, "lms", "Blackboard", { disabled: ctx.status === "locked" ? undefined : needLock })}
        </div>
      )}
    </nav>
  );
}

function Breadcrumbs({ ctx }: { ctx: CourseCtx | null }) {
  const loc = useLocation();
  const m = /^\/v\/\d+\/?([a-z]*)/.exec(loc.pathname);
  const crumbs: { to?: string; label: string }[] = [{ to: "/", label: "Home" }];
  if (m) {
    crumbs.push({ to: "/", label: "My Courses" });
    const sub = m[1] ?? "";
    const course = ctx ? `${ctx.code ?? "Course"} ${ctx.term ?? ""}`.trim() : "Course";
    crumbs.push(sub ? { to: `/v/${ctx?.id ?? ""}`, label: course } : { label: course });
    if (sub) crumbs.push({ label: SUBPAGES[sub] ?? sub });
  } else if (loc.pathname.startsWith("/programs")) crumbs.push({ label: "Program Coverage" });
  else if (loc.pathname.startsWith("/team")) crumbs.push({ label: "Team Metrics" });
  else crumbs.push({ label: "My Courses" });

  return (
    <nav className="crumbband" aria-label="Breadcrumb">
      <ol>
        {crumbs.map((c, i) => (
          <li key={i} aria-current={i === crumbs.length - 1 ? "page" : undefined}>
            {c.to && i < crumbs.length - 1 ? <Link to={c.to}>{c.label}</Link> : <span>{c.label}</span>}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export default function App() {
  const [mode, setMode] = useState<string | null>(null);
  const [user, setU] = useState<DevUser | null>(null);
  const [isTeam, setIsTeam] = useState(false);
  const [role, setRole] = useState<"faculty" | "viewer">("faculty");
  const [notice, setNotice] = useState<string | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [gradingOn, setGradingOn] = useState(false);
  const [lmsOn, setLmsOn] = useState(false);
  const [navOpen, setNavOpen] = useState(false);

  const vMatch = useMatch("/v/:id/*");
  const ctx = useCourseCtx(user && vMatch ? Number(vMatch.params.id) : null);

  useEffect(() => {
    authConfig()
      .then(async (c) => {
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
      })
      .catch(() => {
        setMode("unknown");
        setUnreachable(true);
      });
  }, []);
  useEffect(() => {
    if (!user) return;
    api.whoami().then((w) => setRole(w.role)).catch(() => setRole("faculty"));
    api.me().then((m) => setIsTeam(m.is_team)).catch(() => setIsTeam(false));
    api.gradingStatus().then((s) => setGradingOn(s.enabled)).catch(() => setGradingOn(false));
    api.lmsStatus().then((s) => setLmsOn(s.mode !== "off")).catch(() => setLmsOn(false));
  }, [user]);

  if (mode === null || unreachable)
    return (
      <div className="splash" role={unreachable ? "alert" : "status"}>
        <div className="splash-card">
          <div className="brandmark big">EF</div>
          <h1>EduForge</h1>
          {unreachable ? (
            <>
              <p>The server didn't answer. If it was asleep it may need another moment.</p>
              <button className="primary" onClick={() => window.location.reload()}>Try again</button>
            </>
          ) : (
            <>
              <div className="spinner" aria-hidden="true" />
              <p className="muted">Connecting… a sleeping prototype server can take up to a minute to wake.</p>
            </>
          )}
        </div>
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
    <div className={`shell ${navOpen ? "nav-open" : ""}`}>
      <a href="#main" className="skip">Skip to content</a>
      <header className="topbar">
        <button className="menu-btn" aria-label="Toggle menu" aria-expanded={navOpen} onClick={() => setNavOpen(!navOpen)}>
          <Icon name="menu" size={20} />
        </button>
        <Link to="/" className="brand">
          <span className="brandmark">EF</span>
          <span>
            EduForge
            <small>AI Teaching Resource &amp; Assessment Support</small>
          </span>
        </Link>
        <span className="spacer" />
        <span className="who">{user.name}</span>
        {mode !== "open" && <button onClick={signOut}>Sign out</button>}
      </header>
      <Sidebar user={user} isTeam={isTeam} ctx={ctx} gradingOn={gradingOn} lmsOn={lmsOn} onNavigate={() => setNavOpen(false)} />
      <div className="scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />
      <div className="content">
        <Breadcrumbs ctx={ctx} />
        {notice && <div className="notice-bar" role="note"><Icon name="info" size={16} /> {notice}</div>}
        <main id="main">
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
        <footer className="footbar">
          EduForge prototype · American University of Ras Al Khaimah · every AI output stays a draft until a named faculty member approves it
        </footer>
      </div>
    </div>
  );
}
