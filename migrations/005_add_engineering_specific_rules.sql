-- Migration: Add engineering-specific validation rules
-- Purpose: Extend the rule catalog with CRCA bend radius, reference envelope, and mixed fastener checks.

BEGIN;

INSERT INTO engineering_review_rules (rule_key, display_name, description, severity, rule_group)
VALUES
    ('FEATURE_OUTSIDE_REFERENCE_ENVELOPE',
     'Feature outside reference envelope',
     'Blocks release when a feature in this revision is absent from the approved reference drawing. An Engineering Change Notice (ECN) is required before manufacture.',
     'BLOCK', 'ASSEMBLY_INTERFACE'),
    ('BEND_RADIUS_BELOW_MINIMUM',
     'Bend radius below 1×t minimum',
     'Blocks release when the specified inside bend radius is below the 1×material-thickness minimum for CRCA IS 513 Grade D sheet metal.',
     'BLOCK', 'MANUFACTURING_CONSTRAINT'),
    ('MIXED_FASTENER_SIZES',
     'Mixed fastener/hole sizes',
     'Flags asymmetric hole diameters that imply different fastener standards across mounting points; requires BOM confirmation.',
     'WARN', 'ASSEMBLY_INTERFACE')
ON CONFLICT (rule_key) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description  = EXCLUDED.description,
    severity     = EXCLUDED.severity,
    rule_group   = EXCLUDED.rule_group;

COMMIT;
