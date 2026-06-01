-- ============================================================
-- Migration 008 — Artifact-Level Rule Profiles
-- ============================================================
-- Adds design_artifact_rules table so each drawing artifact can:
--   override  — change severity or check_logic for a segment rule
--   skip      — disable a segment rule (doesn't apply to this part)
--   add       — define a new rule unique to this artifact
--
-- This is the "approval intelligence profile" for a specific part.
-- It sits on top of engineering_review_rules and is merged by
-- run_groq_validation() before each Groq evaluation call.
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS design_artifact_rules (
    id               UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    artifact_id      UUID         NOT NULL REFERENCES design_artifacts(id) ON DELETE CASCADE,
    rule_key         VARCHAR(100) NOT NULL,
    action           VARCHAR(20)  NOT NULL DEFAULT 'override'
                         CHECK (action IN ('override','skip','add')),
    -- For 'override' / 'add':
    override_severity  VARCHAR(10)  CHECK (override_severity IN ('BLOCK','WARN','SAFE')),
    display_name       VARCHAR(255),
    artifact_context   TEXT,          -- why this override/addition exists for this part
    check_logic        JSONB    DEFAULT '{}',
    created_at         TIMESTAMP DEFAULT now(),
    UNIQUE (artifact_id, rule_key)
);

CREATE INDEX IF NOT EXISTS idx_artifact_rules_artifact ON design_artifact_rules(artifact_id);

COMMIT;
