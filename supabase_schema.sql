-- Supabase schema for flat-finder. Run in the Supabase SQL editor.

create table if not exists briefs (
  id           text primary key,
  text         text,
  max_price    int,
  min_beds     int default 0,
  areas        jsonb default '[]',
  must_have    jsonb default '[]',
  nice_to_have jsonb default '[]',
  avoid        jsonb default '[]',
  commute_to   text default '',
  contact_name text,
  contact_email text,
  contact_phone text,
  created_at   timestamptz default now()
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
  sqm       numeric,
  data      jsonb,
  seen_at   timestamptz default now()
);

create table if not exists matches (
  id            bigint generated always as identity primary key,
  brief_id      text references briefs(id),
  listing_id    text references listings(id),
  score         numeric,
  reasons       jsonb,
  enquiry_draft text,
  status        text default 'new',
  created_at    timestamptz default now(),
  unique (brief_id, listing_id)
);

create table if not exists viewings (
  id         bigint generated always as identity primary key,
  brief_id   text,
  listing_id text,
  slot       timestamptz,
  status     text default 'requested',
  created_at timestamptz default now()
);

create table if not exists payments (
  id         text primary key,
  amount     numeric,
  status     text,
  raw        jsonb,
  created_at timestamptz default now()
);
