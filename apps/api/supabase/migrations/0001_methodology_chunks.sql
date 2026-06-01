-- xhs-copilot v1.1 — methodology RAG store
--
-- Run this in Supabase SQL editor (or psql) once before ingestion.
-- Dimensions default to 1024 (matches Zhipu embedding-3 with dimensions=1024).
-- If you switch providers / dimensions, change vector(1024) and the function signature
-- consistently, and re-run.

create extension if not exists vector;

create table if not exists methodology_chunks (
    id          bigserial primary key,
    category    text        not null,
    section     text        not null,
    content     text        not null,
    metadata    jsonb       not null default '{}'::jsonb,
    embedding   vector(1024) not null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists methodology_chunks_category_idx
    on methodology_chunks (category);

-- ivfflat is good enough for a few hundred chunks. For 10K+ consider HNSW.
create index if not exists methodology_chunks_embedding_idx
    on methodology_chunks using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

-- RPC used by apps/api/rag/store.py
create or replace function search_methodology_chunks(
    query_embedding vector(1024),
    match_count     int default 8,
    min_similarity  float default 0.0
)
returns table (
    id          bigint,
    category    text,
    section     text,
    content     text,
    similarity  float
)
language sql
stable
as $$
    select
        c.id,
        c.category,
        c.section,
        c.content,
        1 - (c.embedding <=> query_embedding) as similarity
    from methodology_chunks c
    where 1 - (c.embedding <=> query_embedding) >= min_similarity
    order by c.embedding <=> query_embedding
    limit match_count;
$$;
