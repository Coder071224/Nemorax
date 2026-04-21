create table if not exists public.kb_sources (
    id text primary key,
    source_type text not null,
    source_name text not null,
    base_url text not null,
    trust_tier smallint not null check (trust_tier between 1 and 5),
    category text not null default '',
    active boolean not null default true,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    unique (base_url)
);

create table if not exists public.kb_documents (
    id text primary key,
    source_id text null references public.kb_sources(id) on delete set null,
    canonical_url text not null,
    title text not null default '',
    document_type text not null default '',
    campus text null,
    office text null,
    published_at timestamptz null,
    scraped_at timestamptz not null default timezone('utc', now()),
    raw_text text not null default '',
    cleaned_text text not null default '',
    content_hash text not null default '',
    metadata jsonb not null default '{}'::jsonb,
    public_visibility text not null default 'public',
    last_seen_at timestamptz not null default timezone('utc', now()),
    unique (canonical_url)
);

alter table public.kb_chunks
    add column if not exists document_id text null references public.kb_documents(id) on delete cascade;

alter table public.kb_chunks
    add column if not exists chunk_index integer null;

alter table public.kb_chunks
    add column if not exists token_estimate integer not null default 0;

alter table public.kb_entities
    add column if not exists campus text null;

alter table public.kb_entities
    add column if not exists title text null;

alter table public.kb_entities
    add column if not exists content text null;

create table if not exists public.kb_campuses (
    id text primary key,
    campus_name text not null,
    normalized_name text not null,
    short_name text null,
    location text null,
    description text null,
    source_url text not null default '',
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    unique (normalized_name)
);

create table if not exists public.kb_colleges (
    id text primary key,
    college_name text not null,
    normalized_name text not null,
    abbreviation text null,
    campus text null,
    description text null,
    source_url text not null default '',
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.kb_programs (
    id text primary key,
    campus text null,
    college text null,
    program_name text not null,
    normalized_program_name text not null,
    degree_level text null,
    accreditation text null,
    source_url text not null default '',
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.kb_scholarships (
    id text primary key,
    scholarship_name text not null,
    normalized_scholarship_name text not null,
    provider text not null default '',
    provider_type text not null default '',
    applies_to_nemsu_students boolean not null default true,
    eligibility_text text null,
    benefits_text text null,
    application_url text null,
    source_url text not null default '',
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.kb_contacts (
    id text primary key,
    name text not null,
    title text null,
    office text null,
    campus text null,
    phone text null,
    email text null,
    source_url text not null default '',
    metadata jsonb not null default '{}'::jsonb,
    last_seen_at timestamptz not null default timezone('utc', now()),
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.kb_offices (
    id text primary key,
    office_name text not null,
    normalized_office_name text not null,
    campus text null,
    description text null,
    contact_email text null,
    contact_phone text null,
    source_url text not null default '',
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.kb_news (
    id text primary key,
    title text not null,
    normalized_title text not null,
    summary text null,
    body text null,
    campus text null,
    category text null,
    published_at timestamptz null,
    source_id text null references public.kb_sources(id) on delete set null,
    source_url text not null default '',
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists kb_documents_source_id_idx
    on public.kb_documents (source_id, scraped_at desc);

create index if not exists kb_documents_document_type_idx
    on public.kb_documents (document_type, published_at desc);

create index if not exists kb_documents_campus_idx
    on public.kb_documents (campus, published_at desc);

create index if not exists kb_chunks_document_id_idx
    on public.kb_chunks (document_id, chunk_index);

create unique index if not exists kb_chunks_document_index_uidx
    on public.kb_chunks (document_id, chunk_index)
    where document_id is not null and chunk_index is not null;

create index if not exists kb_campuses_normalized_name_idx
    on public.kb_campuses (normalized_name);

create index if not exists kb_colleges_normalized_name_idx
    on public.kb_colleges (normalized_name, campus);

create unique index if not exists kb_colleges_lookup_uidx
    on public.kb_colleges (normalized_name, coalesce(campus, ''));

create index if not exists kb_programs_program_lookup_idx
    on public.kb_programs (normalized_program_name, campus, college);

create unique index if not exists kb_programs_lookup_uidx
    on public.kb_programs (normalized_program_name, coalesce(campus, ''), coalesce(college, ''), source_url);

create index if not exists kb_scholarships_provider_idx
    on public.kb_scholarships (provider, normalized_scholarship_name);

create unique index if not exists kb_scholarships_lookup_uidx
    on public.kb_scholarships (normalized_scholarship_name, provider, coalesce(application_url, ''), source_url);

create index if not exists kb_contacts_office_idx
    on public.kb_contacts (office, campus);

create unique index if not exists kb_contacts_lookup_uidx
    on public.kb_contacts (name, coalesce(title, ''), coalesce(office, ''), coalesce(campus, ''), source_url);

create index if not exists kb_news_published_idx
    on public.kb_news (published_at desc, category);

create unique index if not exists kb_offices_lookup_uidx
    on public.kb_offices (normalized_office_name, coalesce(campus, ''), source_url);

create unique index if not exists kb_news_lookup_uidx
    on public.kb_news (normalized_title, coalesce(source_url, ''));
