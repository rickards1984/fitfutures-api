-- FitFutures storage — Phase 6
-- Create the private `evidence` bucket used for learner evidence uploads.
-- The API (service-role key) mints signed upload + download URLs, so no
-- additional storage RLS policies are required for the app flow; keeping the
-- bucket private means objects are only reachable via those signed URLs.

insert into storage.buckets (id, name, public)
values ('evidence', 'evidence', false)
on conflict (id) do nothing;
