revoke all on table public.app_users from anon, authenticated;
revoke all on table public.conversation_sessions from anon, authenticated;
revoke all on table public.conversation_messages from anon, authenticated;
revoke all on table public.feedback_records from anon, authenticated;
revoke all on table public.kb_pages from anon, authenticated;
revoke all on table public.kb_entities from anon, authenticated;
revoke all on table public.kb_aliases from anon, authenticated;
revoke all on table public.kb_relationships from anon, authenticated;
revoke all on table public.kb_name_timeline from anon, authenticated;
revoke all on table public.kb_faq from anon, authenticated;
revoke all on table public.kb_chunks from anon, authenticated;

grant all on table public.app_users to service_role;
grant all on table public.conversation_sessions to service_role;
grant all on table public.conversation_messages to service_role;
grant all on table public.feedback_records to service_role;
grant all on table public.kb_pages to service_role;
grant all on table public.kb_entities to service_role;
grant all on table public.kb_aliases to service_role;
grant all on table public.kb_relationships to service_role;
grant all on table public.kb_name_timeline to service_role;
grant all on table public.kb_faq to service_role;
grant all on table public.kb_chunks to service_role;

alter table public.app_users enable row level security;
alter table public.conversation_sessions enable row level security;
alter table public.conversation_messages enable row level security;
alter table public.feedback_records enable row level security;
alter table public.kb_pages enable row level security;
alter table public.kb_entities enable row level security;
alter table public.kb_aliases enable row level security;
alter table public.kb_relationships enable row level security;
alter table public.kb_name_timeline enable row level security;
alter table public.kb_faq enable row level security;
alter table public.kb_chunks enable row level security;

drop policy if exists service_role_app_users on public.app_users;
create policy service_role_app_users
on public.app_users
for all
to service_role
using (true)
with check (true);

drop policy if exists service_role_conversation_sessions on public.conversation_sessions;
create policy service_role_conversation_sessions
on public.conversation_sessions
for all
to service_role
using (true)
with check (true);

drop policy if exists service_role_conversation_messages on public.conversation_messages;
create policy service_role_conversation_messages
on public.conversation_messages
for all
to service_role
using (true)
with check (true);

drop policy if exists service_role_feedback_records on public.feedback_records;
create policy service_role_feedback_records
on public.feedback_records
for all
to service_role
using (true)
with check (true);

drop policy if exists service_role_kb_pages on public.kb_pages;
create policy service_role_kb_pages
on public.kb_pages
for all
to service_role
using (true)
with check (true);

drop policy if exists service_role_kb_entities on public.kb_entities;
create policy service_role_kb_entities
on public.kb_entities
for all
to service_role
using (true)
with check (true);

drop policy if exists service_role_kb_aliases on public.kb_aliases;
create policy service_role_kb_aliases
on public.kb_aliases
for all
to service_role
using (true)
with check (true);

drop policy if exists service_role_kb_relationships on public.kb_relationships;
create policy service_role_kb_relationships
on public.kb_relationships
for all
to service_role
using (true)
with check (true);

drop policy if exists service_role_kb_name_timeline on public.kb_name_timeline;
create policy service_role_kb_name_timeline
on public.kb_name_timeline
for all
to service_role
using (true)
with check (true);

drop policy if exists service_role_kb_faq on public.kb_faq;
create policy service_role_kb_faq
on public.kb_faq
for all
to service_role
using (true)
with check (true);

drop policy if exists service_role_kb_chunks on public.kb_chunks;
create policy service_role_kb_chunks
on public.kb_chunks
for all
to service_role
using (true)
with check (true);

create or replace view public.kb_runtime_stats
with (security_invoker = true) as
select
    count(*)::bigint as chunk_count,
    max(updated_at) as last_updated_at
from public.kb_chunks;

revoke all on public.kb_runtime_stats from anon, authenticated;
grant select on public.kb_runtime_stats to service_role;

revoke all on function public.search_kb_chunks(text, integer) from anon, authenticated;
grant execute on function public.search_kb_chunks(text, integer) to service_role;
