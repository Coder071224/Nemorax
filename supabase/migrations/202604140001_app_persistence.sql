create extension if not exists pgcrypto;

create table if not exists public.app_users (
    user_id uuid primary key,
    email text not null unique,
    display_name text null,
    password_hash text not null,
    salt text not null,
    recovery_answers jsonb not null default '{}'::jsonb,
    settings jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.conversation_sessions (
    session_id text primary key,
    user_id uuid not null references public.app_users(user_id) on delete cascade,
    title text not null default 'New Chat',
    message_count integer not null default 0,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists conversation_sessions_user_updated_idx
    on public.conversation_sessions (user_id, updated_at desc);

create table if not exists public.conversation_messages (
    message_id uuid primary key default gen_random_uuid(),
    session_id text not null references public.conversation_sessions(session_id) on delete cascade,
    user_id uuid not null references public.app_users(user_id) on delete cascade,
    sequence integer not null,
    role text not null check (role in ('user', 'assistant', 'system')),
    content text not null,
    timestamp timestamptz not null default timezone('utc', now()),
    created_at timestamptz not null default timezone('utc', now()),
    unique (session_id, sequence)
);

create index if not exists conversation_messages_session_sequence_idx
    on public.conversation_messages (session_id, sequence asc);

create table if not exists public.feedback_records (
    feedback_id uuid primary key,
    session_id text null references public.conversation_sessions(session_id) on delete set null,
    rating integer null check (rating between 1 and 5),
    comment text not null default '',
    category text null,
    user_id uuid null references public.app_users(user_id) on delete set null,
    saved_at timestamptz not null default timezone('utc', now())
);

create index if not exists feedback_records_user_saved_idx
    on public.feedback_records (user_id, saved_at desc);

create or replace function public.append_conversation_messages(
    p_session_id text,
    p_user_id uuid,
    p_user_text text default null,
    p_assistant_text text default null,
    p_fallback_title text default 'New Chat',
    p_message_timestamp timestamptz default timezone('utc', now())
)
returns void
language plpgsql
as $$
declare
    v_existing_title text;
    v_created_at timestamptz;
    v_next_sequence integer;
    v_trimmed_title text;
    v_message_increment integer := 0;
begin
    select title, created_at
    into v_existing_title, v_created_at
    from public.conversation_sessions
    where session_id = p_session_id
      and user_id = p_user_id;

    if v_existing_title is null then
        v_existing_title := coalesce(nullif(trim(p_fallback_title), ''), 'New Chat');
        v_created_at := p_message_timestamp;
        insert into public.conversation_sessions (
            session_id,
            user_id,
            title,
            message_count,
            created_at,
            updated_at
        )
        values (
            p_session_id,
            p_user_id,
            v_existing_title,
            0,
            v_created_at,
            p_message_timestamp
        )
        on conflict (session_id) do nothing;
    end if;

    select coalesce(max(sequence), 0)
    into v_next_sequence
    from public.conversation_messages
    where session_id = p_session_id;

    if coalesce(nullif(trim(p_user_text), ''), '') <> '' then
        insert into public.conversation_messages (
            session_id,
            user_id,
            sequence,
            role,
            content,
            timestamp
        )
        values (
            p_session_id,
            p_user_id,
            v_next_sequence + 1,
            'user',
            trim(p_user_text),
            p_message_timestamp
        );
        v_next_sequence := v_next_sequence + 1;
        v_message_increment := v_message_increment + 1;
    end if;

    if coalesce(nullif(trim(p_assistant_text), ''), '') <> '' then
        insert into public.conversation_messages (
            session_id,
            user_id,
            sequence,
            role,
            content,
            timestamp
        )
        values (
            p_session_id,
            p_user_id,
            v_next_sequence + 1,
            'assistant',
            trim(p_assistant_text),
            p_message_timestamp
        );
        v_next_sequence := v_next_sequence + 1;
        v_message_increment := v_message_increment + 1;
    end if;

    if coalesce(nullif(trim(p_user_text), ''), '') <> '' and v_existing_title = 'New Chat' then
        v_trimmed_title := replace(trim(p_user_text), E'\n', ' ');
        if char_length(v_trimmed_title) > 40 then
            v_trimmed_title := left(v_trimmed_title, 40) || '...';
        end if;
        v_existing_title := coalesce(nullif(v_trimmed_title, ''), 'New Chat');
    end if;

    update public.conversation_sessions
    set
        title = v_existing_title,
        message_count = (
            select count(*)
            from public.conversation_messages
            where session_id = p_session_id
        ),
        updated_at = p_message_timestamp
    where session_id = p_session_id
      and user_id = p_user_id;
end;
$$;
