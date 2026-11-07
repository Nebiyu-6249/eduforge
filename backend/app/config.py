from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def _psycopg(cls, v: str) -> str:
        """Hosts (Render, Heroku) hand out postgres:// or postgresql:// URLs; use the psycopg 3 driver."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    # SQLite by default so the backend runs without Docker; docker-compose sets Postgres.
    database_url: str = "sqlite:///./eduforge.db"
    storage_dir: Path = Path("./storage")
    # fs | db. "db" keeps uploaded files in the database, for hosts whose disk is wiped on restart.
    storage_backend: str = "fs"
    max_upload_mb: int = 20

    # "dev": trust the X-Dev-User header (local development only).
    # "sso": University SSO (OIDC) — not implemented yet; see app/auth.py.
    auth_mode: str = "dev"  # dev | open | sso
    open_access_email: str = "demo.faculty@prototype.eduforge"
    open_access_name: str = "Demo Faculty"
    # Shown as a banner in the UI (e.g. "Prototype: use made-up data only"); empty = none.
    notice: str = ""
    # SSO (plan H.1): OpenID Connect against the university identity provider.
    oidc_issuer: str = ""          # e.g. https://login.microsoftonline.com/<tenant>/v2.0
    oidc_client_id: str = ""
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str = "http://localhost:8000/api/auth/callback"
    oidc_allowed_domains: list[str] = []  # e.g. ["aurak.ac.ae"]; empty = any
    session_secret: str = ""        # random 32+ bytes; required in sso mode
    cookie_secure: bool = False     # true behind HTTPS
    frontend_url: str = "http://localhost:5173"

    # LLM gateway (D10). none | fake | ollama | openai_compat | groq | openrouter | gemini
    llm_provider: str = "none"
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None

    # Gateway rate limit (plan 0.5a): max model calls per minute across the
    # process; free tiers allow ~5-15. 0 disables throttling.
    llm_max_rpm: int = 10
    # Embedding model for retrieval/duplicates (plan 2.2). Empty = built-in local
    # embedder (offline, nothing sent anywhere).
    llm_embed_model: str | None = None
    # Set true only for a provider contracted not to retain or train on inputs
    # (deployment, plan H.2). Until then real exam material (past exams) never
    # reaches a hosted model (plan 14.10 data hygiene).
    llm_no_retention: bool = False

    # Background jobs (plan 0.1/1.9/2.7):
    #   inline   - thread pool inside the API process (single-machine dev)
    #   external - a separate `python -m app.worker` process claims jobs (compose)
    #   sync     - run immediately in the request (tests)
    worker_mode: str = "inline"
    worker_threads: int = 2

    # Code execution for code_exercise items (plan 2.19): auto | docker | subprocess | off.
    # Production and any student code (Phase 4) must use docker.
    sandbox_mode: str = "auto"

    # The project team (plan 2.11 metrics dashboard is "for the team, not faculty").
    team_emails: list[str] = []
    # Read-only QA/accreditation viewers (plan 3.12): see coverage and syllabi, never items/exams.
    qa_viewer_emails: list[str] = []

    # Phase 4 Grading & Feedback Assist (plan 14.7). Off until the university's
    # data-protection approval (13.D) exists. When off, every grading route
    # answers 403 and the validator skips V13.
    grading_enabled: bool = False
    # Fernet key (base64, 32 bytes) for student identities at rest; required when
    # grading is on. Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Losing it makes stored identities unreadable; keep it with the DB backups, not in them.
    identity_key: str = ""
    # May anonymised student answers go to the configured model for rubric
    # suggestions? Only for the provider/hosting named in the approval (14.10).
    # Off: key-scoring and code tests still run; open answers get no suggestion.
    grading_llm_approved: bool = False
    # Item types whose suggestions missed the calibration gate stay manual (Gate 4).
    grading_suggest_off: list[str] = []

    # Phase 5 Blackboard (plan 14.8): off | mock | blackboard. "blackboard" needs IT
    # to register a Learn REST application (13.C): its key/secret and redirect URI.
    lms_mode: str = "off"
    blackboard_url: str = ""  # e.g. https://learn.aurak.ac.ae
    blackboard_app_key: str = ""
    blackboard_app_secret: str = ""
    blackboard_redirect_uri: str = "http://localhost:8000/api/lms/callback"

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
