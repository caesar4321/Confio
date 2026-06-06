from django.db import migrations


CREATE_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS content_ingestion_memory_chunk (
    chunk_key varchar(64) PRIMARY KEY,
    source_path varchar(500) NOT NULL,
    category varchar(64) NOT NULL,
    title varchar(500) NOT NULL,
    heading varchar(500) NOT NULL,
    content text NOT NULL,
    embedding vector(768) NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS content_memory_category_idx
    ON content_ingestion_memory_chunk (category);

CREATE INDEX IF NOT EXISTS content_memory_embedding_hnsw_idx
    ON content_ingestion_memory_chunk
    USING hnsw (embedding vector_cosine_ops);
"""


DROP_SQL = """
DROP TABLE IF EXISTS content_ingestion_memory_chunk;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('content_ingestion', '0002_expand_canonical_memory_categories'),
    ]

    operations = [
        migrations.RunSQL(CREATE_SQL, reverse_sql=DROP_SQL),
    ]

