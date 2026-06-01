-- ============================================================
-- Migration 009 — Engineering Context on Design Artifacts
-- ============================================================
-- Adds engineering_context jsonb to design_artifacts.
-- Stores what the part does, its load cases, assembly interfaces,
-- why specific dimensions are critical, and known failure modes.
-- This context is passed to Groq during validation so it understands
-- the engineering intent behind each drawing check.
-- ============================================================

BEGIN;

ALTER TABLE design_artifacts
    ADD COLUMN IF NOT EXISTS engineering_context jsonb DEFAULT '{}';

COMMENT ON COLUMN design_artifacts.engineering_context IS
    'Structured engineering narrative: function, load_case, assembly_interface, '
    'critical_dimensions, performance_requirements, design_constraints, known_failure_modes';

COMMIT;
