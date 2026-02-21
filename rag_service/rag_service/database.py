"""数据库连接管理"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
import logging

from .config import settings
from .models import Base

logger = logging.getLogger(__name__)


# MySQL连接（元数据存储）
mysql_engine = create_engine(
    settings.mysql_dsn,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=settings.debug,
)
MySQLSessionLocal = sessionmaker(bind=mysql_engine, autocommit=False, autoflush=False)


# pgvector连接（向量存储）
pgvector_engine = create_engine(
    settings.pgvector_dsn,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=settings.debug,
)
PGVectorSessionLocal = sessionmaker(bind=pgvector_engine, autocommit=False, autoflush=False)


def init_mysql_db():
    """初始化MySQL数据库表"""
    # 首先确保数据库存在
    engine_without_db = create_engine(
        f"mysql+pymysql://{settings.mysql_user}:{settings.mysql_password}@{settings.mysql_host}:{settings.mysql_port}",
        isolation_level="AUTOCOMMIT",
    )
    with engine_without_db.connect() as conn:
        conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {settings.mysql_database}"))
    engine_without_db.dispose()
    
    # 创建表
    Base.metadata.create_all(bind=mysql_engine)

    # Best-effort schema migration (no Alembic in this repo).
    # MySQL does not reliably support `ADD COLUMN IF NOT EXISTS` across versions, so we check information_schema.
    try:
        with mysql_engine.connect() as conn:
            tenant_tables = [
                "rag_knowledge_bases",
                "rag_documents",
                "rag_document_outlines",
                "rag_chat_sessions",
                "rag_eval_datasets",
                "rag_benchmark_runs",
            ]
            for table_name in tenant_tables:
                exists_res = conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.columns
                        WHERE table_schema = :db
                          AND table_name = :table
                          AND column_name = 'tenant_id'
                        """
                    ),
                    {"db": settings.mysql_database, "table": table_name},
                )
                has_tenant_col = int(exists_res.scalar() or 0) > 0
                if not has_tenant_col:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN tenant_id VARCHAR(36) NULL"))
                    conn.commit()
                    logger.info("MySQL migration: added %s.tenant_id", table_name)

                idx_name = f"idx_{table_name}_tenant_id"
                idx_res = conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.statistics
                        WHERE table_schema = :db
                          AND table_name = :table
                          AND index_name = :idx
                        """
                    ),
                    {"db": settings.mysql_database, "table": table_name, "idx": idx_name},
                )
                has_idx = int(idx_res.scalar() or 0) > 0
                if not has_idx:
                    conn.execute(text(f"CREATE INDEX {idx_name} ON {table_name}(tenant_id)"))
                    conn.commit()
                    logger.info("MySQL migration: added index %s", idx_name)

            res = conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM information_schema.columns
                    WHERE table_schema = :db
                      AND table_name = 'rag_knowledge_bases'
                      AND column_name = 'cleaning_rules'
                    """
                ),
                {"db": settings.mysql_database},
            )
            exists = int(res.scalar() or 0) > 0
            if not exists:
                conn.execute(text("ALTER TABLE rag_knowledge_bases ADD COLUMN cleaning_rules TEXT NULL"))
                conn.commit()
                logger.info("MySQL migration: added rag_knowledge_bases.cleaning_rules")

            default_tenant_id = settings.auth_default_tenant_id
            for table_name in tenant_tables:
                conn.execute(
                    text(f"UPDATE {table_name} SET tenant_id = :tenant_id WHERE tenant_id IS NULL"),
                    {"tenant_id": default_tenant_id},
                )
            conn.commit()
    except Exception as e:
        logger.warning(f"MySQL migration (cleaning_rules) skipped due to error: {e}")

    logger.info("MySQL tables initialized")


def init_pgvector_db():
    """初始化pgvector数据库（创建扩展和表）"""
    with pgvector_engine.connect() as conn:
        # 创建pgvector扩展
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()

        # 维度迁移：如果现有 rag_vectors 的向量维度与配置不一致，则保留旧表并新建新表。
        try:
            reg = conn.execute(text("SELECT to_regclass('public.rag_vectors')"))
            has_table = reg.scalar() is not None
            if has_table:
                type_row = conn.execute(
                    text(
                        """
                        SELECT pg_catalog.format_type(a.atttypid, a.atttypmod) AS type
                        FROM pg_attribute a
                        JOIN pg_class c ON a.attrelid = c.oid
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'public'
                          AND c.relname = 'rag_vectors'
                          AND a.attname = 'embedding'
                          AND a.attnum > 0
                          AND NOT a.attisdropped
                        """
                    )
                ).fetchone()
                if type_row and isinstance(type_row[0], str) and type_row[0].startswith("vector("):
                    old_dim_str = type_row[0].split("(", 1)[1].split(")", 1)[0]
                    old_dim = int(old_dim_str)
                    if old_dim != settings.vector_dimension:
                        old_table = f"rag_vectors_{old_dim}"
                        exists_old = conn.execute(
                            text("SELECT to_regclass(:tname)"),
                            {"tname": f"public.{old_table}"},
                        ).scalar()

                        if exists_old is None:
                            logger.warning(
                                "pgvector: rag_vectors is vector(%s) but config wants vector(%s); renaming to %s and creating a fresh rag_vectors",
                                old_dim,
                                settings.vector_dimension,
                                old_table,
                            )
                            conn.execute(text(f"ALTER TABLE rag_vectors RENAME TO {old_table}"))
                            conn.commit()
                        else:
                            logger.warning(
                                "pgvector: rag_vectors dimension mismatch (vector(%s) -> vector(%s)); %s already exists; keeping existing tables",
                                old_dim,
                                settings.vector_dimension,
                                old_table,
                            )
        except Exception as e:
            logger.warning(f"pgvector: dimension check/migration skipped due to error: {e}")
        
        # 创建向量存储表
        # 注意: content_ts 用于全文检索 (由应用层分词后写入)
        # parent_id 和 is_parent 用于父子索引策略
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS rag_vectors (
                    id SERIAL PRIMARY KEY,
                    document_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding vector({settings.vector_dimension}) NOT NULL,
                    metadata JSONB DEFAULT '{{}}',
                    content_ts TSVECTOR,
                    parent_id INTEGER,
                    is_parent BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.commit()
        
        # 添加缺失的列 (用于现有表的迁移)
        migration_cols = [
            ("content_ts", "TSVECTOR"),
            ("parent_id", "INTEGER"),
            ("is_parent", "BOOLEAN DEFAULT FALSE"),
        ]
        for col_name, col_type in migration_cols:
            try:
                conn.execute(text(f"""
                    ALTER TABLE rag_vectors 
                    ADD COLUMN IF NOT EXISTS {col_name} {col_type}
                """))
                conn.commit()
            except Exception as e:
                logger.warning(f"Could not add column {col_name}: {e}")

        # 创建索引
        # 注意：如果历史表曾使用过 idx_rag_vectors_* 名称，这里使用带维度后缀的新索引名，避免重名导致新表缺索引。
        dim_suffix = str(settings.vector_dimension)
        conn.execute(
            text(
                f"""
                CREATE INDEX IF NOT EXISTS idx_rag_vectors_document_id_{dim_suffix}
                ON rag_vectors(document_id)
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE INDEX IF NOT EXISTS idx_rag_vectors_embedding_{dim_suffix}
                ON rag_vectors USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
                """
            )
        )
        try:
            conn.execute(
                text(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_rag_vectors_content_ts_{dim_suffix}
                    ON rag_vectors USING GIN (content_ts)
                    """
                )
            )
            conn.commit()
        except:
            pass # 索引可能已存在
        
        # 父子索引: 为 parent_id 创建索引
        try:
            conn.execute(
                text(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_rag_vectors_parent_id_{dim_suffix}
                    ON rag_vectors(parent_id)
                    """
                )
            )
            conn.commit()
        except:
            pass
        
    logger.info("pgvector tables initialized")


@contextmanager
def get_mysql_session() -> Session:
    """获取MySQL会话"""
    session = MySQLSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager  
def get_pgvector_session() -> Session:
    """获取pgvector会话"""
    session = PGVectorSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_mysql_db():
    """FastAPI依赖注入：获取MySQL会话"""
    db = MySQLSessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_pgvector_db():
    """FastAPI依赖注入：获取pgvector会话"""
    db = PGVectorSessionLocal()
    try:
        yield db
    finally:
        db.close()
