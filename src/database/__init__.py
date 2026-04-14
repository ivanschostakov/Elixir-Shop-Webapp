import json
from contextlib import asynccontextmanager
from logging import getLogger, Logger

from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from config import ASYNC_DATABASE_URL

__all__ = [
    "AsyncSessionLocal",
    "Base",
    "clear_tables",
    "engine",
    "get_db",
    "get_db_items",
    "get_session",
    "init_db",
]

@asynccontextmanager
async def get_session():
    async with AsyncSessionLocal() as session:
        try: yield session
        except Exception:
            await session.rollback()
            raise

engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=False,
    pool_size=10,                                    
    max_overflow=20,                                                
    pool_timeout=60,                                               
    pool_recycle=1800,                                                
    pool_pre_ping=True,                                             
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)

class BaseModelMixin:
    def to_dict(self) -> dict[str, object]: return {c.key: getattr(self, c.key) for c in inspect(self).mapper.column_attrs}
    def to_json(self) -> str: return json.dumps(self.to_dict(), default=str)

class Base(DeclarativeBase, BaseModelMixin): pass

async def init_db(recreate: bool):
    logger = getLogger(__name__)
    async with engine.begin() as conn:
        if recreate:
            logger.warning("Recreating entire database schema...")
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            logger.info("All tables dropped and recreated successfully.")
            
        else:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("All tables checked/created successfully.")

    logger.info("DB initialization complete.")

async def get_db() -> AsyncSession:
    session = AsyncSessionLocal()
    try: yield session
    except Exception:
        await session.rollback()
        raise
    
    finally: await session.close()

async def clear_tables(logger: Logger) -> None:
    try:
        async with engine.execution_options(isolation_level="AUTOCOMMIT").connect() as conn:
            result = await conn.execute(text("""SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename != 'alembic_version';"""))
            tables = [row[0] for row in result]
            if not tables: return logger.warning("No tables found to clear")
            
            table_list = ", ".join(f'"{t}"' for t in tables)
            logger.info(f"Clearing tables: {table_list}")
            await conn.execute(text(f"TRUNCATE {table_list} RESTART IDENTITY CASCADE;"))
            logger.info("Tables cleared successfully")

    except Exception as e:
        logger.error(f"Failed to clear tables: {e}")
        raise

async def get_db_items(logger: Logger) -> None:
    async with engine.connect() as conn:
        result = await conn.execute(text("""SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename; """))
        tables = [row[0] for row in result.fetchall()]
        if not tables: return logger.warning("No tables found in database")
        for table in tables:
            logger.debug(f"📋 Table: {table}")
            try:
                res = await conn.execute(text(f'SELECT * FROM "{table}";'))
                rows = res.fetchall()                  
                if not rows:
                    logger.debug("  (empty)")
                    continue
                colnames = res.keys()
                logger.debug("  Columns: " + ", ".join(colnames))
                for row in rows: logger.debug("  " + str(dict(zip(colnames, row))))
            except Exception as e: logger.error(f"  Failed to fetch {table}: {e}")
        return None
