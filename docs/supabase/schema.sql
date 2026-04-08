begin;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.chat_threads (
  id uuid primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  title text not null default 'New chat',
  graph_data jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now()
);

create table if not exists public.chat_messages (
  id uuid primary key,
  thread_id uuid not null references public.chat_threads(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.request_events (
  id uuid primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  event_type text not null,
  created_at_epoch double precision not null
);

create table if not exists public.search_tool_requests (
  request_id uuid primary key,
  user_id uuid not null references public.profiles(id) on delete cascade,
  thread_id uuid not null references public.chat_threads(id) on delete cascade,
  requested boolean not null default false,
  created_at_epoch double precision not null,
  expires_at_epoch double precision not null
);

create table if not exists public.http_request_logs (
  id uuid primary key,
  user_id uuid,
  method text not null,
  path text not null,
  status_code integer not null,
  latency_ms integer not null,
  ip_address text,
  user_agent text,
  metadata_json text,
  created_at_epoch double precision not null
);

create table if not exists public.llm_telemetry (
  id uuid primary key,
  user_id uuid,
  thread_id uuid,
  operation text not null,
  provider text not null,
  model text not null,
  status text not null,
  duration_ms integer not null,
  output_chars integer not null,
  used_fallback boolean not null default false,
  error_type text,
  metadata_json text,
  created_at_epoch double precision not null
);

create index if not exists idx_chat_threads_user_last_seen
  on public.chat_threads(user_id, last_seen_at desc);

create index if not exists idx_chat_messages_thread_created
  on public.chat_messages(thread_id, created_at desc);

create index if not exists idx_request_events_user_type_created
  on public.request_events(user_id, event_type, created_at_epoch desc);

create index if not exists idx_search_tool_requests_user_thread
  on public.search_tool_requests(user_id, thread_id);

create index if not exists idx_http_request_logs_created
  on public.http_request_logs(created_at_epoch desc);

create index if not exists idx_http_request_logs_user_created
  on public.http_request_logs(user_id, created_at_epoch desc);

create index if not exists idx_llm_telemetry_created
  on public.llm_telemetry(created_at_epoch desc);

create index if not exists idx_llm_telemetry_user_created
  on public.llm_telemetry(user_id, created_at_epoch desc);

alter table public.profiles enable row level security;
alter table public.chat_threads enable row level security;
alter table public.chat_messages enable row level security;
alter table public.request_events enable row level security;
alter table public.search_tool_requests enable row level security;
alter table public.http_request_logs enable row level security;
alter table public.llm_telemetry enable row level security;

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own" on public.profiles
for select using (auth.uid() = id);

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own" on public.profiles
for update using (auth.uid() = id);

drop policy if exists "threads_all_own" on public.chat_threads;
create policy "threads_all_own" on public.chat_threads
for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists "messages_all_own" on public.chat_messages;
create policy "messages_all_own" on public.chat_messages
for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

commit;
