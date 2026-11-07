import { useState } from "react";
import { ssoLoginUrl, type DevUser } from "../api";

// Dev-mode sign-in. University SSO replaces this (backend AUTH_MODE=sso).
export default function Login({ onSignIn, sso }: { onSignIn: (u: DevUser) => void; sso: boolean }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const ok = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());

  if (sso)
    return (
      <div className="login card stack">
        <div>
          <h1>EduForge</h1>
          <div className="muted">AI Teaching Resource &amp; Assessment Support Tool · faculty only</div>
        </div>
        <a href={ssoLoginUrl(window.location.pathname)}><button className="primary">Sign in with your university account</button></a>
      </div>
    );

  return (
    <div className="login card stack">
      <div>
        <h1>EduForge</h1>
        <div className="muted">AI Teaching Resource &amp; Assessment Support Tool · faculty only</div>
      </div>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault();
          if (ok) onSignIn({ email: email.trim().toLowerCase(), name: name.trim() || email.split("@")[0] });
        }}
      >
        <div>
          <label className="lbl" htmlFor="email">University email</label>
          <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
        </div>
        <div>
          <label className="lbl" htmlFor="name">Name (as shown in the edit log)</label>
          <input id="name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <button className="primary" disabled={!ok}>Sign in</button>
        <div className="small muted">Development sign-in. University SSO will replace this screen.</div>
      </form>
    </div>
  );
}
