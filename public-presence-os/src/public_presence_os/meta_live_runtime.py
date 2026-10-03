from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from .control import canonical_json


MODEL_VERSION = "PPOS_META_LIVE_READ_RUNTIME_V1"
EXPECTED_APP_ID = "1488219383133581"
EXPECTED_PAGE_ID = "2816314015107071"
EXPECTED_IG_ID = "17841429701593250"
EXPECTED_THREADS_ID = "28391623420464631"
EXPECTED_NAME = "Mihai Cismaru"
EXPECTED_USERNAME = "m.cismaru"
ALLOWED_HOSTS = ("graph.facebook.com", "graph.threads.net")
UNKNOWN = "UNKNOWN"

SECRET_ENV_NAMES = (
    "META_APP_SECRET",
    "META_USER_ACCESS_TOKEN",
    "META_PAGE_ACCESS_TOKEN",
    "META_THREADS_ACCESS_TOKEN",
)

_SECRET_KEYS = {
    "access_token",
    "app_secret",
    "client_secret",
    "authorization",
    "cookie",
    "password",
}


class MetaLiveHold(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise MetaLiveHold("HOLD_META_BOOLEAN_ENV_INVALID")


def _required_secret(values: Mapping[str, str], name: str) -> str:
    value = values.get(name, "")
    if not isinstance(value, str) or len(value.strip()) < 20 or any(ch.isspace() for ch in value):
        raise MetaLiveHold(f"HOLD_META_SECRET_MISSING_{name}")
    return value


def _identity(values: Mapping[str, str], name: str, expected: str) -> str:
    actual = values.get(name, expected)
    if actual != expected:
        raise MetaLiveHold(f"HOLD_META_IDENTITY_MISMATCH_{name}")
    return actual


@dataclass(frozen=True)
class MetaRuntimeConfig:
    app_id: str
    page_id: str
    ig_user_id: str
    threads_user_id: str
    graph_version: str
    threads_version: str
    user_token: str = field(repr=False)
    threads_token: str = field(repr=False)
    page_token: str | None = field(default=None, repr=False)
    app_secret: str | None = field(default=None, repr=False)
    kill_switch_engaged: bool = True
    live_write_enabled: bool = False

    @classmethod
    def from_env(cls, values: Mapping[str, str] | None = None) -> "MetaRuntimeConfig":
        env = os.environ if values is None else values
        app_id = _identity(env, "META_APP_ID", EXPECTED_APP_ID)
        page_id = _identity(env, "META_PAGE_ID", EXPECTED_PAGE_ID)
        ig_id = _identity(env, "META_IG_USER_ID", EXPECTED_IG_ID)
        threads_id = _identity(env, "META_THREADS_USER_ID", EXPECTED_THREADS_ID)
        graph_version = env.get("META_GRAPH_API_VERSION", "v26.0")
        threads_version = env.get("META_THREADS_API_VERSION", "v1.0")
        if not graph_version.startswith("v") or not threads_version.startswith("v"):
            raise MetaLiveHold("HOLD_META_API_VERSION_INVALID")
        user_token = _required_secret(env, "META_USER_ACCESS_TOKEN")
        threads_token = _required_secret(env, "META_THREADS_ACCESS_TOKEN")
        page_token = env.get("META_PAGE_ACCESS_TOKEN") or None
        if page_token is not None and len(page_token) < 20:
            raise MetaLiveHold("HOLD_META_SECRET_MISSING_META_PAGE_ACCESS_TOKEN")
        app_secret = env.get("META_APP_SECRET") or None
        if app_secret is not None and len(app_secret) < 8:
            raise MetaLiveHold("HOLD_META_SECRET_MISSING_META_APP_SECRET")
        return cls(
            app_id=app_id,
            page_id=page_id,
            ig_user_id=ig_id,
            threads_user_id=threads_id,
            graph_version=graph_version,
            threads_version=threads_version,
            user_token=user_token,
            threads_token=threads_token,
            page_token=page_token,
            app_secret=app_secret,
            kill_switch_engaged=_bool(env.get("KILL_SWITCH"), default=True),
            live_write_enabled=_bool(env.get("LIVE_WRITE"), default=False),
        )

    def redacted(self) -> dict[str, Any]:
        return {
            "app_id": self.app_id,
            "page_id": self.page_id,
            "ig_user_id": self.ig_user_id,
            "threads_user_id": self.threads_user_id,
            "graph_version": self.graph_version,
            "threads_version": self.threads_version,
            "user_token_present": True,
            "page_token_present": self.page_token is not None,
            "threads_token_present": True,
            "app_secret_present": self.app_secret is not None,
            "kill_switch_engaged": self.kill_switch_engaged,
            "live_write_enabled": self.live_write_enabled,
        }


class JsonOpener(Protocol):
    def open(self, request: Request, timeout: float): ...


class MetaReadClient:
    def __init__(
        self,
        *,
        opener: JsonOpener | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
        timeout_seconds: float = 20.0,
    ) -> None:
        if max_attempts < 1 or max_attempts > 4:
            raise MetaLiveHold("HOLD_META_RETRY_BUDGET_INVALID")
        self._opener = opener or build_opener()
        self._sleeper = sleeper
        self._max_attempts = max_attempts
        self._timeout = timeout_seconds

    def get(self, *, host: str, path: str, params: Mapping[str, str], token: str) -> dict[str, Any]:
        if host not in ALLOWED_HOSTS:
            raise MetaLiveHold("HOLD_META_HOST_NOT_ALLOWLISTED")
        if not path.startswith("/") or "?" in path or not token:
            raise MetaLiveHold("HOLD_META_REQUEST_INVALID")
        query = urlencode(sorted(params.items()))
        request = Request(
            f"https://{host}{path}?{query}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "PUBLIC-PRESENCE-OS/1.0",
            },
            method="GET",
        )
        for attempt in range(1, self._max_attempts + 1):
            try:
                with self._opener.open(request, timeout=self._timeout) as response:
                    data = response.read(8 * 1024 * 1024 + 1)
                if len(data) > 8 * 1024 * 1024:
                    raise MetaLiveHold("HOLD_META_RESPONSE_TOO_LARGE")
                payload = json.loads(data.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise MetaLiveHold("HOLD_META_RESPONSE_NOT_OBJECT")
                return payload
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code <= 599
                if not retryable or attempt == self._max_attempts:
                    raise MetaLiveHold(f"HOLD_META_HTTP_{exc.code}") from None
                delay = min(float(exc.headers.get("Retry-After", "1") or "1"), 30.0)
            except (URLError, TimeoutError):
                if attempt == self._max_attempts:
                    raise MetaLiveHold("HOLD_META_TRANSPORT_EXHAUSTED") from None
                delay = float(attempt)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise MetaLiveHold("HOLD_META_RESPONSE_INVALID_JSON") from None
            self._sleeper(delay)
        raise MetaLiveHold("HOLD_META_TRANSPORT_EXHAUSTED")


def _contains_secret_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered in _SECRET_KEYS or lowered.endswith("_token") or lowered.endswith("_secret"):
                return True
            if _contains_secret_key(child):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_secret_key(child) for child in value)
    return False


@dataclass(frozen=True)
class IngestReceipt:
    event_id: str
    action: str
    platform: str
    object_type: str
    external_id: str
    cursor: str


class MetaEventStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta_events (
                    event_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    platform TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    normalized_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta_cursors (
                    stream_key TEXT PRIMARY KEY,
                    cursor_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta_sync_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    state TEXT NOT NULL,
                    accepted_count INTEGER NOT NULL DEFAULT 0,
                    duplicate_count INTEGER NOT NULL DEFAULT 0,
                    hold_reason TEXT
                );
                """
            )

    def healthcheck(self) -> bool:
        with self._connect() as connection:
            return connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"

    def cursor(self, stream_key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT cursor_value FROM meta_cursors WHERE stream_key=?", (stream_key,)
            ).fetchone()
        return None if row is None else str(row[0])

    def set_cursor(self, stream_key: str, value: str, *, updated_at: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO meta_cursors(stream_key,cursor_value,updated_at) VALUES(?,?,?)
                ON CONFLICT(stream_key) DO UPDATE SET cursor_value=excluded.cursor_value,
                updated_at=excluded.updated_at""",
                (stream_key, value, updated_at),
            )

    def start_sync(self, run_id: str, *, started_at: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO meta_sync_runs(run_id,started_at,state) VALUES(?,?,?)",
                (run_id, started_at, "RUNNING"),
            )

    def finish_sync(
        self,
        run_id: str,
        *,
        completed_at: str,
        state: str,
        accepted_count: int,
        duplicate_count: int,
        hold_reason: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE meta_sync_runs SET completed_at=?,state=?,accepted_count=?,
                duplicate_count=?,hold_reason=? WHERE run_id=?""",
                (completed_at, state, accepted_count, duplicate_count, hold_reason, run_id),
            )

    def sync_runs(self) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT run_id,started_at,completed_at,state,accepted_count,
                duplicate_count,hold_reason FROM meta_sync_runs ORDER BY started_at,run_id"""
            ).fetchall()
        return tuple(
            {
                "run_id": row[0],
                "started_at": row[1],
                "completed_at": row[2],
                "state": row[3],
                "accepted_count": row[4],
                "duplicate_count": row[5],
                "hold_reason": row[6],
            }
            for row in rows
        )

    def ingest(
        self,
        *,
        platform: str,
        object_type: str,
        external_id: str,
        observed_at: str,
        fetched_at: str,
        provenance: str,
        normalized: Mapping[str, Any],
        cursor: str,
    ) -> IngestReceipt:
        if _contains_secret_key(normalized):
            raise MetaLiveHold("HOLD_META_SECRET_BEARING_EVENT")
        if not external_id or not observed_at or not fetched_at:
            raise MetaLiveHold("HOLD_META_EVENT_IDENTITY_MISSING")
        body = {
            "platform": platform,
            "object_type": object_type,
            "external_id": external_id,
            "observed_at": observed_at,
            "provenance": provenance,
            "normalized": normalized,
        }
        fingerprint = sha256(canonical_json(body).encode("utf-8")).hexdigest()
        event_id = "mle_" + fingerprint[:28]
        stream_key = f"{platform}:{object_type}"
        with self._connect() as connection:
            accepted = connection.execute(
                """INSERT OR IGNORE INTO meta_events
                (event_id,fingerprint,platform,object_type,external_id,observed_at,fetched_at,provenance,normalized_json)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    event_id,
                    fingerprint,
                    platform,
                    object_type,
                    external_id,
                    observed_at,
                    fetched_at,
                    provenance,
                    canonical_json(normalized),
                ),
            ).rowcount == 1
            connection.execute(
                """INSERT INTO meta_cursors(stream_key,cursor_value,updated_at) VALUES(?,?,?)
                ON CONFLICT(stream_key) DO UPDATE SET cursor_value=excluded.cursor_value,
                updated_at=excluded.updated_at""",
                (stream_key, cursor, fetched_at),
            )
        return IngestReceipt(
            event_id=event_id,
            action="ACCEPTED" if accepted else "DUPLICATE_NOOP",
            platform=platform,
            object_type=object_type,
            external_id=external_id,
            cursor=cursor,
        )

    def events(self, *, after_rowid: int = 0) -> tuple[dict[str, Any], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT rowid,event_id,platform,object_type,external_id,observed_at,fetched_at,
                provenance,normalized_json FROM meta_events WHERE rowid>? ORDER BY rowid""",
                (after_rowid,),
            ).fetchall()
        return tuple(
            {
                "rowid": row[0],
                "event_id": row[1],
                "platform": row[2],
                "object_type": row[3],
                "external_id": row[4],
                "observed_at": row[5],
                "fetched_at": row[6],
                "provenance": row[7],
                "normalized": json.loads(row[8]),
            }
            for row in rows
        )


def _data(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("data")
    if not isinstance(value, list):
        raise MetaLiveHold("HOLD_META_COLLECTION_DATA_MISSING")
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _next_cursor(payload: Mapping[str, Any], fallback: str) -> str:
    paging = payload.get("paging")
    if isinstance(paging, Mapping):
        cursors = paging.get("cursors")
        if isinstance(cursors, Mapping) and isinstance(cursors.get("after"), str):
            return str(cursors["after"])
    return fallback


def _observed(item: Mapping[str, Any], fetched_at: str) -> str:
    for key in ("created_time", "timestamp"):
        if isinstance(item.get(key), str) and item[key]:
            return str(item[key])
    return fetched_at


def _safe_item(item: Mapping[str, Any]) -> dict[str, Any]:
    if _contains_secret_key(item):
        raise MetaLiveHold("HOLD_META_SECRET_BEARING_RESPONSE_BOUNDARY")
    return json.loads(canonical_json(item))


@dataclass(frozen=True)
class SyncSummary:
    state: str
    identities: tuple[tuple[str, str], ...]
    accepted: int
    duplicates: int
    holds: tuple[str, ...]
    write_count: int = 0


class MetaReadRuntime:
    def __init__(self, config: MetaRuntimeConfig, client: MetaReadClient, store: MetaEventStore) -> None:
        self.config = config
        self.client = client
        self.store = store

    def _get(self, platform: str, path: str, params: Mapping[str, str], token: str) -> dict[str, Any]:
        host = "graph.threads.net" if platform == "THREADS" else "graph.facebook.com"
        return self.client.get(host=host, path=path, params=params, token=token)

    def sync_once(self) -> SyncSummary:
        if not self.config.kill_switch_engaged or self.config.live_write_enabled:
            raise MetaLiveHold("HOLD_META_READ_RUNTIME_SAFETY_STATE")
        started_at = _utc_now()
        run_id = "mlr_" + sha256(
            f"{started_at}:{time.time_ns()}:{self.config.page_id}".encode("utf-8")
        ).hexdigest()[:28]
        self.store.start_sync(run_id, started_at=started_at)
        try:
            summary = self._sync_once_inner()
        except MetaLiveHold as exc:
            self.store.finish_sync(
                run_id,
                completed_at=_utc_now(),
                state="HOLD",
                accepted_count=0,
                duplicate_count=0,
                hold_reason=exc.reason,
            )
            raise
        self.store.finish_sync(
            run_id,
            completed_at=_utc_now(),
            state=summary.state,
            accepted_count=summary.accepted,
            duplicate_count=summary.duplicates,
            hold_reason=";".join(summary.holds) or None,
        )
        return summary

    def _page_authority(self) -> tuple[str, dict[str, Any]]:
        fields = "id,name,tasks,instagram_business_account"
        if self.config.page_token is None:
            fields += ",access_token"
        payload = self._get(
            "FACEBOOK_PAGE",
            f"/{self.config.graph_version}/me/accounts",
            {"fields": fields, "limit": "100"},
            self.config.user_token,
        )
        matches = [item for item in _data(payload) if item.get("id") == self.config.page_id]
        if len(matches) != 1:
            raise MetaLiveHold("HOLD_META_PAGE_NOT_ACCESSIBLE")
        page = matches[0]
        linked = page.get("instagram_business_account")
        if page.get("name") != EXPECTED_NAME:
            raise MetaLiveHold("HOLD_META_PAGE_NAME_MISMATCH")
        if not isinstance(linked, Mapping) or linked.get("id") != self.config.ig_user_id:
            raise MetaLiveHold("HOLD_META_INSTAGRAM_BINDING_MISMATCH")
        token = self.config.page_token or page.get("access_token")
        if not isinstance(token, str) or len(token) < 20:
            raise MetaLiveHold("HOLD_META_PAGE_AUTHORITY_MISSING")
        page.pop("access_token", None)
        return token, page

    def _ingest_collection(
        self,
        *,
        platform: str,
        object_type: str,
        payload: Mapping[str, Any],
        fetched_at: str,
        provenance: str,
    ) -> tuple[int, int]:
        accepted = duplicates = 0
        items = _data(payload)
        cursor = _next_cursor(payload, sha256(canonical_json(items).encode("utf-8")).hexdigest())
        for item in items:
            external_id = item.get("id")
            if not isinstance(external_id, str) or not external_id:
                continue
            receipt = self.store.ingest(
                platform=platform,
                object_type=object_type,
                external_id=external_id,
                observed_at=_observed(item, fetched_at),
                fetched_at=fetched_at,
                provenance=provenance,
                normalized=_safe_item(item),
                cursor=cursor,
            )
            if receipt.action == "ACCEPTED":
                accepted += 1
            else:
                duplicates += 1
        return accepted, duplicates

    def _sync_once_inner(self) -> SyncSummary:
        if not self.config.kill_switch_engaged or self.config.live_write_enabled:
            raise MetaLiveHold("HOLD_META_READ_RUNTIME_SAFETY_STATE")
        fetched_at = _utc_now()
        accepted = duplicates = 0
        identities: list[tuple[str, str]] = []
        holds: list[str] = []

        page_token, managed_page = self._page_authority()
        identities.append(("FACEBOOK_PAGE", str(managed_page["id"])))
        page_identity = self._get(
            "FACEBOOK_PAGE",
            f"/{self.config.graph_version}/{self.config.page_id}",
            {"fields": "id,name,instagram_business_account"},
            page_token,
        )
        if page_identity.get("id") != self.config.page_id or page_identity.get("name") != EXPECTED_NAME:
            raise MetaLiveHold("HOLD_META_PAGE_IDENTITY_MISMATCH")

        posts = self._get(
            "FACEBOOK_PAGE",
            f"/{self.config.graph_version}/{self.config.page_id}/posts",
            {"fields": "id,message,created_time,permalink_url", "limit": "50"},
            page_token,
        )
        a, d = self._ingest_collection(
            platform="FACEBOOK_PAGE", object_type="POST", payload=posts,
            fetched_at=fetched_at, provenance="META_GRAPH_PAGE_POSTS",
        )
        accepted += a; duplicates += d
        for post in _data(posts):
            post_id = post.get("id")
            if not isinstance(post_id, str):
                continue
            comments = self._get(
                "FACEBOOK_PAGE",
                f"/{self.config.graph_version}/{post_id}/comments",
                {"fields": "id,message,created_time,from,parent", "limit": "100"},
                page_token,
            )
            a, d = self._ingest_collection(
                platform="FACEBOOK_PAGE", object_type="COMMENT", payload=comments,
                fetched_at=fetched_at, provenance=f"META_GRAPH_PAGE_COMMENTS:{post_id}",
            )
            accepted += a; duplicates += d

        ig_identity = self._get(
            "INSTAGRAM_PROFESSIONAL",
            f"/{self.config.graph_version}/{self.config.ig_user_id}",
            {"fields": "id,username,name,media_count"},
            page_token,
        )
        if (
            ig_identity.get("id") != self.config.ig_user_id
            or ig_identity.get("username") != EXPECTED_USERNAME
            or ig_identity.get("name") != EXPECTED_NAME
        ):
            raise MetaLiveHold("HOLD_META_INSTAGRAM_IDENTITY_MISMATCH")
        identities.append(("INSTAGRAM_PROFESSIONAL", self.config.ig_user_id))
        media = self._get(
            "INSTAGRAM_PROFESSIONAL",
            f"/{self.config.graph_version}/{self.config.ig_user_id}/media",
            {"fields": "id,caption,media_type,permalink,timestamp,username,comments_count,like_count", "limit": "50"},
            page_token,
        )
        a, d = self._ingest_collection(
            platform="INSTAGRAM_PROFESSIONAL", object_type="MEDIA", payload=media,
            fetched_at=fetched_at, provenance="META_GRAPH_INSTAGRAM_MEDIA",
        )
        accepted += a; duplicates += d
        for item in _data(media):
            media_id = item.get("id")
            if not isinstance(media_id, str):
                continue
            try:
                comments = self._get(
                    "INSTAGRAM_PROFESSIONAL",
                    f"/{self.config.graph_version}/{media_id}/comments",
                    {"fields": "id,text,timestamp,username,from,parent_id", "limit": "100"},
                    page_token,
                )
            except MetaLiveHold as exc:
                holds.append(f"INSTAGRAM_COMMENTS:{exc.reason}")
                continue
            a, d = self._ingest_collection(
                platform="INSTAGRAM_PROFESSIONAL", object_type="COMMENT", payload=comments,
                fetched_at=fetched_at, provenance=f"META_GRAPH_INSTAGRAM_COMMENTS:{media_id}",
            )
            accepted += a; duplicates += d

        threads_identity = self._get(
            "THREADS",
            f"/{self.config.threads_version}/me",
            {"fields": "id,username,name"},
            self.config.threads_token,
        )
        if (
            threads_identity.get("id") != self.config.threads_user_id
            or threads_identity.get("username") != EXPECTED_USERNAME
            or threads_identity.get("name") != EXPECTED_NAME
        ):
            raise MetaLiveHold("HOLD_META_THREADS_IDENTITY_MISMATCH")
        identities.append(("THREADS", self.config.threads_user_id))
        threads = self._get(
            "THREADS",
            f"/{self.config.threads_version}/me/threads",
            {"fields": "id,media_product_type,media_type,permalink,username,text,timestamp,is_quote_post,has_replies", "limit": "50"},
            self.config.threads_token,
        )
        a, d = self._ingest_collection(
            platform="THREADS", object_type="POST", payload=threads,
            fetched_at=fetched_at, provenance="THREADS_GRAPH_OWN_POSTS",
        )
        accepted += a; duplicates += d
        for thread in _data(threads):
            if not thread.get("has_replies"):
                continue
            thread_id = thread.get("id")
            if not isinstance(thread_id, str):
                continue
            try:
                replies = self._get(
                    "THREADS",
                    f"/{self.config.threads_version}/{thread_id}/replies",
                    {"fields": "id,text,timestamp,username,is_reply,is_reply_owned_by_me,root_post,replied_to", "limit": "100"},
                    self.config.threads_token,
                )
            except MetaLiveHold as exc:
                holds.append(f"THREADS_REPLIES:{exc.reason}")
                continue
            a, d = self._ingest_collection(
                platform="THREADS", object_type="REPLY", payload=replies,
                fetched_at=fetched_at, provenance=f"THREADS_GRAPH_REPLIES:{thread_id}",
            )
            accepted += a; duplicates += d

        return SyncSummary(
            state="READ_ONLY_REAL_SYNC_PASS" if not holds else "READ_ONLY_REAL_SYNC_PARTIAL",
            identities=tuple(identities),
            accepted=accepted,
            duplicates=duplicates,
            holds=tuple(holds),
        )


def environment_presence(values: Mapping[str, str] | None = None) -> dict[str, bool]:
    env = os.environ if values is None else values
    names = (
        "META_APP_ID",
        "META_APP_SECRET",
        "META_USER_ACCESS_TOKEN",
        "META_PAGE_ACCESS_TOKEN",
        "META_PAGE_ID",
        "META_IG_USER_ID",
        "META_THREADS_USER_ID",
        "META_THREADS_ACCESS_TOKEN",
    )
    return {name: bool(env.get(name)) for name in names}


def preflight_report(
    *,
    db_path: str | Path,
    values: Mapping[str, str] | None = None,
    run_live_read: bool = False,
    client: MetaReadClient | None = None,
) -> dict[str, str]:
    store = MetaEventStore(db_path)
    report = {
        "META APP": "FAIL",
        "FACEBOOK AUTH": "FAIL",
        "PAGE IDENTITY": "FAIL",
        "INSTAGRAM BINDING": "FAIL",
        "THREADS IDENTITY": "FAIL",
        "READ CAPABILITIES": "FAIL",
        "WRITE CAPABILITIES": "LOCKED",
        "WEBHOOKS": "HOLD",
        "EVENT LOG": "PASS" if store.healthcheck() else "FAIL",
        "KILL SWITCH": "ENGAGED",
        "LIVE AUTHORITY": "NONE",
    }
    try:
        config = MetaRuntimeConfig.from_env(values)
    except MetaLiveHold:
        return report
    report["META APP"] = "PASS" if config.app_id == EXPECTED_APP_ID else "FAIL"
    report["FACEBOOK AUTH"] = "PASS"
    report["KILL SWITCH"] = "ENGAGED" if config.kill_switch_engaged else "DISENGAGED"
    if not config.kill_switch_engaged or config.live_write_enabled:
        return report
    report["LIVE AUTHORITY"] = "LIMITED" if run_live_read else "NONE"
    if not run_live_read:
        return report
    try:
        summary = MetaReadRuntime(config, client or MetaReadClient(), store).sync_once()
    except MetaLiveHold:
        return report
    observed = dict(summary.identities)
    report["PAGE IDENTITY"] = "PASS" if observed.get("FACEBOOK_PAGE") == EXPECTED_PAGE_ID else "FAIL"
    report["INSTAGRAM BINDING"] = "PASS" if observed.get("INSTAGRAM_PROFESSIONAL") == EXPECTED_IG_ID else "FAIL"
    report["THREADS IDENTITY"] = "PASS" if observed.get("THREADS") == EXPECTED_THREADS_ID else "FAIL"
    if (
        summary.state == "READ_ONLY_REAL_SYNC_PASS"
        and all(report[key] == "PASS" for key in ("PAGE IDENTITY", "INSTAGRAM BINDING", "THREADS IDENTITY"))
    ):
        report["READ CAPABILITIES"] = "PASS"
        report["LIVE AUTHORITY"] = "LIMITED"
    return report
