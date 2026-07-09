-- Phase 7B-ii: manager email briefings (Resend).
--
-- The reminder_log table is reused to dedupe email briefings, but two of its
-- constraints need relaxing for the new send types:
--   1. `channel` gains 'email' alongside the existing 'whatsapp'/'push'.
--   2. `placement_id` becomes nullable — the weekly cohort digest is one email
--      covering every active placement, so it is logged once with a null
--      placement_id (the per-placement red-RAG alert still sets it).
-- A nullable `week_number` is added so red-RAG alerts dedupe cleanly per week.

alter table reminder_log
  drop constraint if exists reminder_log_channel_check;

alter table reminder_log
  add constraint reminder_log_channel_check
  check (channel in ('whatsapp', 'push', 'email'));

alter table reminder_log
  alter column placement_id drop not null;

alter table reminder_log
  add column if not exists week_number int;

-- No RLS change: reminder_log is written only by the service-role client from
-- the internal cron endpoint; it is never exposed to end users.
