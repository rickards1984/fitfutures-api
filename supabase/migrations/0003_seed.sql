-- FitFutures seed — Phase 1
-- Global reference data only: the 6 fixed units and their task checklists.
-- (Business + study milestones are seeded PER PLACEMENT on enrolment in Phase 3.)

-- ---------------------------------------------------------------------------
-- Units (verbatim from the brief)
-- ---------------------------------------------------------------------------
insert into units (unit_number, title, aim, is_mandatory, suggested_hours_min, suggested_hours_max, route_applicability) values
(1,'Gym Duties and Professional Facility Practice','Develop reliable, safe and commercially aware day-to-day gym practice through supervised placement duties.',true,12,20,'all'),
(2,'Shadowing Personal Training and Specialist Practice','Build understanding of PT session delivery, specialist practice and client management through supervised observation and support.',true,8,15,'all'),
(3,'Social Media and Member Communication Practice','Plan and deliver approved member communication and social media activity to support the facility and develop commercial skills.',true,6,12,'all'),
(4,'PR, Community or Facility Event Project','Plan, obtain approval for, and deliver a community engagement or facility event that supports recruitment or retention.',true,6,12,'all'),
(5,'Consultation, Sales Tracking and Professional Progression','Develop systematic member engagement, consultation practice and conversion skills through structured tracking and reflection.',true,10,18,'all'),
(6,'New Member Induction and Bespoke Programme Practice','Deliver or support supervised new member inductions and basic programme design where the facility permits.',false,6,12,'all')
on conflict (unit_number) do nothing;

-- ---------------------------------------------------------------------------
-- Unit tasks (STARTER set — placeholder checklist items)
-- NOTE: the brief does not specify task-level checklist content. These are
-- reasonable starters so the Phase 5 checklist is not empty; replace with the
-- real UKFI assessment criteria before go-live.
-- ---------------------------------------------------------------------------
insert into unit_tasks (unit_id, task_order, description, is_mandatory, requires_evidence, requires_supervisor_sign)
select u.id, t.task_order, t.description, t.is_mandatory, t.requires_evidence, t.requires_supervisor_sign
from units u
join (values
  -- Unit 1
  (1, 1, 'Complete facility health & safety induction', true, true, true),
  (1, 2, 'Demonstrate safe opening/closing and floor walk routine', true, true, true),
  (1, 3, 'Log a typical week of supervised gym duties', true, true, false),
  -- Unit 2
  (2, 1, 'Shadow and reflect on 3 PT sessions', true, true, false),
  (2, 2, 'Observe a specialist practice session and write up learning', true, true, false),
  -- Unit 3
  (3, 1, 'Draft an approved member communication / social post', true, true, true),
  (3, 2, 'Deliver the approved communication and record reach/response', true, true, false),
  -- Unit 4
  (4, 1, 'Plan a community or facility event and obtain sign-off', true, true, true),
  (4, 2, 'Deliver the event and capture outcome evidence', true, true, true),
  -- Unit 5
  (5, 1, 'Run a structured member consultation', true, true, false),
  (5, 2, 'Maintain a sales/conversion tracker for the placement', true, true, false),
  (5, 3, 'Reflect on conversion results and next actions', true, true, false),
  -- Unit 6
  (6, 1, 'Support or deliver a supervised new member induction', false, true, true),
  (6, 2, 'Draft a basic bespoke programme where permitted', false, true, false)
) as t(unit_number, task_order, description, is_mandatory, requires_evidence, requires_supervisor_sign)
  on t.unit_number = u.unit_number;
