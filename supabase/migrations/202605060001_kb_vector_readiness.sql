create extension if not exists vector;

alter table public.kb_chunks
    add column if not exists embedding vector;

alter table public.kb_chunks
    add column if not exists embedding_model text null;

alter table public.kb_chunks
    add column if not exists embedding_updated_at timestamptz null;

create or replace view public.kb_vector_readiness as
select
    count(*)::bigint as chunk_count,
    count(*) filter (where embedding is not null)::bigint as embedded_chunk_count,
    coalesce(
        jsonb_agg(distinct vector_dims(embedding)) filter (where embedding is not null),
        '[]'::jsonb
    ) as embedding_dimensions,
    coalesce(
        jsonb_agg(distinct embedding_model) filter (where embedding_model is not null and embedding_model <> ''),
        '[]'::jsonb
    ) as embedding_models,
    to_regprocedure('public.match_kb_chunks(vector, integer)') is not null as vector_search_function_available
from public.kb_chunks;

grant select on public.kb_vector_readiness to service_role;
