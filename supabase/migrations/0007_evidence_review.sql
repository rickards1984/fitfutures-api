-- Phase 9b: assessor evidence review.
--
-- The evidence_items table already carries the review state columns
-- (supervisor_approved bool, supervisor_approved_at timestamptz, supervisor_id
-- = the reviewer). Staff review adds one thing: a free-text feedback note that
-- is shown back to the learner when changes are requested.
--
-- We also add an explicit staff UPDATE policy so a tutor/admin can record a
-- review. The API uses the service-role key (bypasses RLS), but per the working
-- agreement every table's policies must still reflect who is allowed to write —
-- mirroring the completion_reviews staff-decide policy.

alter table evidence_items
  add column if not exists review_feedback text;

-- Tutor/admin may update any evidence item's review state (approve / request
-- changes + feedback). Learners keep their existing own-placement update policy.
drop policy if exists evidence_review_staff on evidence_items;
create policy evidence_review_staff on evidence_items
  for update using (is_tutor_or_admin()) with check (is_tutor_or_admin());
