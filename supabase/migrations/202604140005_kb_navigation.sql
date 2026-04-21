create table if not exists public.kb_navigation (
    id text primary key,
    category text not null,
    title text not null,
    normalized_title text not null,
    aliases text[] not null default '{}',
    url text not null,
    description text null,
    keywords text[] not null default '{}',
    usage_rule text not null default 'explicit_or_uncertain',
    fallback_priority integer not null default 100,
    confidence_tags text[] not null default '{}',
    access_note text null,
    source text not null default 'official_reference',
    active boolean not null default true,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    unique (url)
);

create index if not exists kb_navigation_category_idx
    on public.kb_navigation (category, fallback_priority, active);

create index if not exists kb_navigation_normalized_title_idx
    on public.kb_navigation (normalized_title);

create index if not exists kb_navigation_aliases_gin_idx
    on public.kb_navigation using gin (aliases);

create index if not exists kb_navigation_keywords_gin_idx
    on public.kb_navigation using gin (keywords);
