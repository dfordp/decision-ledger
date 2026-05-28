-- Migration: Add drawing-validation entities and deterministic review results
-- Purpose: Reposition ReviewGraph around engineering drawing validation while preserving existing review sessions.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS drawing_feature_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    design_revision_id UUID NOT NULL REFERENCES design_revisions(id) ON DELETE CASCADE,
    entity_type VARCHAR(80) NOT NULL,
    entity_key VARCHAR(160) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    drawing_region VARCHAR(120),
    sheet_reference VARCHAR(120),
    geometry_json JSONB DEFAULT '{}',
    relationships_json JSONB DEFAULT '{}',
    extraction_confidence INTEGER DEFAULT 90 CHECK (extraction_confidence >= 0 AND extraction_confidence <= 100),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(design_revision_id, entity_key)
);

CREATE INDEX IF NOT EXISTS idx_drawing_entities_revision ON drawing_feature_entities(design_revision_id);
CREATE INDEX IF NOT EXISTS idx_drawing_entities_type ON drawing_feature_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_drawing_entities_key ON drawing_feature_entities(entity_key);

CREATE TABLE IF NOT EXISTS drawing_dimensions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    design_revision_id UUID NOT NULL REFERENCES design_revisions(id) ON DELETE CASCADE,
    entity_id UUID REFERENCES drawing_feature_entities(id) ON DELETE SET NULL,
    dimension_key VARCHAR(160) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    nominal_value DECIMAL(14, 4),
    unit VARCHAR(40),
    tolerance_json JSONB DEFAULT '{}',
    chain_key VARCHAR(160),
    is_critical BOOLEAN DEFAULT FALSE,
    drawing_region VARCHAR(120),
    source_reference VARCHAR(120),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drawing_dimensions_revision ON drawing_dimensions(design_revision_id);
CREATE INDEX IF NOT EXISTS idx_drawing_dimensions_chain ON drawing_dimensions(chain_key);
CREATE INDEX IF NOT EXISTS idx_drawing_dimensions_critical ON drawing_dimensions(is_critical);

CREATE TABLE IF NOT EXISTS drawing_annotations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    design_revision_id UUID NOT NULL REFERENCES design_revisions(id) ON DELETE CASCADE,
    entity_id UUID REFERENCES drawing_feature_entities(id) ON DELETE SET NULL,
    annotation_type VARCHAR(80) NOT NULL,
    annotation_key VARCHAR(160) NOT NULL,
    display_text TEXT NOT NULL,
    drawing_region VARCHAR(120),
    source_reference VARCHAR(120),
    metadata_json JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drawing_annotations_revision ON drawing_annotations(design_revision_id);
CREATE INDEX IF NOT EXISTS idx_drawing_annotations_type ON drawing_annotations(annotation_type);

CREATE TABLE IF NOT EXISTS drawing_validation_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    design_revision_id UUID NOT NULL REFERENCES design_revisions(id) ON DELETE CASCADE,
    rule_key VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('CRITICAL', 'MAJOR', 'MINOR', 'INFO')),
    status VARCHAR(10) NOT NULL CHECK (status IN ('SAFE', 'WARN', 'BLOCK')),
    title VARCHAR(255) NOT NULL,
    what_is_wrong TEXT NOT NULL,
    why_it_matters TEXT NOT NULL,
    affected_entities JSONB DEFAULT '[]',
    affected_regions JSONB DEFAULT '[]',
    recommended_action TEXT NOT NULL,
    evidence_json JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drawing_validation_revision ON drawing_validation_results(design_revision_id);
CREATE INDEX IF NOT EXISTS idx_drawing_validation_rule ON drawing_validation_results(rule_key);
CREATE INDEX IF NOT EXISTS idx_drawing_validation_status ON drawing_validation_results(status);

CREATE TABLE IF NOT EXISTS drawing_reference_baselines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES design_artifacts(id) ON DELETE CASCADE,
    design_revision_id UUID NOT NULL REFERENCES design_revisions(id) ON DELETE CASCADE,
    baseline_name VARCHAR(160) NOT NULL,
    approval_status VARCHAR(60) DEFAULT 'APPROVED_REFERENCE',
    baseline_metadata_json JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(artifact_id, design_revision_id)
);

CREATE INDEX IF NOT EXISTS idx_drawing_baselines_artifact ON drawing_reference_baselines(artifact_id);

CREATE TABLE IF NOT EXISTS drawing_revision_pairs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES design_artifacts(id) ON DELETE CASCADE,
    baseline_revision_id UUID NOT NULL REFERENCES design_revisions(id) ON DELETE CASCADE,
    compared_revision_id UUID NOT NULL REFERENCES design_revisions(id) ON DELETE CASCADE,
    comparison_type VARCHAR(60) DEFAULT 'REFERENCE_COMPARISON',
    comparison_summary_json JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(baseline_revision_id, compared_revision_id)
);

CREATE INDEX IF NOT EXISTS idx_drawing_pairs_artifact ON drawing_revision_pairs(artifact_id);
CREATE INDEX IF NOT EXISTS idx_drawing_pairs_compared ON drawing_revision_pairs(compared_revision_id);

INSERT INTO engineering_review_rules (rule_key, display_name, description, severity, rule_group)
VALUES
    ('MISSING_REQUIRED_DIMENSION', 'Missing required dimension', 'Blocks release when a critical drawing feature lacks a dimensional reference.', 'BLOCK', 'DRAWING_VALIDATION'),
    ('MISSING_TOLERANCE_SPECIFICATION', 'Missing tolerance specification', 'Blocks release when production-critical dimensions lack tolerance guidance.', 'BLOCK', 'DRAFTING_COMPLIANCE'),
    ('MISSING_HOLE_CALLOUT', 'Missing hole callout', 'Blocks release when mounting holes lack diameter, thread, or callout definition.', 'BLOCK', 'ASSEMBLY_INTERFACE'),
    ('MISSING_SECTION_REFERENCE', 'Missing section reference', 'Blocks release when section geometry lacks explicit section annotation.', 'BLOCK', 'FABRICATION_READINESS'),
    ('INCOMPLETE_DIMENSION_CHAIN', 'Incomplete dimension chain', 'Flags features that cannot be fully traced through inspection dimensions.', 'WARN', 'INSPECTION_READINESS'),
    ('INCOMPLETE_WELD_NOTE', 'Incomplete weld note', 'Flags weld locations without sufficient fabrication guidance.', 'WARN', 'FABRICATION_READINESS'),
    ('TITLE_BLOCK_INCOMPLETE', 'Title block incomplete', 'Flags missing drawing metadata such as revision, material, or scale.', 'WARN', 'DOCUMENT_TRACEABILITY'),
    ('MISSING_THICKNESS_CALLOUT', 'Missing thickness callout', 'Flags missing sheet thickness definition on fabrication drawings.', 'WARN', 'MATERIAL_DEFINITION'),
    ('ANNOTATION_ALIGNMENT_INCONSISTENCY', 'Annotation alignment inconsistency', 'Flags annotation placement or leader inconsistencies that reduce drawing clarity.', 'WARN', 'DRAFTING_CLARITY'),
    ('DUPLICATE_DIMENSION_REFERENCE', 'Duplicate dimension reference', 'Flags repeated dimensions that may create conflicting inspection interpretation.', 'WARN', 'DRAFTING_CLARITY'),
    ('INCONSISTENT_NOTE_FORMATTING', 'Inconsistent note formatting', 'Flags inconsistent note formatting across drawing views.', 'WARN', 'DRAFTING_CLARITY'),
    ('VIEW_LABEL_INCONSISTENCY', 'View label inconsistency', 'Flags inconsistent or missing view labels.', 'WARN', 'DRAFTING_CLARITY')
ON CONFLICT (rule_key) DO NOTHING;

COMMIT;
