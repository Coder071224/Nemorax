create extension if not exists pg_trgm;

create table if not exists public.kb_pages (
    page_id text primary key,
    url text not null,
    canonical_url text null,
    title text not null,
    page_type text not null,
    freshness text not null,
    breadcrumb jsonb not null default '[]'::jsonb,
    headings jsonb not null default '[]'::jsonb,
    cleaned_main_body_text text not null default '',
    structured_tables jsonb not null default '[]'::jsonb,
    publication_date text null,
    updated_date text null,
    detected_language text not null default 'en',
    content_hash text not null,
    source_domain text not null default '',
    crawl_timestamp text null,
    extraction_confidence double precision not null default 0,
    source_links jsonb not null default '[]'::jsonb,
    duplicate_of text null,
    provenance jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now())
);

do $$
begin
    if exists (
        select 1
        from information_schema.tables
        where table_schema = 'public'
          and table_name = 'kb_pages'
    ) then
        if exists (
            select 1
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'kb_pages'
              and column_name = 'id'
        ) and not exists (
            select 1
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'kb_pages'
              and column_name = 'page_id'
        ) then
            alter table public.kb_pages rename column id to page_id;
        end if;

        if not exists (
            select 1
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'kb_pages'
              and column_name = 'page_id'
        ) then
            alter table public.kb_pages add column page_id text;
            update public.kb_pages
            set page_id = md5(coalesce(url, '') || ':' || ctid::text)
            where page_id is null;
        end if;
    end if;
end
$$;

create table if not exists public.kb_entities (
    entity_id text primary key,
    canonical_name text not null,
    entity_type text not null,
    description text null,
    source_urls jsonb not null default '[]'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

do $$
begin
    if exists (
        select 1
        from information_schema.tables
        where table_schema = 'public'
          and table_name = 'kb_entities'
    ) then
        if exists (
            select 1
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'kb_entities'
              and column_name = 'id'
        ) and not exists (
            select 1
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'kb_entities'
              and column_name = 'entity_id'
        ) then
            alter table public.kb_entities rename column id to entity_id;
        end if;

        if not exists (
            select 1
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'kb_entities'
              and column_name = 'entity_id'
        ) then
            alter table public.kb_entities add column entity_id text;
            update public.kb_entities
            set entity_id = md5(coalesce(canonical_name, '') || ':' || ctid::text)
            where entity_id is null;
        end if;

        if exists (
            select 1
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'kb_entities'
              and column_name = 'entity_id'
              and data_type <> 'text'
        ) then
            alter table public.kb_entities
                alter column entity_id type text using entity_id::text;
        end if;
    end if;
end
$$;

create table if not exists public.kb_aliases (
    alias_id bigint generated always as identity primary key,
    entity_id text null references public.kb_entities(entity_id) on delete cascade,
    canonical_name text not null,
    alias text not null,
    normalized_alias text not null,
    created_at timestamptz not null default timezone('utc', now()),
    unique (entity_id, normalized_alias)
);

create table if not exists public.kb_relationships (
    relationship_id text primary key,
    subject_entity_id text not null references public.kb_entities(entity_id) on delete cascade,
    predicate text not null,
    object_entity_id text null references public.kb_entities(entity_id) on delete set null,
    object_name text null,
    valid_from text null,
    valid_to text null,
    source_urls jsonb not null default '[]'::jsonb,
    confidence double precision not null default 0,
    notes text null,
    created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.kb_name_timeline (
    timeline_id text primary key,
    entity_id text not null references public.kb_entities(entity_id) on delete cascade,
    canonical_name text not null,
    aliases jsonb not null default '[]'::jsonb,
    valid_from text null,
    valid_to text null,
    status text not null,
    source_urls jsonb not null default '[]'::jsonb,
    source_authority text not null default '',
    confidence double precision not null default 0,
    notes text null,
    created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.kb_faq (
    faq_id text primary key,
    question text not null,
    answer text not null,
    category text null,
    campus text null,
    metadata jsonb not null default '{}'::jsonb,
    source_ref text null,
    created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.kb_chunks (
    chunk_id text primary key,
    source_kind text not null,
    source_ref text not null,
    page_id text null references public.kb_pages(page_id) on delete cascade,
    title text not null default '',
    url text not null default '',
    heading_path jsonb not null default '[]'::jsonb,
    page_type text not null default '',
    topic text not null default '',
    content text not null,
    normalized_text text not null default '',
    short_summary text not null default '',
    keywords jsonb not null default '[]'::jsonb,
    entity_ids jsonb not null default '[]'::jsonb,
    publication_date text null,
    updated_date text null,
    freshness text not null default 'evergreen',
    content_hash text not null,
    previous_chunk_id text null,
    next_chunk_id text null,
    parent_chunk_id text null,
    source_section_id text null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    search_vector tsvector generated always as (
        setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(topic, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(short_summary, '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(normalized_text, '')), 'C') ||
        setweight(to_tsvector('simple', coalesce(content, '')), 'D')
    ) stored
);

create index if not exists kb_entities_canonical_name_trgm_idx
    on public.kb_entities using gin (lower(canonical_name) gin_trgm_ops);

create index if not exists kb_aliases_normalized_alias_trgm_idx
    on public.kb_aliases using gin (normalized_alias gin_trgm_ops);

create index if not exists kb_chunks_search_vector_idx
    on public.kb_chunks using gin (search_vector);

create index if not exists kb_chunks_normalized_text_trgm_idx
    on public.kb_chunks using gin (normalized_text gin_trgm_ops);

create index if not exists kb_chunks_title_trgm_idx
    on public.kb_chunks using gin (lower(title) gin_trgm_ops);

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
            trim(coalesce(p_query, '')) as raw_query,
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
        greatest(
            ts_rank_cd(c.search_vector, prepared.ts_query) * 1.5,
            similarity(c.normalized_text, prepared.raw_query),
            similarity(lower(c.title), prepared.raw_query) * 2.0,
            similarity(lower(c.topic), prepared.raw_query) * 1.5
        ) as rank
    from public.kb_chunks c
    cross join prepared
    where prepared.raw_query <> ''
      and (
        c.search_vector @@ prepared.ts_query
        or similarity(c.normalized_text, prepared.raw_query) > 0.15
        or similarity(lower(c.title), prepared.raw_query) > 0.15
        or similarity(lower(c.topic), prepared.raw_query) > 0.15
      )
    order by rank desc, coalesce(c.updated_at, c.created_at) desc
    limit greatest(1, least(coalesce(p_limit, 6), 20));
$$;

create or replace view public.kb_runtime_stats as
select
    count(*)::bigint as chunk_count,
    max(updated_at) as last_updated_at
from public.kb_chunks;
