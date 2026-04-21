create or replace function public.search_kb_chunks(
    p_query text,
    p_limit integer default 6
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
    rank double precision
)
language sql
stable
as $$
    with prepared as (
        select
            trim(lower(coalesce(p_query, ''))) as raw_query,
            websearch_to_tsquery('simple', trim(coalesce(p_query, ''))) as ts_query
    )
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
        (
            ts_rank_cd(c.search_vector, prepared.ts_query) * 2.2
            + similarity(c.normalized_text, prepared.raw_query) * 2.0
            + similarity(lower(c.title), prepared.raw_query) * 3.0
            + similarity(lower(c.topic), prepared.raw_query) * 2.2
            + case when prepared.raw_query <> '' and position(prepared.raw_query in lower(c.title)) > 0 then 6.0 else 0.0 end
            + case when prepared.raw_query <> '' and position(prepared.raw_query in lower(c.topic)) > 0 then 4.0 else 0.0 end
            + case when prepared.raw_query <> '' and position(prepared.raw_query in lower(c.short_summary)) > 0 then 3.0 else 0.0 end
            + case when prepared.raw_query <> '' and position(prepared.raw_query in lower(c.normalized_text)) > 0 then 2.5 else 0.0 end
        ) as rank
    from public.kb_chunks c
    cross join prepared
    where prepared.raw_query <> ''
      and (
        c.search_vector @@ prepared.ts_query
        or position(prepared.raw_query in lower(c.title)) > 0
        or position(prepared.raw_query in lower(c.topic)) > 0
        or position(prepared.raw_query in lower(c.short_summary)) > 0
        or position(prepared.raw_query in lower(c.normalized_text)) > 0
        or similarity(c.normalized_text, prepared.raw_query) > 0.08
        or similarity(lower(c.title), prepared.raw_query) > 0.08
        or similarity(lower(c.topic), prepared.raw_query) > 0.08
      )
    order by rank desc, coalesce(c.updated_at, c.created_at) desc
    limit greatest(1, least(coalesce(p_limit, 6), 20));
$$;
