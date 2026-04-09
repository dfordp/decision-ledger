-- ============================================================================
-- PFMEA (Process Failure Mode & Effects Analysis) Schema
-- Created: 2026-04-06
-- Purpose: Enterprise-wide standardized FMEA system for manufacturing processes
-- ============================================================================

-- Enable pgvector extension (if not already enabled)
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- 1. FAILURE MODE TAXONOMY (Standardized company-wide failure modes)
-- ============================================================================
CREATE TABLE IF NOT EXISTS failure_mode_taxonomy (
    id SERIAL PRIMARY KEY,
    canonical_name VARCHAR(256) NOT NULL UNIQUE,
    description TEXT,
    category VARCHAR(50) NOT NULL DEFAULT 'MANUFACTURING',
        -- Categories: ELECTRICAL, MECHANICAL, SURFACE, PROCESS_CONTROL, MATERIAL, SAFETY, OTHER
    
    -- Standardization & Governance
    typical_severity_range INT[] DEFAULT '{3,7}',  -- e.g., [3,7] means typically 3-7
    version INT DEFAULT 1,
    approved_by VARCHAR(100),
    approved_at TIMESTAMP,
    aliases TEXT[] DEFAULT '{}',  -- e.g., ["Short circuit", "Circuit failure"]
    
    -- Semantic Search
    embedding vector(1536),
    
    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_failure_mode_canonical ON failure_mode_taxonomy(canonical_name);
CREATE INDEX idx_failure_mode_category ON failure_mode_taxonomy(category);
CREATE INDEX idx_failure_mode_embedding ON failure_mode_taxonomy USING hnsw (embedding vector_cosine_ops);

-- ============================================================================
-- 2. PFMEA RECORDS (Master FMEA record per part/process)
-- ============================================================================
CREATE TABLE IF NOT EXISTS pfmea_records (
    id SERIAL PRIMARY KEY,
    part_number VARCHAR(50) NOT NULL,
    part_name VARCHAR(256) NOT NULL,
    model_year VARCHAR(50),
    
    -- Metadata
    customer_name VARCHAR(256),
    process_responsibility VARCHAR(100),
    core_team TEXT[] DEFAULT '{}',  -- Array of engineer names
    domain VARCHAR(100),  -- e.g., "ELECTRICAL", "AUTOMOTIVE", "PLATING"
    
    -- FMEA Administration
    fmea_date_original DATE,
    fmea_revision_date DATE,
    format_number VARCHAR(50),
    status VARCHAR(20) DEFAULT 'DRAFT',
        -- Status: DRAFT, REVIEW, APPROVED, IMPLEMENTATION, CLOSED
    
    -- Canvas Session & Scoring
    canvas_session_id UUID,
    last_modified_by VARCHAR(100),
    overall_rpn INT,  -- Maximum RPN across all failure modes
    overall_rpn_average FLOAT,  -- Average RPN
    canvas_state JSONB,  -- Temporary unsaved edits
    
    -- Semantic Search
    embedding vector(1536),
    
    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_pfmea_part_number ON pfmea_records(part_number);
CREATE INDEX idx_pfmea_status ON pfmea_records(status);
CREATE INDEX idx_pfmea_embedding ON pfmea_records USING hnsw (embedding vector_cosine_ops);

-- ============================================================================
-- 3. PROCESS STEPS (Steps within a PFMEA)
-- ============================================================================
CREATE TABLE IF NOT EXISTS process_steps (
    id SERIAL PRIMARY KEY,
    pfmea_record_id INT NOT NULL REFERENCES pfmea_records(id) ON DELETE CASCADE,
    step_number INT NOT NULL,  -- e.g., 10, 20, 30 (allows gaps for insertion)
    step_name VARCHAR(256) NOT NULL,
    process_function TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_process_steps_pfmea_id ON process_steps(pfmea_record_id);
CREATE INDEX idx_process_steps_step_number ON process_steps(step_number);

-- ============================================================================
-- 4. PFMEA FAILURE MODE ENTRIES (One row per failure mode per FMEA)
-- ============================================================================
CREATE TABLE IF NOT EXISTS pfmea_failure_mode_entries (
    id SERIAL PRIMARY KEY,
    pfmea_record_id INT NOT NULL REFERENCES pfmea_records(id) ON DELETE CASCADE,
    process_step_id INT REFERENCES process_steps(id) ON DELETE SET NULL,
    process_step_number INT,  -- Denormalized for query speed
    
    -- Failure Mode Reference
    failure_mode_id INT NOT NULL REFERENCES failure_mode_taxonomy(id),
    
    -- RPN Scoring (User Input)
    severity_user_input INT,  -- 1-10
    occurrence_user_input INT,  -- 1-10
    detection_user_input INT,  -- 1-10
    rpn_user_calculated INT,  -- S × O × D
    
    -- RPN Scoring (Historical Suggestion)
    severity_suggested INT,
    occurrence_suggested INT,
    detection_suggested INT,
    rpn_suggested INT,
    similar_incidents_count INT DEFAULT 0,
    
    -- Risk Classification
    rpn_risk_class VARCHAR(10),  -- HIGH, MED, LOW (auto-calculated)
    
    -- Context
    potential_effect TEXT,
    justification TEXT,
    source_excerpt TEXT,
    canvas_notes TEXT,
    
    -- Semantic Search
    embedding vector(1536),
    
    -- Post-Action Follow-up (After remediation)
    severity_after INT,
    occurrence_after INT,
    detection_after INT,
    rpn_after INT,
    
    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_pfmea_entry_record_id ON pfmea_failure_mode_entries(pfmea_record_id);
CREATE INDEX idx_pfmea_entry_failure_mode_id ON pfmea_failure_mode_entries(failure_mode_id);
CREATE INDEX idx_pfmea_entry_rpn ON pfmea_failure_mode_entries(rpn_user_calculated);
CREATE INDEX idx_pfmea_entry_risk_class ON pfmea_failure_mode_entries(rpn_risk_class);
CREATE INDEX idx_pfmea_entry_embedding ON pfmea_failure_mode_entries USING hnsw (embedding vector_cosine_ops);

-- ============================================================================
-- 5. FAILURE MODE CAUSES (1:N relationship - multiple causes per failure)
-- ============================================================================
CREATE TABLE IF NOT EXISTS failure_mode_causes (
    id SERIAL PRIMARY KEY,
    fmea_entry_id INT NOT NULL REFERENCES pfmea_failure_mode_entries(id) ON DELETE CASCADE,
    cause_sequence INT DEFAULT 1,  -- Order for display (1, 2, 3, etc.)
    
    -- Cause Information
    canonical_cause VARCHAR(256) NOT NULL,
    cause_category VARCHAR(50),  -- MATERIAL, OPERATOR, DESIGN, PROCESS_PARAM, EQUIPMENT, ENVIRONMENT
    description TEXT,
    
    -- Individual Occurrence Score (may vary per cause)
    occurrence_score INT,  -- 1-10
    
    -- Semantic Search
    embedding vector(1536),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_causes_fmea_entry ON failure_mode_causes(fmea_entry_id);
CREATE INDEX idx_causes_canonical ON failure_mode_causes(canonical_cause);
CREATE INDEX idx_causes_category ON failure_mode_causes(cause_category);

-- ============================================================================
-- 6. PROCESS CONTROLS (Prevention & Detection)
-- ============================================================================
CREATE TABLE IF NOT EXISTS process_controls (
    id SERIAL PRIMARY KEY,
    fmea_entry_id INT NOT NULL REFERENCES pfmea_failure_mode_entries(id) ON DELETE CASCADE,
    control_type VARCHAR(20) NOT NULL,  -- PREVENTION or DETECTION
    
    -- Control Description
    control_description TEXT NOT NULL,
    method VARCHAR(100),  -- Visual, Automatic, SPC, Manual, etc.
    frequency VARCHAR(100),  -- 100%, Every hour, Sampling, Every 2 hours, etc.
    effectiveness_percent INT DEFAULT 90,  -- 0-100, used for D score calculation
    
    -- Semantic Search
    embedding vector(1536),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_controls_fmea_entry ON process_controls(fmea_entry_id);
CREATE INDEX idx_controls_type ON process_controls(control_type);

-- ============================================================================
-- 7. HISTORICAL INCIDENTS (Field failures for trending)
-- ============================================================================
CREATE TABLE IF NOT EXISTS historical_incidents (
    id SERIAL PRIMARY KEY,
    part_number VARCHAR(50) NOT NULL,
    failure_mode_id INT NOT NULL REFERENCES failure_mode_taxonomy(id),
    
    -- Incident Details
    incident_date DATE NOT NULL,
    location VARCHAR(256),  -- Plant, field, warehouse, etc.
    description TEXT,
    root_cause TEXT,
    
    -- Impact Metrics
    impact_hours INT,  -- Operational hours before detection
    impact_units INT,  -- How many units affected
    severity_actual INT,  -- Field-observed severity (1-10)
    
    -- Resolution
    corrective_action TEXT,
    action_completion_date DATE,
    
    -- Semantic Search
    embedding vector(1536),
    
    -- Reference
    source_document VARCHAR(256),  -- Incident report ID
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_incidents_part_number ON historical_incidents(part_number);
CREATE INDEX idx_incidents_failure_mode ON historical_incidents(failure_mode_id);
CREATE INDEX idx_incidents_date ON historical_incidents(incident_date);
CREATE INDEX idx_incidents_embedding ON historical_incidents USING hnsw (embedding vector_cosine_ops);

-- ============================================================================
-- 8. FMEA COMMENTS/AUDIT TRAIL (Track changes and approvals)
-- ============================================================================
CREATE TABLE IF NOT EXISTS fmea_audit_log (
    id SERIAL PRIMARY KEY,
    pfmea_record_id INT NOT NULL REFERENCES pfmea_records(id) ON DELETE CASCADE,
    action VARCHAR(50) NOT NULL,  -- CREATED, UPDATED, APPROVED, REJECTED, CLOSED
    actor VARCHAR(100) NOT NULL,
    old_values JSONB,
    new_values JSONB,
    comments TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_audit_pfmea_id ON fmea_audit_log(pfmea_record_id);
CREATE INDEX idx_audit_action ON fmea_audit_log(action);

-- ============================================================================
-- Sample Data Insertion (Optional - for demo)
-- ============================================================================

-- Insert sample failure mode taxonomy
INSERT INTO failure_mode_taxonomy (canonical_name, category, typical_severity_range, aliases, description)
VALUES 
    ('Short Circuiting', 'ELECTRICAL', '{3,9}', '{"Short circuit", "Circuit failure", "Circuit short"}', 'Unwanted electrical path causing current bypass'),
    ('Resistance Variation', 'ELECTRICAL', '{3,6}', '{"High/low resistance", "Resistance drift"}', 'Resistance value outside specified range'),
    ('Mechanical Fracture', 'MECHANICAL', '{6,10}', '{"Crack", "Break", "Fracture propagation"}', 'Component separation or crack propagation'),
    ('Loose Fit', 'MECHANICAL', '{2,5}', '{"Loosening", "Vibration looseness"}', 'Component looseness due to insufficient torque or wear'),
    ('Surface Scratches', 'SURFACE', '{2,4}', '{"Surface defect", "Scratching", "Scuff"}', 'Surface damage affecting appearance or function'),
    ('Corrosion', 'MATERIAL', '{4,8}', '{"Oxidation", "Rust", "Material degradation"}', 'Chemical degradation of material'),
    ('Operator Error', 'PROCESS_CONTROL', '{2,7}', '{"Operator negligence", "Inadequate training", "Human error"}', 'Failure due to operator mistake or inadequate procedure'),
    ('Equipment Calibration', 'PROCESS_CONTROL', '{3,6}', '{"Out of calibration", "Drift"}', 'Measurement or process equipment out of calibration')
ON CONFLICT (canonical_name) DO NOTHING;

COMMIT;
