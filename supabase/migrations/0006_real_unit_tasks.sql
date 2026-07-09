-- Phase 7 data correction: replace the Phase 1 placeholder unit content with
-- the real UKFI FitFutures unit content, taken verbatim from
-- "FitFutures_STP_Learner_Evidence_Portfolio_and_Resources.docx".
--
--   1. Update all 6 units (aim, suggested hours, mandatory status) from the
--      document's Status / Aim / Suggested time table. The Phase 1 seed used
--      values from the build brief; several were wrong. Unit 6 is optional
--      ("Optional - facility dependent" in the source).
--   2. Delete learner_task_progress rows tied to the placeholder tasks so
--      nothing is orphaned, then delete all placeholder unit_tasks.
--   3. Insert the 27 real tasks (the units' "What you need to do" bullets),
--      matched to each unit by unit_number. requires_evidence /
--      requires_supervisor_sign are derived from each unit's Evidence
--      checklist; supervisor sign-off sits on the evaluation/reflection task.
--
-- All task descriptions and unit aims are the document's wording, unchanged.

begin;

-- ---------------------------------------------------------------------------
-- 1. Units: aim / suggested hours / mandatory status (verbatim from document)
-- ---------------------------------------------------------------------------
update units set
  aim = 'Develop reliable, safe and commercially aware day-to-day gym practice through supervised placement duties.',
  suggested_hours_min = 12, suggested_hours_max = 20,
  is_mandatory = true
where unit_number = 1;

update units set
  aim = 'Develop practical insight by observing competent practitioners and reflecting on professional practice.',
  suggested_hours_min = 8, suggested_hours_max = 12,
  is_mandatory = true
where unit_number = 2;

update units set
  aim = 'Build practical marketing and communication skills that support retention, recruitment and reactivation.',
  suggested_hours_min = 6, suggested_hours_max = 10,
  is_mandatory = true
where unit_number = 3;

update units set
  aim = 'Develop project planning, community engagement and promotional skills by organising and delivering a facility-approved event.',
  suggested_hours_min = 8, suggested_hours_max = 15,
  is_mandatory = true
where unit_number = 4;

update units set
  aim = 'Develop confidence in the professional consultation journey, sales tracking and readiness for qualified PT practice.',
  suggested_hours_min = 3, suggested_hours_max = 6,
  is_mandatory = true
where unit_number = 5;

update units set
  aim = 'Support learners to understand and practise high-quality new member induction and basic programme design where this is part of the host facility process.',
  suggested_hours_min = 4, suggested_hours_max = 8,
  is_mandatory = false
where unit_number = 6;

-- ---------------------------------------------------------------------------
-- 2. Clear placeholder tasks. Two tables reference unit_tasks(id):
--      * learner_task_progress — ON DELETE CASCADE, but we clear it explicitly.
--      * evidence_items        — no cascade, so deleting a task it points at
--        would fail (evidence_items_unit_task_id_fkey). The column is nullable,
--        so we detach the evidence from the placeholder task and KEEP the
--        evidence record itself. Both run before the delete, in one transaction.
-- ---------------------------------------------------------------------------
delete from learner_task_progress
where unit_task_id in (select id from unit_tasks);

update evidence_items set unit_task_id = null
where unit_task_id in (select id from unit_tasks);

delete from unit_tasks;

-- ---------------------------------------------------------------------------
-- 3. Insert the 27 real tasks, matched to units by unit_number
--    columns: unit_id, task_order, description, is_mandatory,
--             requires_evidence, requires_supervisor_sign
-- ---------------------------------------------------------------------------

-- Unit 1: Gym Duties and Professional Facility Practice
insert into unit_tasks (unit_id, task_order, description, is_mandatory, requires_evidence, requires_supervisor_sign) values
  ((select id from units where unit_number = 1), 1, 'Carry out typical gym duties in line with facility procedures, health and safety requirements and professional standards.', true, true, true),
  ((select id from units where unit_number = 1), 2, 'Complete and evidence cleaning, equipment checks, basic reporting and permitted minor actions within competence.', true, true, false),
  ((select id from units where unit_number = 1), 3, 'Demonstrate professional customer interaction, member support, membership sales support and PT package sales support.', true, true, false),
  ((select id from units where unit_number = 1), 4, 'Support new member sign-up and approved ex-member reactivation activity in line with data protection and facility procedures.', true, true, false),
  ((select id from units where unit_number = 1), 5, 'Complete the induction/initial training checklist and maintain suitable evidence using facility records or UKFI proformas.', true, true, false);

-- Unit 2: Shadowing Personal Training and Specialist Practice
insert into unit_tasks (unit_id, task_order, description, is_mandatory, requires_evidence, requires_supervisor_sign) values
  ((select id from units where unit_number = 2), 1, 'Shadow at least four personal training sessions delivered by a suitably qualified practitioner.', true, true, true),
  ((select id from units where unit_number = 2), 2, 'Shadow at least one additional relevant specialist session, such as physiotherapy, sports therapy, strength and conditioning or specialist training.', true, true, true),
  ((select id from units where unit_number = 2), 3, 'Record key observations about session structure, communication, coaching, safety, adaptations and professionalism.', true, true, false),
  ((select id from units where unit_number = 2), 4, 'Reflect on how shadowing informs the learner’s own future practice, within qualification and competence boundaries.', true, true, false);

-- Unit 3: Social Media and Member Communication Practice
insert into unit_tasks (unit_id, task_order, description, is_mandatory, requires_evidence, requires_supervisor_sign) values
  ((select id from units where unit_number = 3), 1, 'Plan, create and evidence three facility-approved social media or member communication campaigns.', true, true, false),
  ((select id from units where unit_number = 3), 2, 'Produce one campaign aimed at member retention.', true, true, false),
  ((select id from units where unit_number = 3), 3, 'Produce one campaign aimed at new member recruitment.', true, true, false),
  ((select id from units where unit_number = 3), 4, 'Produce one campaign aimed at re-engaging ex-members.', true, true, false),
  ((select id from units where unit_number = 3), 5, 'Evaluate campaign quality, approval process, results and learning points.', true, true, true);

-- Unit 4: PR, Community or Facility Event Project
insert into unit_tasks (unit_id, task_order, description, is_mandatory, requires_evidence, requires_supervisor_sign) values
  ((select id from units where unit_number = 4), 1, 'Propose a suitable PR, charitable, community, B2B, retention or facility event.', true, true, false),
  ((select id from units where unit_number = 4), 2, 'Gain facility sign-off before promotion or delivery.', true, true, true),
  ((select id from units where unit_number = 4), 3, 'Plan the event, including aims, audience, roles, resources, health and safety considerations and promotional activity.', true, true, false),
  ((select id from units where unit_number = 4), 4, 'Deliver or support delivery of the event professionally.', true, true, false),
  ((select id from units where unit_number = 4), 5, 'Evaluate outcomes, evidence gathered, learner contribution and improvement points.', true, true, true);

-- Unit 5: Consultation, Sales Tracking and Professional Progression
-- Tasks 2 and 3 are an explicit either/or (see the "OR ... where not eligible"
-- Evidence checklist row), so both are non-mandatory.
insert into unit_tasks (unit_id, task_order, description, is_mandatory, requires_evidence, requires_supervisor_sign) values
  ((select id from units where unit_number = 5), 1, 'Use the progress tracking spreadsheet or UKFI tracker to evidence sales, enquiries and consultation activity.', true, true, false),
  ((select id from units where unit_number = 5), 2, 'Where qualified or nearly qualified at PT level, confirm booking of at least three taster session consultations.', false, true, false),
  ((select id from units where unit_number = 5), 3, 'Where not ready to book consultations independently, attend consultation training and/or sit in on a suitable consultation.', false, true, false),
  ((select id from units where unit_number = 5), 4, 'Reflect on the consultation process, ethical sales, client needs and professional boundaries.', true, true, true);

-- Unit 6: New Member Induction and Bespoke Programme Practice
insert into unit_tasks (unit_id, task_order, description, is_mandatory, requires_evidence, requires_supervisor_sign) values
  ((select id from units where unit_number = 6), 1, 'Attend induction training for delivering a professional new member induction using the UKFI approach.', true, true, true),
  ((select id from units where unit_number = 6), 2, 'Observe or support the delivery of a new member induction and bespoke programme process.', true, true, false),
  ((select id from units where unit_number = 6), 3, 'Demonstrate understanding of safe onboarding, goal gathering, exercise selection and signposting.', true, true, false),
  ((select id from units where unit_number = 6), 4, 'Reflect on what makes an induction effective, safe, personal and commercially useful.', true, true, true);

commit;
