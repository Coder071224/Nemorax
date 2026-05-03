create extension if not exists vector;

alter table public.kb_chunks
    add column if not exists embedding vector;

alter table public.kb_chunks
    add column if not exists embedding_model text null;

alter table public.kb_chunks
    add column if not exists embedding_updated_at timestamptz null;

alter table public.kb_documents
    add column if not exists embedding vector;

alter table public.kb_documents
    add column if not exists embedding_model text null;

alter table public.kb_documents
    add column if not exists embedding_updated_at timestamptz null;

create index if not exists kb_chunks_embedding_hnsw_1536_idx
    on public.kb_chunks
    using hnsw ((embedding::vector(1536)) vector_cosine_ops)
    where embedding is not null and vector_dims(embedding) = 1536;

create index if not exists kb_documents_embedding_hnsw_1536_idx
    on public.kb_documents
    using hnsw ((embedding::vector(1536)) vector_cosine_ops)
    where embedding is not null and vector_dims(embedding) = 1536;

create or replace function public.match_kb_chunks(
    query_embedding vector(1536),
    match_count integer default 6
)
returns table (
    chunk_id text,
    source_kind text,
    source_ref text,
    title text,
    url text,
    heading_path jsonb,
    page_type text,
    topic text,
    content text,
    short_summary text,
    publication_date text,
    updated_date text,
    metadata jsonb,
    similarity double precision
)
language sql
stable
as $$
    select
        c.chunk_id,
        c.source_kind,
        c.source_ref,
        c.title,
        c.url,
        c.heading_path,
        c.page_type,
        c.topic,
        c.content,
        c.short_summary,
        c.publication_date,
        c.updated_date,
        c.metadata,
        1 - (c.embedding::vector(1536) <=> query_embedding) as similarity
    from public.kb_chunks c
    where c.embedding is not null
      and vector_dims(c.embedding) = 1536
    order by c.embedding::vector(1536) <=> query_embedding
    limit greatest(1, least(coalesce(match_count, 6), 20));
$$;

grant execute on function public.match_kb_chunks(vector, integer) to service_role;
