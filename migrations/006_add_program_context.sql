-- Migration: Add vehicle program context and segment-specific rules
-- Purpose: Give the platform organisational memory — each artifact knows which
--          vehicle program, assembly family, and product segment it belongs to.
--          Rules can declare which segments they apply to.

BEGIN;

-- ── 1. design_artifacts: program context columns ──────────────────────────────
ALTER TABLE design_artifacts
    ADD COLUMN IF NOT EXISTS product_segment  VARCHAR(80),
    ADD COLUMN IF NOT EXISTS assembly_family  VARCHAR(120),
    ADD COLUMN IF NOT EXISTS vehicle_program  VARCHAR(120);

CREATE INDEX IF NOT EXISTS idx_design_artifacts_segment
    ON design_artifacts(product_segment);
CREATE INDEX IF NOT EXISTS idx_design_artifacts_vehicle_program
    ON design_artifacts(vehicle_program);

-- ── 2. engineering_review_rules: segment applicability ────────────────────────
-- Empty array = applies to ALL segments (backwards-compatible default)
ALTER TABLE engineering_review_rules
    ADD COLUMN IF NOT EXISTS applies_to_segments JSONB DEFAULT '[]';

-- ── 3. Segment-specific rules ─────────────────────────────────────────────────
-- POWERTRAIN rules
INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group, applies_to_segments)
VALUES
    ('ENGINE_BAY_THERMAL_CLEARANCE',
     'Engine bay thermal clearance',
     'Flags insufficient clearance to engine heat sources. Minimum 15 mm radial clearance '
     'required from exhaust manifold and EGR pipe centerlines per HTEG-2.1.',
     'WARN', 'THERMAL_COMPLIANCE',
     '["POWERTRAIN"]'),

    ('VIBRATION_FATIGUE_NOTE',
     'Vibration / fatigue note missing',
     'Flags absence of a vibration-fatigue specification note on powertrain bracket drawings. '
     'All engine-mounted brackets must reference the applicable NVH load spectrum.',
     'WARN', 'FABRICATION_READINESS',
     '["POWERTRAIN"]'),

    ('ENGINE_LOAD_FIT_CLASS',
     'Engine load fit class non-compliant',
     'Blocks release when mounting hole fit deviates from the H11 class required for '
     'engine-load brackets. Incorrect fit class causes fretting and premature fatigue failure.',
     'BLOCK', 'ASSEMBLY_INTERFACE',
     '["POWERTRAIN"]')

ON CONFLICT (rule_key) DO UPDATE SET
    display_name        = EXCLUDED.display_name,
    description         = EXCLUDED.description,
    severity            = EXCLUDED.severity,
    rule_group          = EXCLUDED.rule_group,
    applies_to_segments = EXCLUDED.applies_to_segments;

-- BATTERY_SYSTEM rules
INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group, applies_to_segments)
VALUES
    ('HV_CABLE_CLEARANCE',
     'HV cable clearance insufficient',
     'Blocks release when the minimum 25 mm segregation distance from HV cables to '
     'structural members is not annotated on the drawing.',
     'BLOCK', 'ELECTRICAL_SAFETY',
     '["BATTERY_SYSTEM"]'),

    ('THERMAL_EXPANSION_SPEC',
     'Thermal expansion specification missing',
     'Flags battery mounting drawings that do not specify thermal expansion allowance '
     'between −40 °C and +60 °C operating range per BMS-THM-003.',
     'WARN', 'MATERIAL_DEFINITION',
     '["BATTERY_SYSTEM"]'),

    ('BATTERY_RETENTION_SPEC',
     'Battery retention specification incomplete',
     'Flags missing or incomplete retention-load specification (minimum 3 g lateral, '
     '5 g vertical shock load) on battery mounting brackets.',
     'WARN', 'FABRICATION_READINESS',
     '["BATTERY_SYSTEM"]')

ON CONFLICT (rule_key) DO UPDATE SET
    display_name        = EXCLUDED.display_name,
    description         = EXCLUDED.description,
    severity            = EXCLUDED.severity,
    rule_group          = EXCLUDED.rule_group,
    applies_to_segments = EXCLUDED.applies_to_segments;

-- CHASSIS_STRUCTURE rules
INSERT INTO engineering_review_rules
    (rule_key, display_name, description, severity, rule_group, applies_to_segments)
VALUES
    ('WELD_PENETRATION_DEPTH',
     'Weld penetration depth not specified',
     'Blocks release when full-penetration weld symbols on chassis structure drawings '
     'lack minimum throat / penetration depth callout.',
     'BLOCK', 'FABRICATION_READINESS',
     '["CHASSIS_STRUCTURE"]'),

    ('CHASSIS_LOAD_PATH',
     'Chassis load path not documented',
     'Flags chassis brackets without a load-path diagram or reference to the applicable '
     'load-case analysis document in the title block notes.',
     'WARN', 'DOCUMENT_TRACEABILITY',
     '["CHASSIS_STRUCTURE"]'),

    ('FRAME_ALIGNMENT_DATUM',
     'Frame alignment datum missing',
     'Flags chassis components that do not reference the vehicle coordinate system '
     'datum (X0/Y0/Z0) on at least one primary view.',
     'WARN', 'DRAFTING_COMPLIANCE',
     '["CHASSIS_STRUCTURE"]')

ON CONFLICT (rule_key) DO UPDATE SET
    display_name        = EXCLUDED.display_name,
    description         = EXCLUDED.description,
    severity            = EXCLUDED.severity,
    rule_group          = EXCLUDED.rule_group,
    applies_to_segments = EXCLUDED.applies_to_segments;

COMMIT;
