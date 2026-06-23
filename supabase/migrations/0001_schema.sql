-- FitFutures schema — Phase 1
-- Run order: 0001_schema → 0002_rls → 0003_seed
-- RLS is enabled on every table in 0002.

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------
create type user_role as enum ('learner', 'tutor', 'supervisor', 'admin');
create type learner_route as enum ('route_a', 'route_b');
create type placement_status as enum ('active', 'referred', 'complete', 'withdrawn');
create type unit_status as enum ('not_started', 'in_progress', 'complete');
create type task_status as enum ('not_started', 'in_progress', 'complete', 'not_applicable');
create type rag_status as enum ('green', 'amber', 'red', 'no_entry');
create type pipeline_stage as enum ('lead','taster_booked','taster_completed','consult_booked','consult_completed','proposal_made','converted','lost','deferred');
create type campaign_type as enum ('new_member_recruitment','member_retention','ex_member_reactivation','pr_community_event','b2b_activity','other');
create type completion_decision as enum ('pending','pass','refer');

-- ---------------------------------------------------------------------------
-- Profiles
-- ---------------------------------------------------------------------------
create table profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  full_name text not null,
  email text not null,
  role user_role not null default 'learner',
  phone text,                      -- E.164 for WhatsApp nudges
  whatsapp_opt_in boolean default false,
  push_opt_in boolean default false,
  avatar_url text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- ---------------------------------------------------------------------------
-- Placements
-- ---------------------------------------------------------------------------
create table placements (
  id uuid primary key default gen_random_uuid(),
  learner_id uuid not null references profiles(id) on delete cascade,
  tutor_id uuid references profiles(id),
  supervisor_id uuid references profiles(id),
  facility_name text not null,
  route learner_route not null default 'route_a',
  status placement_status not null default 'active',
  start_date date not null,
  expected_end_date date,
  actual_end_date date,
  planned_weeks int not null default 18,   -- explicit, not derived
  -- FIXED WEEKLY targets (match the spreadsheet, not derived)
  wk_target_placement_hours numeric(4,1) not null default 6,
  wk_target_study_hours numeric(4,1) not null default 3,
  wk_target_member_conversations int not null default 10,
  wk_target_ex_member_contacts int not null default 10,
  wk_target_retention_saves int not null default 2,
  wk_target_campaign_touches int not null default 5,
  wk_target_tasters_booked int not null default 1,
  wk_target_consultations int not null default 1,
  wk_target_conversions int not null default 0,
  -- Cumulative placement targets (for the totals dashboard)
  total_target_placement_hours int not null default 102,
  total_target_study_hours int not null default 51,
  total_target_member_conversations int not null default 170,
  total_target_ex_member_contacts int not null default 170,
  total_target_retention_saves int not null default 34,
  total_target_campaign_touches int not null default 85,
  total_target_tasters_booked int not null default 17,
  total_target_consultations int not null default 17,
  total_target_conversions int not null default 0,
  notes text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- ---------------------------------------------------------------------------
-- Weekly KPI entries
-- ---------------------------------------------------------------------------
create table kpi_entries (
  id uuid primary key default gen_random_uuid(),
  placement_id uuid not null references placements(id) on delete cascade,
  week_number int not null check (week_number between 1 and 52),
  week_commencing date not null,
  actual_placement_hours numeric(4,1) default 0,
  actual_study_hours numeric(4,1) default 0,
  actual_member_conversations int default 0,
  actual_ex_member_contacts int default 0,
  actual_retention_saves int default 0,
  actual_campaign_touches int default 0,
  actual_tasters_booked int default 0,
  actual_consultations int default 0,
  actual_conversions int default 0,
  reflection text,
  key_issue text,
  supervisor_initials text,
  supervisor_signed_at timestamptz,
  overall_status rag_status default 'no_entry',
  ai_coach_message text,
  ai_coach_generated_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (placement_id, week_number)
);

-- ---------------------------------------------------------------------------
-- Units (seeded, 6 fixed) + tasks + per-learner progress
-- ---------------------------------------------------------------------------
create table units (
  id uuid primary key default gen_random_uuid(),
  unit_number int not null unique check (unit_number between 1 and 6),
  title text not null,
  aim text not null,
  is_mandatory boolean not null default true,
  suggested_hours_min int,
  suggested_hours_max int,
  route_applicability text not null default 'all'
);

create table unit_tasks (
  id uuid primary key default gen_random_uuid(),
  unit_id uuid not null references units(id) on delete cascade,
  task_order int not null,
  description text not null,
  is_mandatory boolean not null default true,
  requires_evidence boolean not null default true,
  requires_supervisor_sign boolean not null default false
);

create table learner_unit_progress (
  id uuid primary key default gen_random_uuid(),
  placement_id uuid not null references placements(id) on delete cascade,
  unit_id uuid not null references units(id) on delete cascade,
  status unit_status not null default 'not_started',
  started_at timestamptz, completed_at timestamptz,
  tutor_signed_at timestamptz, supervisor_signed_at timestamptz,
  notes text,
  unique (placement_id, unit_id)
);

create table learner_task_progress (
  id uuid primary key default gen_random_uuid(),
  placement_id uuid not null references placements(id) on delete cascade,
  unit_task_id uuid not null references unit_tasks(id) on delete cascade,
  status task_status not null default 'not_started',
  completed_at timestamptz,
  supervisor_initials text, supervisor_signed_at timestamptz,
  notes text,
  unique (placement_id, unit_task_id)
);

-- ---------------------------------------------------------------------------
-- Evidence
-- ---------------------------------------------------------------------------
create table evidence_items (
  id uuid primary key default gen_random_uuid(),
  placement_id uuid not null references placements(id) on delete cascade,
  unit_task_id uuid references unit_tasks(id),
  kpi_entry_id uuid references kpi_entries(id),
  title text not null, description text,
  file_url text not null, file_type text not null, file_size_bytes int,
  uploaded_by uuid not null references profiles(id),
  supervisor_approved boolean, supervisor_approved_at timestamptz,
  supervisor_id uuid references profiles(id),
  created_at timestamptz default now()
);

-- ---------------------------------------------------------------------------
-- Business start-up milestones (the "start your own business" outcome)
-- ---------------------------------------------------------------------------
create table business_milestones (
  id uuid primary key default gen_random_uuid(),
  placement_id uuid not null references placements(id) on delete cascade,
  milestone_key text not null,
  title text not null,
  status task_status not null default 'not_started',
  target_date date, completed_at timestamptz,
  evidence_notes text, blocking_issue text, next_action text,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (placement_id, milestone_key)
);

-- ---------------------------------------------------------------------------
-- Completion review (Pass / Refer + certificate trigger)
-- ---------------------------------------------------------------------------
create table completion_reviews (
  id uuid primary key default gen_random_uuid(),
  placement_id uuid not null unique references placements(id) on delete cascade,
  learner_final_reflection text,
  tutor_decision completion_decision not null default 'pending',
  tutor_feedback text,
  tutor_id uuid references profiles(id),
  decided_at timestamptz,
  certificate_triggered boolean default false,
  certificate_triggered_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- ---------------------------------------------------------------------------
-- Secondary data (Fast-Follow tables — schema now, UI in Phase 8)
-- ---------------------------------------------------------------------------
create table lead_contacts (
  id uuid primary key default gen_random_uuid(),
  placement_id uuid not null references placements(id) on delete cascade,
  contact_date date not null, name_or_id text, category text,
  contact_method text, reason text, need_or_barrier text, outcome text,
  follow_up_date date, next_action text, evidence_notes text,
  gdpr_permission_checked boolean default false,
  created_at timestamptz default now(), updated_at timestamptz default now()
);

create table campaigns (
  id uuid primary key default gen_random_uuid(),
  placement_id uuid not null references placements(id) on delete cascade,
  campaign_ref text not null, campaign_type campaign_type,
  aim text, audience text, offer_message text,
  start_date date, end_date date,
  touchpoints_planned int default 5, touchpoints_completed int default 0,
  leads_generated int default 0, bookings_made int default 0,
  members_retained_rejoined int default 0, result_status text, evidence_notes text,
  created_at timestamptz default now(), updated_at timestamptz default now()
);

create table pt_pipeline (
  id uuid primary key default gen_random_uuid(),
  placement_id uuid not null references placements(id) on delete cascade,
  date_added date not null,
  prospect_name text,           -- UI MUST nudge initials/ref only (GDPR)
  source text, goal_or_need text, route_permission text,
  stage pipeline_stage not null default 'lead',
  taster_date date, consultation_date date, decision text,
  package_or_offer text, value numeric(8,2), follow_up_date date,
  converted boolean default false, evidence_notes text,
  created_at timestamptz default now(), updated_at timestamptz default now()
);

create table study_milestones (
  id uuid primary key default gen_random_uuid(),
  placement_id uuid not null references placements(id) on delete cascade,
  milestone_key text not null, title text not null,
  required_for_route text not null default 'all',
  target_date date, status task_status not null default 'not_started',
  evidence_produced text, blocking_issue text, next_action text,
  tutor_initials text, tutor_signed_at timestamptz,
  created_at timestamptz default now(), updated_at timestamptz default now(),
  unique (placement_id, milestone_key)
);

-- ---------------------------------------------------------------------------
-- AI coach history
-- ---------------------------------------------------------------------------
create table coach_messages (
  id uuid primary key default gen_random_uuid(),
  placement_id uuid not null references placements(id) on delete cascade,
  role text not null check (role in ('user','assistant')),
  content text not null, context_snapshot jsonb,
  created_at timestamptz default now()
);

-- ---------------------------------------------------------------------------
-- Reminder log (avoid double-sends, audit trail)
-- ---------------------------------------------------------------------------
create table reminder_log (
  id uuid primary key default gen_random_uuid(),
  placement_id uuid not null references placements(id) on delete cascade,
  channel text not null check (channel in ('whatsapp','push')),
  reminder_type text not null,    -- 'weekly_checkin', 'kpi_behind', 'unit_stalled'
  sent_at timestamptz default now(),
  status text,                    -- 'sent','failed','skipped'
  detail text
);

-- Web push subscriptions (stored via /v1/push/subscribe)
create table push_subscriptions (
  id uuid primary key default gen_random_uuid(),
  profile_id uuid not null references profiles(id) on delete cascade,
  endpoint text not null,
  p256dh text not null,
  auth text not null,
  created_at timestamptz default now(),
  unique (profile_id, endpoint)
);
