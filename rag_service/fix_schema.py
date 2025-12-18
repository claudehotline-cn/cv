
from sqlalchemy import text
from rag_service.database import pgvector_engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_schema():
    with pgvector_engine.connect() as conn:
        logger.info("Tentative schema fix: Dropping content_ts if it exists to ensure it is not GENERATED...")
        try:
            conn.execute(text("ALTER TABLE rag_vectors DROP COLUMN IF EXISTS content_ts"))
            conn.commit()
            logger.info("Dropped content_ts column.")
        except Exception as e:
            logger.error(f"Error dropping column: {e}")
            
        try:
            conn.execute(text("ALTER TABLE rag_vectors ADD COLUMN content_ts TSVECTOR"))
            conn.commit()
            logger.info("Added content_ts column (manual).")
        except Exception as e:
            logger.error(f"Error adding column: {e}")
            
        try:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rag_vectors_content_ts ON rag_vectors USING GIN (content_ts)"))
            conn.commit()
            logger.info("Created GIN index.")
        except Exception as e:
            logger.error(f"Error creating index: {e}")

if __name__ == "__main__":
    fix_schema()
