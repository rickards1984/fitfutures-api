-- FitFutures RLS — Phase 1
-- Enable RLS on every table and apply the learner / tutor-admin / supervisor
-- policy pattern from the brief (§9).

-- ---------------------------------------------------------------------------
-- Helper functions (security definer)
-- ---------------------------------------------------------------------------
create or replace function is_own_placement(p uuid) returns boolean
language sql security definer as $$
  select exists (select 1 from placements where id = p and learner_id = auth.uid());
$$;

create or replace function is_tutor_or_admin() returns boolean
language sql security definer as $$
  select exists (select 1 from profiles where id = auth.uid() and role in ('tutor','admin'));
$$;

create or replace function is_supervisor_for_placement(p uuid) returns boolean
language sql security definer as $$
  select exists (select 1 from placements where id = p and supervisor_id = auth.uid());
$$;

-- ---------------------------------------------------------------------------
-- Enable RLS on every table
-- ---------------------------------------------------------------------------
alter table profiles               enable row level security;
alter table placements             enable row level security;
alter table kpi_entries            enable row level security;
alter table units                  enable row level security;
alter table unit_tasks             enable row level security;
alter table learner_unit_progress  enable row level security;
alter table learner_task_progress  enable row level security;
alter table evidence_items         enable row level security;
alter table business_milestones    enable row level security;
alter table completion_reviews     enable row level security;
alter table lead_contacts          enable row level security;
alter table campaigns              enable row level security;
alter table pt_pipeline            enable row level security;
alter table study_milestones       enable row level security;
alter table coach_messages         enable row level security;
alter table reminder_log           enable row level security;
alter table push_subscriptions     enable row level security;

-- ---------------------------------------------------------------------------
-- profiles: own row read/update; tutor/admin read all
-- ---------------------------------------------------------------------------
create policy profiles_select_own on profiles
  for select using (id = auth.uid() or is_tutor_or_admin());
create policy profiles_insert_own on profiles
  for insert with check (id = auth.uid());
create policy profiles_update_own on profiles
  for update using (id = auth.uid()) with check (id = auth.uid());

-- ---------------------------------------------------------------------------
-- Reference data: any authenticated user may read; tutor/admin may write
-- ---------------------------------------------------------------------------
create policy units_select on units
  for select using (auth.role() = 'authenticated');
create policy units_write on units
  for all using (is_tutor_or_admin()) with check (is_tutor_or_admin());

create policy unit_tasks_select on unit_tasks
  for select using (auth.role() = 'authenticated');
create policy unit_tasks_write on unit_tasks
  for all using (is_tutor_or_admin()) with check (is_tutor_or_admin());

-- ---------------------------------------------------------------------------
-- placements: learner reads own; tutor/admin read+write all; supervisor reads assigned
-- ---------------------------------------------------------------------------
create policy placements_select on placements
  for select using (
    learner_id = auth.uid()
    or is_tutor_or_admin()
    or supervisor_id = auth.uid()
  );
create policy placements_write_staff on placements
  for all using (is_tutor_or_admin()) with check (is_tutor_or_admin());

-- ---------------------------------------------------------------------------
-- Placement-scoped tables: learner own (rw), tutor/admin all (r), supervisor assigned (r)
-- Applied uniformly to every table carrying placement_id.
-- ---------------------------------------------------------------------------

-- kpi_entries
create policy kpi_select on kpi_entries for select using (
  is_own_placement(placement_id) or is_tutor_or_admin() or is_supervisor_for_placement(placement_id));
create policy kpi_insert on kpi_entries for insert with check (is_own_placement(placement_id));
create policy kpi_update on kpi_entries for update using (is_own_placement(placement_id)) with check (is_own_placement(placement_id));

-- learner_unit_progress
create policy lup_select on learner_unit_progress for select using (
  is_own_placement(placement_id) or is_tutor_or_admin() or is_supervisor_for_placement(placement_id));
create policy lup_insert on learner_unit_progress for insert with check (is_own_placement(placement_id));
create policy lup_update on learner_unit_progress for update using (is_own_placement(placement_id)) with check (is_own_placement(placement_id));

-- learner_task_progress
create policy ltp_select on learner_task_progress for select using (
  is_own_placement(placement_id) or is_tutor_or_admin() or is_supervisor_for_placement(placement_id));
create policy ltp_insert on learner_task_progress for insert with check (is_own_placement(placement_id));
create policy ltp_update on learner_task_progress for update using (is_own_placement(placement_id)) with check (is_own_placement(placement_id));

-- evidence_items
create policy evidence_select on evidence_items for select using (
  is_own_placement(placement_id) or is_tutor_or_admin() or is_supervisor_for_placement(placement_id));
create policy evidence_insert on evidence_items for insert with check (is_own_placement(placement_id));
create policy evidence_update on evidence_items for update using (is_own_placement(placement_id)) with check (is_own_placement(placement_id));

-- business_milestones
create policy biz_select on business_milestones for select using (
  is_own_placement(placement_id) or is_tutor_or_admin() or is_supervisor_for_placement(placement_id));
create policy biz_insert on business_milestones for insert with check (is_own_placement(placement_id));
create policy biz_update on business_milestones for update using (is_own_placement(placement_id)) with check (is_own_placement(placement_id));

-- completion_reviews: learner reads + writes own reflection; tutor/admin own the decision
create policy completion_select on completion_reviews for select using (
  is_own_placement(placement_id) or is_tutor_or_admin() or is_supervisor_for_placement(placement_id));
create policy completion_insert on completion_reviews for insert with check (is_own_placement(placement_id));
create policy completion_update_learner on completion_reviews for update using (is_own_placement(placement_id)) with check (is_own_placement(placement_id));
create policy completion_decide_staff on completion_reviews for update using (is_tutor_or_admin()) with check (is_tutor_or_admin());

-- lead_contacts
create policy leads_select on lead_contacts for select using (
  is_own_placement(placement_id) or is_tutor_or_admin() or is_supervisor_for_placement(placement_id));
create policy leads_insert on lead_contacts for insert with check (is_own_placement(placement_id));
create policy leads_update on lead_contacts for update using (is_own_placement(placement_id)) with check (is_own_placement(placement_id));

-- campaigns
create policy campaigns_select on campaigns for select using (
  is_own_placement(placement_id) or is_tutor_or_admin() or is_supervisor_for_placement(placement_id));
create policy campaigns_insert on campaigns for insert with check (is_own_placement(placement_id));
create policy campaigns_update on campaigns for update using (is_own_placement(placement_id)) with check (is_own_placement(placement_id));

-- pt_pipeline
create policy pipeline_select on pt_pipeline for select using (
  is_own_placement(placement_id) or is_tutor_or_admin() or is_supervisor_for_placement(placement_id));
create policy pipeline_insert on pt_pipeline for insert with check (is_own_placement(placement_id));
create policy pipeline_update on pt_pipeline for update using (is_own_placement(placement_id)) with check (is_own_placement(placement_id));

-- study_milestones
create policy study_select on study_milestones for select using (
  is_own_placement(placement_id) or is_tutor_or_admin() or is_supervisor_for_placement(placement_id));
create policy study_insert on study_milestones for insert with check (is_own_placement(placement_id));
create policy study_update on study_milestones for update using (is_own_placement(placement_id)) with check (is_own_placement(placement_id));

-- coach_messages
create policy coach_select on coach_messages for select using (
  is_own_placement(placement_id) or is_tutor_or_admin());
create policy coach_insert on coach_messages for insert with check (is_own_placement(placement_id));

-- reminder_log: read-only to learner/staff; writes happen via service role
create policy reminder_select on reminder_log for select using (
  is_own_placement(placement_id) or is_tutor_or_admin());

-- push_subscriptions: own rows only
create policy push_select on push_subscriptions for select using (profile_id = auth.uid());
create policy push_insert on push_subscriptions for insert with check (profile_id = auth.uid());
create policy push_delete on push_subscriptions for delete using (profile_id = auth.uid());

-- NOTE: the API uses the service-role key, which bypasses RLS. These policies
-- protect any direct (anon/auth-key) access and enforce least privilege.
