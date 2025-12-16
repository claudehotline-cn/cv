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
    logger.info("MySQL tables initialized")


def init_pgvector_db():
    """初始化pgvector数据库（创建扩展和表）"""
    with pgvector_engine.connect() as conn:
        # 创建pgvector扩展
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
        
        # 创建向量存储表
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS rag_vectors (
                id SERIAL PRIMARY KEY,
                document_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding vector({settings.vector_dimension}) NOT NULL,
                metadata JSONB DEFAULT '{{}}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()
        
        # 创建索引
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_rag_vectors_document_id 
            ON rag_vectors(document_id)
        """))
        conn.execute(text(f"""
            CREATE INDEX IF NOT EXISTS idx_rag_vectors_embedding 
            ON rag_vectors USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
        """))
        conn.commit()
        
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
