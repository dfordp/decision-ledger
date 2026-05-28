-- Migration: Add ReviewGraph review sessions, graph memory, and deterministic rule results
-- Purpose: Foundation slice for graph-native engineering review intelligence

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS engineering_review_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_number VARCHAR(80) UNIQUE NOT NULL,
    review_type VARCHAR(50) NOT NULL DEFAULT 'REVISION_IMPACT',
    title VARCHAR(255) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'DRAFT'
        CHECK (status IN ('DRAFT', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'CLOSED')),
    risk_status VARCHAR(10) NOT NULL DEFAULT 'SAFE'
        CHECK (risk_status IN ('SAFE', 'WARN', 'BLOCK')),
    part_revision_id UUID REFERENCES part_revisions(id) ON DELETE SET NULL,
    part_id UUID REFERENCES parts(id) ON DELETE SET NULL,
    summary_json JSONB DEFAULT '{}',
    reviewer_notes TEXT,
    created_by VARCHAR(100) DEFAULT 'system',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    closed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_review_sessions_revision ON engineering_review_sessions(part_revision_id);
CREATE INDEX IF NOT EXISTS idx_review_sessions_part ON engineering_review_sessions(part_id);
CREATE INDEX IF NOT EXISTS idx_review_sessions_status ON engineering_review_sessions(status);
CREATE INDEX IF NOT EXISTS idx_review_sessions_risk ON engineering_review_sessions(risk_status);

CREATE TABLE IF NOT EXISTS engineering_review_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES engineering_review_sessions(id) ON DELETE CASCADE,
    item_type VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    source_type VARCHAR(80),
    source_id VARCHAR(120),
    payload_json JSONB DEFAULT '{}',
    risk_status VARCHAR(10) NOT NULL DEFAULT 'SAFE'
        CHECK (risk_status IN ('SAFE', 'WARN', 'BLOCK')),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_review_items_session ON engineering_review_items(session_id);
CREATE INDEX IF NOT EXISTS idx_review_items_source ON engineering_review_items(source_type, source_id);

CREATE TABLE IF NOT EXISTS engineering_review_rules (
    id SERIAL PRIMARY KEY,
    rule_key VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    description TEXT,
    severity VARCHAR(10) NOT NULL DEFAULT 'WARN'
        CHECK (severity IN ('SAFE', 'WARN', 'BLOCK')),
    rule_group VARCHAR(80) NOT NULL DEFAULT 'REVISION_IMPACT',
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS engineering_review_rule_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES engineering_review_sessions(id) ON DELETE CASCADE,
    rule_id INT REFERENCES engineering_review_rules(id),
    rule_key VARCHAR(100) NOT NULL,
    status VARCHAR(10) NOT NULL CHECK (status IN ('SAFE', 'WARN', 'BLOCK')),
    confidence INTEGER NOT NULL DEFAULT 80 CHECK (confidence >= 0 AND confidence <= 100),
    triggered BOOLEAN NOT NULL DEFAULT FALSE,
    explanation TEXT NOT NULL,
    evidence_json JSONB DEFAULT '[]',
    recommended_actions JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rule_results_session ON engineering_review_rule_results(session_id);
CREATE INDEX IF NOT EXISTS idx_rule_results_status ON engineering_review_rule_results(status);

CREATE TABLE IF NOT EXISTS engineering_review_findings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES engineering_review_sessions(id) ON DELETE CASCADE,
    rule_result_id UUID REFERENCES engineering_review_rule_results(id) ON DELETE SET NULL,
    finding_type VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,
    status VARCHAR(10) NOT NULL CHECK (status IN ('SAFE', 'WARN', 'BLOCK')),
    explanation TEXT NOT NULL,
    affected_entity_type VARCHAR(80),
    affected_entity_id VARCHAR(120),
    recommended_action TEXT,
    reviewer_override_status VARCHAR(10) CHECK (reviewer_override_status IN ('SAFE', 'WARN', 'BLOCK')),
    reviewer_notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_findings_session ON engineering_review_findings(session_id);
CREATE INDEX IF NOT EXISTS idx_findings_status ON engineering_review_findings(status);

CREATE TABLE IF NOT EXISTS engineering_review_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES engineering_review_sessions(id) ON DELETE CASCADE,
    finding_id UUID REFERENCES engineering_review_findings(id) ON DELETE CASCADE,
    evidence_type VARCHAR(80) NOT NULL,
    source_type VARCHAR(80) NOT NULL,
    source_id VARCHAR(120),
    title VARCHAR(255) NOT NULL,
    excerpt TEXT,
    relevance_score DECIMAL(5, 4),
    payload_json JSONB DEFAULT '{}',
    embedding vector(1536),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_review_evidence_session ON engineering_review_evidence(session_id);
CREATE INDEX IF NOT EXISTS idx_review_evidence_source ON engineering_review_evidence(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_review_evidence_embedding ON engineering_review_evidence USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS engineering_graph_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(80) NOT NULL,
    entity_id VARCHAR(120) NOT NULL,
    label VARCHAR(255) NOT NULL,
    metadata_json JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_graph_nodes_entity ON engineering_graph_nodes(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS engineering_graph_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_node_id UUID NOT NULL REFERENCES engineering_graph_nodes(id) ON DELETE CASCADE,
    target_node_id UUID NOT NULL REFERENCES engineering_graph_nodes(id) ON DELETE CASCADE,
    relationship_type VARCHAR(80) NOT NULL,
    confidence INTEGER DEFAULT 90 CHECK (confidence >= 0 AND confidence <= 100),
    evidence_json JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(source_node_id, target_node_id, relationship_type)
);

CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON engineering_graph_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON engineering_graph_edges(target_node_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_type ON engineering_graph_edges(relationship_type);

CREATE TABLE IF NOT EXISTS review_approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES engineering_review_sessions(id) ON DELETE CASCADE,
    approver_name VARCHAR(120) NOT NULL,
    approver_role VARCHAR(120),
    approval_status VARCHAR(30) NOT NULL DEFAULT 'PENDING'
        CHECK (approval_status IN ('PENDING', 'APPROVED', 'REJECTED', 'WAIVED')),
    comments TEXT,
    decided_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_review_approvals_session ON review_approvals(session_id);

CREATE TABLE IF NOT EXISTS review_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES engineering_review_sessions(id) ON DELETE CASCADE,
    action VARCHAR(80) NOT NULL,
    actor VARCHAR(120) NOT NULL DEFAULT 'system',
    old_values JSONB,
    new_values JSONB,
    comments TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_review_audit_session ON review_audit_log(session_id);

INSERT INTO engineering_review_rules (rule_key, display_name, description, severity, rule_group)
VALUES
    ('HIGH_IMPORTANCE_SPEC_CHANGE', 'High importance specification change', 'Flags high-importance material, safety, thermal, voltage, or large numeric deltas.', 'WARN', 'REVISION_IMPACT'),
    ('MATERIAL_CHANGE_WITH_INCIDENTS', 'Material change with historical incidents', 'Flags material changes when part-family incidents exist.', 'WARN', 'MANUFACTURING'),
    ('TOLERANCE_OR_GEOMETRY_REQUIRES_VALIDATION', 'Tolerance or geometry change requires validation review', 'Flags geometry and tolerance changes that may alter validation coverage.', 'WARN', 'VALIDATION'),
    ('HIGH_RPN_CARRY_FORWARD', 'High RPN failure mode carried into revision', 'Blocks or warns when prior high-risk DFMEA entries need review for the new revision.', 'BLOCK', 'DFMEA'),
    ('NO_PRIOR_DFMEA', 'No prior DFMEA baseline', 'Warns when a revision has no prior DFMEA entries to ground continuity.', 'WARN', 'DFMEA')
ON CONFLICT (rule_key) DO NOTHING;

COMMIT;
