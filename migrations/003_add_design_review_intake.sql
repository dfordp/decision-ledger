-- Migration: Add design-data-first intake for ReviewGraph
-- Purpose: Make drawing/design revisions the primary ReviewGraph source, with DFMEA as linked evidence

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS design_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_number VARCHAR(120) UNIQUE NOT NULL,
    title VARCHAR(255) NOT NULL,
    artifact_type VARCHAR(50) NOT NULL DEFAULT 'ENGINEERING_DRAWING'
        CHECK (artifact_type IN ('ENGINEERING_DRAWING', 'CAD_MODEL', 'SPECIFICATION', 'REDLINE_PACKAGE')),
    domain VARCHAR(100),
    owning_team VARCHAR(120),
    supplier VARCHAR(255),
    material VARCHAR(120),
    linked_part_number VARCHAR(120),
    metadata_json JSONB DEFAULT '{}',
    embedding vector(1536),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_design_artifacts_number ON design_artifacts(artifact_number);
CREATE INDEX IF NOT EXISTS idx_design_artifacts_part_number ON design_artifacts(linked_part_number);
CREATE INDEX IF NOT EXISTS idx_design_artifacts_embedding ON design_artifacts USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS design_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id UUID NOT NULL REFERENCES design_artifacts(id) ON DELETE CASCADE,
    revision_code VARCHAR(40) NOT NULL,
    revision_sequence INTEGER NOT NULL,
    change_summary TEXT,
    source_filename VARCHAR(255),
    previous_data_json JSONB DEFAULT '{}',
    design_data_json JSONB NOT NULL DEFAULT '{}',
    extraction_summary_json JSONB DEFAULT '{}',
    changed_by VARCHAR(120) DEFAULT 'system',
    approval_status VARCHAR(40) DEFAULT 'draft'
        CHECK (approval_status IN ('draft', 'in_review', 'approved', 'rejected')),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(artifact_id, revision_sequence),
    UNIQUE(artifact_id, revision_code)
);

CREATE INDEX IF NOT EXISTS idx_design_revisions_artifact ON design_revisions(artifact_id);
CREATE INDEX IF NOT EXISTS idx_design_revisions_sequence ON design_revisions(artifact_id, revision_sequence);

CREATE TABLE IF NOT EXISTS design_extracted_features (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    design_revision_id UUID NOT NULL REFERENCES design_revisions(id) ON DELETE CASCADE,
    feature_type VARCHAR(80) NOT NULL,
    feature_key VARCHAR(160) NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    value_json JSONB DEFAULT '{}',
    unit VARCHAR(40),
    source_reference VARCHAR(120),
    criticality VARCHAR(20) DEFAULT 'MEDIUM'
        CHECK (criticality IN ('LOW', 'MEDIUM', 'HIGH', 'SAFETY_CRITICAL')),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_design_features_revision ON design_extracted_features(design_revision_id);
CREATE INDEX IF NOT EXISTS idx_design_features_type ON design_extracted_features(feature_type);
CREATE INDEX IF NOT EXISTS idx_design_features_key ON design_extracted_features(feature_key);

CREATE TABLE IF NOT EXISTS design_revision_changes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    design_revision_id UUID NOT NULL REFERENCES design_revisions(id) ON DELETE CASCADE,
    change_type VARCHAR(80) NOT NULL,
    feature_key VARCHAR(160) NOT NULL,
    field_path VARCHAR(255) NOT NULL,
    old_value JSONB,
    new_value JSONB,
    importance VARCHAR(20) NOT NULL DEFAULT 'MEDIUM'
        CHECK (importance IN ('LOW', 'MEDIUM', 'HIGH', 'SAFETY_CRITICAL')),
    deterministic_reason TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_design_changes_revision ON design_revision_changes(design_revision_id);
CREATE INDEX IF NOT EXISTS idx_design_changes_type ON design_revision_changes(change_type);
CREATE INDEX IF NOT EXISTS idx_design_changes_importance ON design_revision_changes(importance);

ALTER TABLE engineering_review_sessions
ADD COLUMN IF NOT EXISTS design_revision_id UUID REFERENCES design_revisions(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_review_sessions_design_revision ON engineering_review_sessions(design_revision_id);

INSERT INTO engineering_review_rules (rule_key, display_name, description, severity, rule_group)
VALUES
    ('DRAWING_TOLERANCE_TIGHTENED', 'Drawing tolerance tightened', 'Flags tightened tolerance bands that may affect manufacturing capability or inspection plans.', 'WARN', 'DRAWING_REVIEW'),
    ('SAFETY_CRITICAL_DIMENSION_CHANGED', 'Safety critical dimension changed', 'Blocks review when a safety-critical dimension changes without explicit validation evidence.', 'BLOCK', 'DRAWING_REVIEW'),
    ('MATERIAL_SUBSTITUTION_REVIEW', 'Material substitution review', 'Flags drawing material changes for engineering and supplier review.', 'WARN', 'DRAWING_REVIEW'),
    ('FASTENER_OR_INTERFACE_CHANGED', 'Fastener or interface changed', 'Flags interface, mounting, or fastener changes that may propagate to assemblies.', 'WARN', 'ASSEMBLY_IMPACT'),
    ('INSPECTION_METHOD_IMPACTED', 'Inspection method impacted', 'Flags changes that require inspection method, gauge, or validation-plan updates.', 'WARN', 'MANUFACTURING')
ON CONFLICT (rule_key) DO NOTHING;

COMMIT;
