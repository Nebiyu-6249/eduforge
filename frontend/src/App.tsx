import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Route, Routes, useLocation, useMatch, useNavigate } from "react-router-dom";
import { api, authConfig, getUser, setUser, ssoLogout, type DevUser } from "./api";
import Activity from "./components/Activity";
import Icon from "./components/Icon";
import Blackboard from "./pages/Blackboard";
import Builder from "./pages/Builder";
import Courses from "./pages/Courses";
import Dashboard from "./pages/Dashboard";
import Drafts from "./pages/Drafts";
import Grading from "./pages/Grading";
import Login from "./pages/Login";
import Materials from "./pages/Materials";
import Programs, { QaApp } from "./pages/Programs";
import QuizFlow from "./pages/QuizFlow";
import QuizList from "./pages/QuizList";
import QuizPage from "./pages/QuizPage";
import TeamMetrics from "./pages/TeamMetrics";
import Version from "./pages/Version";
import type { AppNotification, SearchHit, Status } from "./types";

/** Fired by pages that change a course's state, so the sidebar and bell refresh. */
export const VERSION_CHANGED = "eduforge:version-changed";

interface CourseCtx {
  id: number;
  code: string | null;
  title: string | null;
  term: string | null;
  status: Status;
}

/** Page names a teacher reads, used for the breadcrumb. */
const SUBPAGES: Record<string, string> = {
  "": "Syllabus",
  materials: "Slides and materials",
  questions: "Question bank",
  quiz: "Quizzes and exams",
  grading: "Marking",
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

// --------------------------------------------------------------------------
function Sidebar({ isTeam, ctx, gradingOn, lmsOn, onNavigate }: {
  isTeam: boolean; ctx: CourseCtx | null; gradingOn: boolean; lmsOn: boolean; onNavigate: () => void;
}) {
  const confirmed = ctx?.status === "locked" || ctx?.status === "superseded";
  const item = (to: string, icon: string, label: string, opts: { end?: boolean; disabled?: string } = {}) =>
    opts.disabled ? (
      <span className="nav-item disabled" title={opts.disabled} aria-disabled="true" key={to}>
        <Icon name={icon} /> <span>{label}</span>
      </span>
    ) : (
      <NavLink to={to} end={opts.end} className="nav-item" onClick={onNavigate} key={to}>
        <Icon name={icon} /> <span>{label}</span>
      </NavLink>
    );
  const needConfirm = "Confirm the syllabus first";

  return (
    <nav className="sidebar" aria-label="Main">
      {item("/", "dashboard", "Dashboard", { end: true })}
      {item("/courses", "courses", "My courses")}
      {item("/questions", "bank", "All questions")}
      {gradingOn && item("/grading", "grading", "Marking (all courses)")}
      {item("/reports", "reports", "Reports")}
      {isTeam && item("/team/metrics", "metrics", "Team metrics")}

      {ctx && (
        <div className="side-course">
          <div className="side-course-head">
            <span className="code">{ctx.code ?? "Course"}</span>
            <span className="side-term">{ctx.term ?? ""}</span>
          </div>
          {item(`/v/${ctx.id}`, "review", "Overview", { end: true })}
          {item(`/v/${ctx.id}/syllabus`, "file", "Syllabus")}
          {item(`/v/${ctx.id}/quiz`, "quiz", "Quizzes and exams", { disabled: confirmed ? undefined : needConfirm })}
          {item(`/v/${ctx.id}/questions`, "bank", "Question bank", { disabled: confirmed ? undefined : needConfirm })}
          {item(`/v/${ctx.id}/materials`, "materials", "Slides and materials", { disabled: confirmed ? undefined : needConfirm })}
          {gradingOn && item(`/v/${ctx.id}/grading`, "grading", "Marking", { disabled: ctx.status === "locked" ? undefined : needConfirm })}
          {lmsOn && item(`/v/${ctx.id}/blackboard`, "lms", "Blackboard", { disabled: ctx.status === "locked" ? undefined : needConfirm })}
        </div>
      )}
    </nav>
  );
}

// --------------------------------------------------------------------------
function Breadcrumbs({ ctx }: { ctx: CourseCtx | null }) {
  const loc = useLocation();
  const m = /^\/v\/\d+\/?([a-z]*)\/?([a-z0-9]*)/.exec(loc.pathname);
  const crumbs: { to?: string; label: string }[] = [{ to: "/", label: "Dashboard" }];
  if (m) {
    crumbs.push({ to: "/courses", label: "My courses" });
    const sub = m[1] ?? "";
    const course = ctx ? `${ctx.code ?? "Course"} ${ctx.term ?? ""}`.trim() : "Course";
    crumbs.push(sub ? { to: `/v/${ctx?.id ?? ""}`, label: course } : { label: course });
    if (sub && m[2] && sub === "quiz") {
      crumbs.push({ to: `/v/${ctx?.id ?? ""}/quiz`, label: SUBPAGES.quiz });
      crumbs.push({ label: m[2] === "new" ? "New quiz or exam" : "Quiz" });
    } else if (sub) crumbs.push({ label: SUBPAGES[sub] ?? sub });
  } else if (loc.pathname.startsWith("/courses")) crumbs.push({ label: "My courses" });
  else if (loc.pathname.startsWith("/questions")) crumbs.push({ label: "All questions" });
  else if (loc.pathname.startsWith("/grading")) crumbs.push({ label: "Marking (all courses)" });
  else if (loc.pathname.startsWith("/reports")) crumbs.push({ label: "Reports" });
  else if (loc.pathname.startsWith("/team")) crumbs.push({ label: "Team metrics" });
  if (crumbs.length === 1) return null;

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

// --------------------------------------------------------------------------
function useNarrow(px = 600): boolean {
  const q = `(max-width: ${px}px)`;
  const [narrow, setNarrow] = useState(() => window.matchMedia?.(q).matches ?? false);
  useEffect(() => {
    const m = window.matchMedia?.(q);
    if (!m) return;
    const on = () => setNarrow(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [q]);
  return narrow;
}

function SearchBox() {
  const narrow = useNarrow();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const nav = useNavigate();
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (q.trim().length < 2) {
      setHits(null);
      return;
    }
    const t = setTimeout(() => api.search(q).then(setHits).catch(() => setHits([])), 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setHits(null);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  return (
    <div className="search" ref={box}>
      <label className="sr-only" htmlFor="site-search">Search courses and questions</label>
      <Icon name="search" size={16} />
      <input id="site-search" type="search" value={q} placeholder={narrow ? "Search" : "Search courses and questions"}
        autoComplete="off"
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Escape") { setQ(""); setHits(null); } }} />
      {hits && (
        <div className="search-results" role="listbox" aria-label="Search results">
          {hits.length === 0 ? (
            <p className="none muted small">Nothing matched “{q}”. Search finds your course codes and titles,
              and the text of questions you have approved.</p>
          ) : hits.map((h, i) => (
            <a key={i} href={h.href} onClick={(e) => { e.preventDefault(); setQ(""); setHits(null); nav(h.href); }}>
              <span className="kind">{h.kind === "course" ? "Course" : "Question"}</span>
              <div>{h.title}</div>
              <div className="small muted">{h.subtitle}</div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
function Bell() {
  const [open, setOpen] = useState(false);
  const [notes, setNotes] = useState<AppNotification[]>([]);
  const nav = useNavigate();
  const box = useRef<HTMLDivElement>(null);

  const load = () => api.notifications().then(setNotes).catch(() => setNotes([]));
  useEffect(() => {
    load();
    window.addEventListener(VERSION_CHANGED, load);
    return () => window.removeEventListener(VERSION_CHANGED, load);
  }, []);
  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);

  const unread = notes.filter((n) => !n.read).length;
  return (
    <div className="bell" ref={box}>
      <button className="ghost" aria-expanded={open} aria-haspopup="true"
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        onClick={() => setOpen(!open)}>
        <Icon name="bell" size={20} />
        {unread > 0 && <span className="dot" aria-hidden="true">{unread}</span>}
      </button>
      {open && (
        <div className="popover">
          <header>
            <h3>Notifications</h3>
            {unread > 0 && (
              <button className="link" onClick={() => api.markNotificationsRead().then(load)}>Mark all as read</button>
            )}
          </header>
          <div className="list">
            {notes.length === 0 ? (
              <p className="empty-note">Nothing needs your attention right now.</p>
            ) : notes.map((n) => (
              <a key={n.key} href={n.href} className={n.read ? "" : "unread"}
                onClick={(e) => {
                  e.preventDefault();
                  setOpen(false);
                  api.markNotificationsRead([n.key]).then(load).catch(() => undefined);
                  nav(n.href);
                }}>
                <strong>{n.title}</strong>
                <span className="small muted">{n.body}</span>
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
function Profile({ user, canSignOut, onSignOut }: { user: DevUser; canSignOut: boolean; onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const initials = (user.name || user.email).split(/\s+/).slice(0, 2).map((p) => p[0]).join("").toUpperCase();
  useEffect(() => {
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, []);
  if (!canSignOut) {
    return (
      <div className="profile">
        <span className="avatar" aria-hidden="true">{initials}</span>
        <span className="who"><b>{user.name}</b><span>Teacher</span></span>
      </div>
    );
  }
  return (
    <div className="profile" ref={box}>
      <button className="ghost row" aria-expanded={open} aria-haspopup="true" onClick={() => setOpen(!open)}>
        <span className="avatar" aria-hidden="true">{initials}</span>
        <span className="who"><b>{user.name}</b><span>Teacher</span></span>
      </button>
      {open && (
        <div className="popover" style={{ width: 200 }}>
          <div className="list">
            <a href="#sign-out" onClick={(e) => { e.preventDefault(); onSignOut(); }}><strong>Sign out</strong></a>
          </div>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
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
              <p>The server did not answer. If it was asleep it may need another moment.</p>
              <button className="primary" onClick={() => window.location.reload()}>Try again</button>
            </>
          ) : (
            <>
              <div className="spinner" aria-hidden="true" />
              <p className="muted">Starting up. A sleeping prototype server can take up to a minute.</p>
            </>
          )}
        </div>
      </div>
    );
  if (!user)
    return <Login sso={mode === "sso"} onSignIn={(u) => { setUser(u); setU(u); }} />;

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
        <button className="menu-btn" aria-label="Show the menu" aria-expanded={navOpen} onClick={() => setNavOpen(!navOpen)}>
          <Icon name="menu" size={22} />
        </button>
        <Link to="/" className="brand">
          <span className="brandmark">EF</span>
          <span>EduForge<small>AURAK teaching tools</small></span>
        </Link>
        <SearchBox />
        <span className="spacer" />
        <Activity />
        <Bell />
        <Profile user={user} canSignOut={mode !== "open"} onSignOut={signOut} />
      </header>
      <Sidebar isTeam={isTeam} ctx={ctx} gradingOn={gradingOn} lmsOn={lmsOn} onNavigate={() => setNavOpen(false)} />
      <div className="scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />
      <div className="content">
        <Breadcrumbs ctx={ctx} />
        {notice && <div className="notice-bar" role="note"><Icon name="info" size={16} /> {notice}</div>}
        <main id="main">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/courses" element={<Courses />} />
            <Route path="/questions" element={<Courses pick="questions" />} />
            <Route path="/grading" element={<Courses pick="grading" />} />
            <Route path="/reports" element={<Programs />} />
            <Route path="/v/:id" element={<Version />} />
            <Route path="/v/:id/syllabus" element={<Version tab="syllabus" />} />
            <Route path="/v/:id/quiz" element={<QuizList />} />
            <Route path="/v/:id/quiz/new" element={<QuizFlow />} />
            <Route path="/v/:id/quiz/:formId" element={<QuizPage />} />
            <Route path="/v/:id/questions" element={<Drafts />} />
            <Route path="/v/:id/materials" element={<Materials />} />
            <Route path="/v/:id/grading" element={<Grading />} />
            <Route path="/v/:id/blackboard" element={<Blackboard />} />
            {/* The detailed builder: reached from "Advanced" on the quiz page. */}
            <Route path="/v/:id/builder" element={<Builder />} />
            <Route path="/programs" element={<Programs />} />
            <Route path="/team/metrics" element={<TeamMetrics />} />
          </Routes>
        </main>
        <footer className="footbar">
          EduForge · American University of Ras Al Khaimah · everything the tool writes stays a draft until a
          named teacher approves it
        </footer>
      </div>
    </div>
  );
}
