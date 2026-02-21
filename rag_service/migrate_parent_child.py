"""Add parent_id and is_parent columns for Parent-Child indexing"""

from sqlalchemy import text
from rag_service.database import pgvector_engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_schema():
    with pgvector_engine.connect() as conn:
        # Add parent_id column
        try:
            conn.execute(text("ALTER TABLE rag_vectors ADD COLUMN IF NOT EXISTS parent_id INTEGER"))
            conn.commit()
            logger.info("Added parent_id column.")
        except Exception as e:
            logger.error(f"Error adding parent_id: {e}")
            
        # Add is_parent column
        try:
            conn.execute(text("ALTER TABLE rag_vectors ADD COLUMN IF NOT EXISTS is_parent BOOLEAN DEFAULT FALSE"))
            conn.commit()
            logger.info("Added is_parent column.")
        except Exception as e:
            logger.error(f"Error adding is_parent: {e}")
            
        # Create index on parent_id
        try:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rag_vectors_parent_id ON rag_vectors(parent_id)"))
            conn.commit()
            logger.info("Created parent_id index.")
        except Exception as e:
            logger.error(f"Error creating index: {e}")

if __name__ == "__main__":
    migrate_schema()
