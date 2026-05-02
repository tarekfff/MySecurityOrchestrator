-- Run this in your Supabase SQL Editor before ingestion.

-- 1. Enable pgvector
create extension if not exists vector;

-- 2. Main chunks table
--    Gemini text-embedding-004 produces 768-dimensional vectors.
create table if not exists cyber_chunks (
    id          uuid primary key default gen_random_uuid(),
    chunk_id    text unique not null,       -- deterministic: topic_type_index
    topic       text not null,              -- e.g. "xss", "sql_injection"
    type        text not null,              -- introduction | symptoms | detection | exploitation | mitigation
    content     text not null,
    tags        text[] default '{}',
    source      text default 'WAHH',        -- Web Application Hacker's Handbook
    page_start  int,
    page_end    int,
    embedding   vector(768),
    created_at  timestamptz default now()
);

-- 3. Indexes
create index if not exists cyber_chunks_topic_idx  on cyber_chunks (topic);
create index if not exists cyber_chunks_type_idx   on cyber_chunks (type);
create index if not exists cyber_chunks_embed_idx  on cyber_chunks
    using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

-- 4. Similarity search RPC
--    Called by the retriever with an optional topic/type filter.
create or replace function match_cyber_chunks(
    query_embedding  vector(768),
    match_count      int      default 10,
    filter_topic     text     default null,
    filter_type      text     default null,
    min_similarity   float    default 0.0
)
returns table (
    id           uuid,
    chunk_id     text,
    topic        text,
    type         text,
    content      text,
    tags         text[],
    source       text,
    page_start   int,
    page_end     int,
    similarity   float
)
language plpgsql
as $$
begin
    return query
    select
        c.id,
        c.chunk_id,
        c.topic,
        c.type,
        c.content,
        c.tags,
        c.source,
        c.page_start,
        c.page_end,
        (1 - (c.embedding <=> query_embedding))::float as similarity
    from cyber_chunks c
    where
        (filter_topic is null or c.topic = filter_topic)
        and (filter_type is null or c.type = filter_type)
        and (1 - (c.embedding <=> query_embedding)) >= min_similarity
    order by c.embedding <=> query_embedding
    limit match_count;
end;
$$;

-- 5. Topic listing helper
create or replace function list_topics()
returns table(topic text, chunk_count bigint)
language sql
as $$
    select topic, count(*) as chunk_count
    from cyber_chunks
    group by topic
    order by chunk_count desc;
$$;
