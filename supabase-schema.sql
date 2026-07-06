-- World Cup 2026 predictor — backend schema
-- Run this once in your Supabase project's SQL editor (Database > SQL Editor > New query).
-- Free tier is enough for this.

create table if not exists players (
  id uuid primary key references auth.users(id) on delete cascade,
  name text default '',
  followed int[] default '{}',       -- array of team indices (0..31), matches TEAMS[] in the app
  bracket text default '',           -- the 31-char encoded bracket state (same format as the #hash link)
  cup_pick int,                      -- team index (0..31) the player thinks will win the whole tournament
  updated_at timestamptz default now()
);

-- if the table already existed from before this feature, add the column on its own
alter table players add column if not exists cup_pick int;

alter table players enable row level security;

-- anyone can read everyone's row — this is what powers a future mini-league / "who's following what" view
drop policy if exists "players are readable by anyone" on players;
create policy "players are readable by anyone"
  on players for select
  using (true);

-- a user can only insert/update/delete their OWN row (enforced via their anonymous auth id)
drop policy if exists "users manage their own row" on players;
create policy "users manage their own row"
  on players for all
  using (auth.uid() = id)
  with check (auth.uid() = id);

-- keep updated_at fresh on every write
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists players_set_updated_at on players;
create trigger players_set_updated_at
  before update on players
  for each row execute function set_updated_at();
