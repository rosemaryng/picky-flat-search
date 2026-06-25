-- Schema for the Supabase store backend (flatfinder/store.py: SupabaseStore).
-- Run in the Supabase SQL editor. All tables double as shared memory across agents.

create table if not exists briefs (
  id            text primary key,
  text          text,
  max_price     int,
  min_beds      int,
  areas         jsonb,
  must_have     jsonb,
  nice_to_have  jsonb,
  avoid         jsonb,
  commute_to    text,
  created_at    timestamptz default now()
);

create table if not exists listings (
  id        text primary key,
  source    text,
  url       text,
  price     int,
  beds      int,
  baths     int,
  address   text,
  postcode  text,
  summary   text,
  epc       text,
  sqm       int,
  data      jsonb,          -- full listing payload
  seen_at   timestamptz default now()
);

create table if not exists matches (
  id            text primary key,      -- "<brief_id>::<listing_id>"
  brief_id      text,
  listing_id    text,
  score         numeric,
  reasons       jsonb,
  enquiry_draft text,
  status        text default 'new',
  listing       jsonb,                 -- nested listing so consumers don't need a join
  created_at    timestamptz default now()
);

create table if not exists viewings (
  id          text primary key default gen_random_uuid()::text,
  listing_id  text,
  brief_id    text,
  slot        timestamptz,
  status      text
);

create table if not exists payments (
  id      text primary key,
  amount  numeric,
  status  text,
  raw     jsonb,
  ts      timestamptz default now()
);

-- Cross-agent coordination blackboard
create table if not exists agents (
  name    text primary key,
  status  text,
  ts      double precision,
  extra   jsonb
);

create table if not exists notes (
  key     text primary key,
  value   jsonb,
  ts      double precision
);
