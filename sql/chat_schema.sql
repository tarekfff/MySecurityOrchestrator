-- Run this in your Supabase SQL Editor to enable chat persistence.

-- 1. Chat sessions (one per conversation)
create table if not exists chat_sessions (
    id               uuid primary key default gen_random_uuid(),
    user_id          text,                              -- profile id or anonymous token
    title            text not null default 'New chat',  -- auto-set from first message
    suspected_attack text,                              -- e.g. "xss", "sql_injection"
    task_context     text,                              -- raw incident/log pasted in
    user_role        text,                              -- e.g. "SOC analyst"
    message_count    int  not null default 0,
    created_at       timestamptz default now(),
    updated_at       timestamptz default now()
);

-- 2. Individual messages
create table if not exists chat_messages (
    id         uuid primary key default gen_random_uuid(),
    session_id uuid not null references chat_sessions(id) on delete cascade,
    role       text not null check (role in ('user', 'assistant')),
    content    text not null,
    created_at timestamptz default now()
);

-- 3. Indexes
create index if not exists chat_sessions_user_idx    on chat_sessions(user_id);
create index if not exists chat_sessions_updated_idx on chat_sessions(updated_at desc);
create index if not exists chat_messages_session_idx on chat_messages(session_id, created_at asc);

-- 4. Auto-update updated_at on chat_sessions
create or replace function touch_chat_session()
returns trigger language plpgsql as $$
begin
    update chat_sessions
       set updated_at    = now(),
           message_count = message_count + 1
     where id = NEW.session_id;
    return NEW;
end;
$$;

drop trigger if exists chat_message_inserted on chat_messages;
create trigger chat_message_inserted
after insert on chat_messages
for each row execute function touch_chat_session();

-- 5. Convenience view: sessions with last-message preview
create or replace view chat_sessions_preview as
select
    s.id,
    s.user_id,
    s.title,
    s.suspected_attack,
    s.user_role,
    s.message_count,
    s.created_at,
    s.updated_at,
    m.content  as last_message,
    m.role     as last_role
from chat_sessions s
left join lateral (
    select content, role
    from chat_messages
    where session_id = s.id
    order by created_at desc
    limit 1
) m on true;
