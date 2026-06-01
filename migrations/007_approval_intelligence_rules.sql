-- ============================================================
-- Migration 007 — Approval Intelligence Rule System
-- ============================================================
-- Adds two new columns to engineering_review_rules:
--   check_logic   jsonb  – structured thresholds / expected values
--   historical_context text – why this rule exists (shown on part page)
-- Then inserts 16 new POWERTRAIN/ENGINE_MOUNTS bracket-specific rules.
-- ============================================================

BEGIN;

ALTER TABLE engineering_review_rules
    ADD COLUMN IF NOT EXISTS check_logic        jsonb DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS historical_context text  DEFAULT '';

-- ── MOUNTING INTERFACE ────────────────────────────────────────────────────────
INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group,
     applies_to_segments, check_logic, historical_context)
VALUES

('HOLE_CENTRE_DISTANCE_CONSISTENCY',
 'Mounting hole centre distance must match approved reference',
 'The 51.4 mm centre-to-centre distance between the upper mounting hole pair is a protected dimension. Deviation affects engine block alignment and fastener load distribution.',
 'BLOCK', 'MOUNTING_INTERFACE', '["POWERTRAIN"]',
 '{"protected_value": 51.4, "unit": "mm", "tolerance": 0.2, "dimension_names": ["hole centre distance", "centre distance", "hole center distance"]}',
 'Dimension protected across HB-000071 R7→R10 and HB-000110 R6→R8. Any deviation historically triggered a hold until confirmed with engine assembly team.')

ON CONFLICT (rule_key) DO UPDATE SET
    check_logic = EXCLUDED.check_logic,
    historical_context = EXCLUDED.historical_context;

INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group,
     applies_to_segments, check_logic, historical_context)
VALUES

('MOUNTING_HOLE_COUNT_REQUIRED',
 'Four mounting holes required for engine bracket family',
 'All Hatchback engine load brackets in this family require exactly 4 mounting holes: 2× upper Ø13 H11, 2× lower Ø12 H11. Missing holes indicate incomplete drawing.',
 'BLOCK', 'MOUNTING_INTERFACE', '["POWERTRAIN"]',
 '{"required_hole_count": 4, "expected_holes": ["Ø13 H11", "Ø12 H11"], "minimum": 4}',
 'Established during HB-000071 R7 when a variant with 2 holes caused an assembly halt. Four-hole requirement written into segment standard.')

ON CONFLICT (rule_key) DO UPDATE SET
    check_logic = EXCLUDED.check_logic,
    historical_context = EXCLUDED.historical_context;

INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group,
     applies_to_segments, check_logic, historical_context)
VALUES

('UPPER_HOLE_DIAMETER_PROTECTED',
 'Upper mounting holes must be Ø13 H11',
 'Upper mounting holes are specified as Ø13 H11 across the entire bracket family. Change requires re-qualification of engine-side mounting hardware.',
 'BLOCK', 'MOUNTING_INTERFACE', '["POWERTRAIN"]',
 '{"expected_callout": "Ø13 H11", "region_hint": "upper", "fit_class": "H11", "diameter": 13.0}',
 'Ø13 H11 standardised at HB-000071 R8 to align with engine block thread insert supplier specification.')

ON CONFLICT (rule_key) DO UPDATE SET
    check_logic = EXCLUDED.check_logic,
    historical_context = EXCLUDED.historical_context;

INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group,
     applies_to_segments, check_logic, historical_context)
VALUES

('LOWER_HOLE_DIAMETER_PROTECTED',
 'Lower mounting holes must be Ø12 H11',
 'Lower mounting holes are specified as Ø12 H11. Side-mounting interface is load-bearing under NVH conditions; fit class must not be relaxed.',
 'BLOCK', 'MOUNTING_INTERFACE', '["POWERTRAIN"]',
 '{"expected_callout": "Ø12 H11", "region_hint": "lower", "fit_class": "H11", "diameter": 12.0}',
 'Relaxation to Ø12 (no fit class) on HB-000110 R5 caused fretting wear at 40 000 km. H11 made mandatory from R6 onwards.')

ON CONFLICT (rule_key) DO UPDATE SET
    check_logic = EXCLUDED.check_logic,
    historical_context = EXCLUDED.historical_context;

INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group,
     applies_to_segments, check_logic, historical_context)
VALUES

('SIDE_REFERENCE_HEIGHT_PROTECTED',
 'Side reference height (86.9 mm) must be present',
 'The 86.9 mm side reference height defines the vertical mounting-hole position relative to the engine block datum. Missing dimension makes position unverifiable at CMM.',
 'BLOCK', 'MOUNTING_INTERFACE', '["POWERTRAIN"]',
 '{"protected_value": 86.9, "unit": "mm", "tolerance": 0.3, "dimension_names": ["side reference height", "side ref height", "reference height"]}',
 'First enforced after an HB-000071 R6 drawing omitted this height; assembly plant measured incorrectly, causing a 200-unit rework.')

ON CONFLICT (rule_key) DO UPDATE SET
    check_logic = EXCLUDED.check_logic,
    historical_context = EXCLUDED.historical_context;

-- ── ENGINE LOAD / NVH ─────────────────────────────────────────────────────────
INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group,
     applies_to_segments, check_logic, historical_context)
VALUES

('FATIGUE_SPECTRUM_NOTE_REQUIRED',
 'Fatigue load spectrum reference must appear in drawing notes',
 'Engine-mounted brackets experience multi-axis NVH loads. The applicable load spectrum document (e.g. PT-LS-235) must be referenced so downstream analysis can reproduce boundary conditions.',
 'BLOCK', 'NVH_FATIGUE', '["POWERTRAIN"]',
 '{"note_keywords": ["fatigue", "load spectrum", "PT-LS", "NVH", "vibration"], "minimum_keyword_matches": 1}',
 'Introduced after a fatigue crack on HB-000071 R4 was traced to an undocumented load profile change. Made BLOCK severity from R7 onwards.')

ON CONFLICT (rule_key) DO UPDATE SET
    check_logic = EXCLUDED.check_logic,
    historical_context = EXCLUDED.historical_context;

INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group,
     applies_to_segments, check_logic, historical_context)
VALUES

('NVH_VALIDATION_NOTE_REQUIRED',
 'NVH validation plan reference required for new bracket geometry',
 'Any geometry change to an engine bracket must reference the NVH validation plan (e.g. NVH-HBC-001) so resonance impact can be assessed before release.',
 'WARN', 'NVH_FATIGUE', '["POWERTRAIN"]',
 '{"note_keywords": ["NVH", "nvh", "resonance", "validation plan", "NVH-HBC"], "check_on_geometry_change": true}',
 'Added to checklist after HB-000110 R7 slot width change shifted bracket resonance frequency into engine idle band.')

ON CONFLICT (rule_key) DO UPDATE SET
    check_logic = EXCLUDED.check_logic,
    historical_context = EXCLUDED.historical_context;

INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group,
     applies_to_segments, check_logic, historical_context)
VALUES

('SLOT_WIDTH_INCREASE_RISK',
 'Slot width increase beyond approved value affects stiffness and tooling',
 'The approved slot width is 26 mm. Any increase reduces lateral stiffness, changes stress concentration, and may require new stamping tooling.',
 'WARN', 'NVH_FATIGUE', '["POWERTRAIN"]',
 '{"reference_value": 26.0, "unit": "mm", "dimension_names": ["slot width"], "warn_if_above": 26.0, "block_if_above": 32.0}',
 'Slot widened to 28 mm on HB-000235 R00 without ECN. Tooling impact raised as concern; returned to 26 mm in R01.')

ON CONFLICT (rule_key) DO UPDATE SET
    check_logic = EXCLUDED.check_logic,
    historical_context = EXCLUDED.historical_context;

-- ── MANUFACTURING ─────────────────────────────────────────────────────────────
INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group,
     applies_to_segments, check_logic, historical_context)
VALUES

('DEBURR_NOTE_REQUIRED',
 'Deburr and break sharp edges callout required',
 'Sheet-metal brackets must include a deburr/break-sharp-edges instruction. Absence creates assembly-line injury risk and possible harness damage at wire routing slots.',
 'WARN', 'MANUFACTURING_READINESS', '[]',
 '{"note_keywords": ["deburr", "break sharp", "break edges", "deburr and break"], "minimum_keyword_matches": 1}',
 'Standard shop-floor requirement. Omissions cause recurring non-conformance reports at goods-in inspection.')

ON CONFLICT (rule_key) DO UPDATE SET
    check_logic = EXCLUDED.check_logic,
    historical_context = EXCLUDED.historical_context;

INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group,
     applies_to_segments, check_logic, historical_context)
VALUES

('SURFACE_FINISH_REQUIRED',
 'Surface finish / coating specification must be stated',
 'Brackets must specify coating or finish treatment (e.g. powder coat, e-coat, zinc phosphate). Absence causes incorrect process selection at supplier.',
 'WARN', 'MANUFACTURING_READINESS', '[]',
 '{"note_keywords": ["powder coat", "e-coat", "zinc", "finish", "coating", "treatment", "painted"], "minimum_keyword_matches": 1}',
 'Omission on HB-000110 R3 resulted in raw steel delivery; added to standard checklist from R4.')

ON CONFLICT (rule_key) DO UPDATE SET
    check_logic = EXCLUDED.check_logic,
    historical_context = EXCLUDED.historical_context;

INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group,
     applies_to_segments, check_logic, historical_context)
VALUES

('GENERAL_TOLERANCE_STANDARD_STATED',
 'General tolerance standard must be referenced (e.g. ISO 2768)',
 'All dimensions not individually toleranced must reference a general tolerance standard. Absence causes unresolvable inspection disputes.',
 'WARN', 'MANUFACTURING_READINESS', '[]',
 '{"note_keywords": ["ISO 2768", "general tolerance", "GB/T 1804", "DIN ISO", "tolerance class"], "minimum_keyword_matches": 1}',
 'Manufacturing quality rule. Required by all three Hatchback bracket programs.')

ON CONFLICT (rule_key) DO UPDATE SET
    check_logic = EXCLUDED.check_logic,
    historical_context = EXCLUDED.historical_context;

-- ── INSPECTION READINESS ──────────────────────────────────────────────────────
INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group,
     applies_to_segments, check_logic, historical_context)
VALUES

('OVERALL_HEIGHT_PRESENT',
 'Overall height dimension (approx 152 mm) must be present',
 'Overall bracket height defines the envelope accepted by engine bay packaging. Required on every revision for CMM baseline verification.',
 'BLOCK', 'INSPECTION_READINESS', '["POWERTRAIN"]',
 '{"reference_value": 152.1, "unit": "mm", "tolerance": 5.0, "dimension_names": ["overall height", "total height", "height"]}',
 'Consistently the first dimension checked by receiving inspection across all three Hatchback programs.')

ON CONFLICT (rule_key) DO UPDATE SET
    check_logic = EXCLUDED.check_logic,
    historical_context = EXCLUDED.historical_context;

INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group,
     applies_to_segments, check_logic, historical_context)
VALUES

('LOWER_CLEARANCE_DIMENSION_PRESENT',
 'Lower clearance dimension (33 mm) must be present',
 'The 33 mm lower clearance defines minimum distance from engine oil sump. Omission makes interference-check impossible during engine installation.',
 'WARN', 'INSPECTION_READINESS', '["POWERTRAIN"]',
 '{"reference_value": 33.0, "unit": "mm", "tolerance": 2.0, "dimension_names": ["lower clearance", "clearance", "sump clearance"]}',
 'Added after HB-000110 R5 missed this dim; engine sump contact found at PDI.')

ON CONFLICT (rule_key) DO UPDATE SET
    check_logic = EXCLUDED.check_logic,
    historical_context = EXCLUDED.historical_context;

-- ── HISTORICAL APPROVAL PATTERN ───────────────────────────────────────────────
INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group,
     applies_to_segments, check_logic, historical_context)
VALUES

('NEW_FEATURE_REQUIRES_ECN',
 'New geometry features require an Engineering Change Notice reference',
 'Any feature not present in the approved reference drawing (HB-000071 or HB-000110) must reference a formal ECN. Unreferenced new features cannot be traced through the change control system.',
 'WARN', 'CHANGE_CONTROL', '[]',
 '{"check_against_reference": true, "ecn_keywords": ["ECN", "ECR", "change notice", "change request", "EC-"]}',
 'HB-000235 R00 slot addition had no ECN. Manufacturing raised a concession; workflow tightened from R01.')

ON CONFLICT (rule_key) DO UPDATE SET
    check_logic = EXCLUDED.check_logic,
    historical_context = EXCLUDED.historical_context;

INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group,
     applies_to_segments, check_logic, historical_context)
VALUES

('SECTION_VIEW_THICKNESS_SHOWN',
 'Sheet thickness must appear in section view or title block',
 'Material thickness must be explicitly dimensioned or noted. It controls bend allowance calculations, springback compensation, and incoming material inspection.',
 'WARN', 'INSPECTION_READINESS', '[]',
 '{"note_keywords": ["thickness", "t =", "t=", "sheet", "1.6", "2.0", "2.5", "3.0"], "title_block_field": "thickness"}',
 'Standard requirement enforced across all three Hatchback bracket programs from initial release.')

ON CONFLICT (rule_key) DO UPDATE SET
    check_logic = EXCLUDED.check_logic,
    historical_context = EXCLUDED.historical_context;

INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group,
     applies_to_segments, check_logic, historical_context)
VALUES

('REVISION_NOT_REGRESSING',
 'New revision must not remove approved critical dimensions',
 'Removing a critical dimension from an approved revision is a regression. All critical dimensions from the most recently approved revision should carry forward unless explicitly superseded.',
 'BLOCK', 'REVISION_PROGRESSION', '[]',
 '{"check_critical_carry_forward": true, "compare_to_approved": true}',
 'Systematic regression check added after HB-000235 R00 removed 3 critical dims from the R10 baseline.')

ON CONFLICT (rule_key) DO UPDATE SET
    check_logic = EXCLUDED.check_logic,
    historical_context = EXCLUDED.historical_context;

COMMIT;
