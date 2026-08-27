"""StockRevenueLab 的 Supabase/PostgreSQL 連線入口。"""

from __future__ import annotations

import logging
import re
import urllib.parse
from pathlib import Path
import streamlit as st
from sqlalchemy import create_engine, text


logger = logging.getLogger(__name__)
_DEFAULT_POOLER_HOST = "aws-1-ap-southeast-1.pooler.supabase.com"

_SECTIONS = ("supabase", "postgres", "postgresql", "database", "db", "connections")
_ALIASES = {
    "url": (
        "DATABASE_URL",
        "SUPABASE_DB_URL",
        "POSTGRES_URL",
        "SQLALCHEMY_DATABASE_URI",
        "url",
    ),
    "password": (
        "DB_PASSWORD",
        "SUPABASE_PASSWORD",
        "POSTGRES_PASSWORD",
        "PASSWORD",
        "password",
    ),
    "project_ref": (
        "PROJECT_REF",
        "SUPABASE_PROJECT_REF",
        "SUPABASE_PROJECT_ID",
        "PROJECT_ID",
        "project_ref",
    ),
    "host": (
        "POOLER_HOST",
        "SUPABASE_POOLER_HOST",
        "DB_HOST",
        "HOST",
        "host",
    ),
    "port": ("POOLER_PORT", "DB_PORT", "PORT", "port"),
    "dbname": ("DB_NAME", "POSTGRES_DB", "DBNAME", "dbname"),
    "user": ("DB_USER", "POSTGRES_USER", "USER", "user"),
}

_SAMPLE_TOML = """\
# 建議直接貼 Supabase Dashboard -> Connect -> Session pooler 的 URI
DATABASE_URL = "postgresql://postgres.<PROJECT_REF>:<PASSWORD>@<POOLER_HOST>:5432/postgres"

# 或使用分開的欄位（可放在頂層或 [supabase] 區段）
DB_PASSWORD = "資料庫密碼"
PROJECT_REF = "Supabase project ref"
POOLER_HOST = "aws-0-<region>.pooler.supabase.com"
"""


def _lookup(container: object, name: str) -> str | None:
    try:
        value = container[name]  # type: ignore[index]
    except (KeyError, TypeError, AttributeError):
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _get_secret(kind: str, default: str | None = None) -> str | None:
    names = _ALIASES[kind]
    for name in names:
        value = _lookup(st.secrets, name)
        if value:
            return value
    for section in _SECTIONS:
        try:
            block = st.secrets[section]
        except (KeyError, TypeError, AttributeError):
            continue
        for name in names:
            value = _lookup(block, name)
            if value:
                return value
    return default


def _normalise_url(url: str) -> str:
    """固定 psycopg2 driver 與 sslmode；不改動已編碼的密碼。"""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://") :]
    if not url.startswith("postgresql+psycopg2://"):
        raise ValueError("DATABASE_URL 必須是 PostgreSQL 連線字串")
    separator = "&" if "?" in url else "?"
    if "sslmode=" not in url:
        url += f"{separator}sslmode=require"
    return url


def _connection_url() -> tuple[str, dict[str, str]]:
    direct_url = _get_secret("url")
    if direct_url:
        url = _normalise_url(direct_url)
        return url, {"mode": "DATABASE_URL"}

    password = _get_secret("password")
    project_ref = _get_secret("project_ref")
    # 此專案原始 Notebook 已固定使用 Supabase Singapore Session Pooler。
    # 保留 Secrets 覆寫能力，避免未來搬移 region 時需改程式碼。
    host = _get_secret("host", _DEFAULT_POOLER_HOST)
    port = _get_secret("port", "5432")
    dbname = _get_secret("dbname", "postgres")
    user = _get_secret("user") or (f"postgres.{project_ref}" if project_ref else None)

    missing = [
        label
        for label, value in (
            ("DB_PASSWORD", password),
            ("PROJECT_REF", project_ref),
        )
        if not value
    ]
    if missing:
        raise ValueError("Streamlit Secrets 缺少：" + "、".join(missing))

    encoded_user = urllib.parse.quote(user or "", safe=".")
    encoded_password = urllib.parse.quote(password or "", safe="")
    encoded_dbname = urllib.parse.quote(dbname or "postgres", safe="")
    url = (
        f"postgresql+psycopg2://{encoded_user}:{encoded_password}"
        f"@{host}:{port}/{encoded_dbname}?sslmode=require"
    )
    return url, {"host": host or "", "port": port or "", "dbname": dbname or ""}


def _redact(message: str, url: str = "") -> str:
    redacted = message
    if url:
        try:
            parsed = urllib.parse.urlsplit(url.replace("postgresql+psycopg2", "postgresql", 1))
            if parsed.password:
                for password in {parsed.password, urllib.parse.unquote(parsed.password)}:
                    if password:
                        redacted = redacted.replace(password, "***")
        except ValueError:
            pass
    redacted = re.sub(r"(postgres(?:ql)?(?:\+psycopg2)?://[^:\s]+:)[^@\s]+@", r"\1***@", redacted)
    return redacted


def _diagnose(message: str) -> str:
    low = message.lower()
    if "tenant or user not found" in low:
        return "PROJECT_REF、使用者名稱或 Pooler region 不匹配；請重新複製 Supabase Session pooler URI。"
    if "password authentication failed" in low:
        return "資料庫密碼不正確；更新 Streamlit Secrets 後重新啟動 App。"
    if "could not translate host name" in low or "name or service not known" in low:
        return "POOLER_HOST 無法解析；請重新複製 Session pooler 主機名稱。"
    if "timeout" in low or "timed out" in low:
        return "連線逾時；請確認 Supabase 專案未暫停，且使用 Session pooler。"
    if "connection refused" in low:
        return "連線被拒；請確認 Pooler 主機與連接埠。"
    if "ssl" in low:
        return "SSL 協商失敗；連線字串必須使用 sslmode=require。"
    return "請確認 Supabase 專案狀態，以及 Streamlit Secrets 中的 Session pooler URI。"


def _sync_latest_snapshot(engine) -> dict | None:
    snapshot_path = Path(__file__).resolve().parent / "data" / "latest_snapshot.json.gz"
    if not snapshot_path.exists():
        return None
    from snapshot_sync import apply_snapshot_file

    return apply_snapshot_file(engine, snapshot_path)


@st.cache_resource(show_spinner="連線資料庫中…")
def get_engine():
    try:
        url, endpoint = _connection_url()
    except ValueError as exc:
        logger.error("Database configuration invalid: %s", exc)
        st.error(f"❌ {exc}")
        st.markdown("請到 **Manage app → Settings → Secrets** 設定：")
        st.code(_SAMPLE_TOML, language="toml")
        st.stop()

    try:
        engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_size=2,
            max_overflow=3,
            connect_args={"connect_timeout": 10},
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("Database connectivity check failed: %s", type(exc).__name__)
        detail = _redact(str(exc), url)
        st.error(f"❌ 資料庫連線失敗：{type(exc).__name__}")
        st.warning(_diagnose(detail))
        with st.expander("技術細節（不含密碼）"):
            st.code(f"endpoint={endpoint}\n\n{detail}")
        st.stop()
    print("[db] connectivity check succeeded", flush=True)
    try:
        sync_result = _sync_latest_snapshot(engine)
        if sync_result:
            print("[snapshot-sync] " + str(sync_result), flush=True)
    except Exception as exc:
        logger.error("Bundled snapshot sync failed: %s", type(exc).__name__)
        st.warning("⚠️ 最新官方資料快照未能套用；目前顯示既有資料，請查看 Cloud logs。")
    return engine
