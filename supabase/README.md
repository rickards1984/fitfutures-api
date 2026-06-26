# Supabase migrations

Run order (in the Supabase SQL editor, or via the Supabase CLI):

1. `migrations/0001_schema.sql` — enums + all tables
2. `migrations/0002_rls.sql` — enable RLS on every table + policies
3. `migrations/0003_seed.sql` — seed the 6 units + starter unit tasks
4. `migrations/0004_storage.sql` — create the private `evidence` bucket (Phase 6)

## Setup checklist (Phase 1)

- [ ] Create a **separate** Supabase project (isolated from Business Hero).
- [ ] Run the three migrations in order.
- [ ] Create the Storage bucket `evidence` — run `0004_storage.sql` (or create
      a **private** bucket named `evidence` in the dashboard).
- [ ] Copy the project URL + anon + service keys into `fitfutures-api/.env`
      and `fitfutures-web/.env`.

## Notes

- The API authenticates with the **service-role** key, which bypasses RLS.
  The policies in `0002` protect direct anon/auth-key access (defence in depth).
- `unit_tasks` content in `0003` is a **starter placeholder** — replace with the
  real UKFI assessment criteria before go-live.
