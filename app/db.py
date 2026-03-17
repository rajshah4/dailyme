from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


def _normalize_db_url(url: str) -> tuple[str, dict]:
    """Normalize the database URL for asyncpg compatibility.

    asyncpg (via SQLAlchemy 2.0) requires:
    - Scheme: postgresql+asyncpg://
    - SSL via connect_args, not ?sslmode= query param
    - No channel_binding or other unsupported params
    """
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url.split("://", 1)[1]

    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    connect_args: dict = {}
    ssl_mode = params.pop("sslmode", [None])[0]
    params.pop("channel_binding", None)  # not supported by asyncpg
    if ssl_mode in ("require", "verify-ca", "verify-full"):
        connect_args["ssl"] = True
    elif ssl_mode == "disable":
        connect_args["ssl"] = False

    new_query = urlencode({k: v[0] for k, v in params.items()})
    clean_url = urlunparse(parsed._replace(query=new_query))
    return clean_url, connect_args


_db_url, _connect_args = _normalize_db_url(settings.database_url)

engine = create_async_engine(
    _db_url,
    echo=False,
    pool_pre_ping=True,  # Reconnect stale connections (Neon drops idle ones)
    pool_recycle=600,    # Recycle connections every 10 min (handles long LLM operations)
    connect_args=_connect_args,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
