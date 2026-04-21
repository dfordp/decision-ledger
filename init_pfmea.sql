-- ============================================================================
-- DFMEA (Design Failure Mode & Effects Analysis) Schema
-- Created: 2026-04-06 | Refactored: 2026-04-20
-- Purpose: Enterprise-wide standardized DFMEA system for product design validation
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
    category VARCHAR(50) NOT NULL DEFAULT 'ELECTRICAL',
        -- Categories: ELECTRICAL, MECHANICAL, MATERIAL, DESIGN_INTERFACE, ENVIRONMENTAL, SAFETY, OTHER
    
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
-- 2. DFMEA RECORDS (Master DFMEA record per product design)
-- ============================================================================
CREATE TABLE IF NOT EXISTS pfmea_records (
    id SERIAL PRIMARY KEY,
    part_number VARCHAR(50) NOT NULL,
    part_name VARCHAR(256) NOT NULL,
    model_year VARCHAR(50),
    
    -- Metadata
    customer_name VARCHAR(256),
    process_responsibility VARCHAR(100),  -- Lead design engineer
    core_team TEXT[] DEFAULT '{}',  -- Array of design engineer names
    domain VARCHAR(100),  -- e.g., "ELECTRICAL", "MECHANICAL", "THERMAL", "INTERFACE"
    
    -- DFMEA Administration
    fmea_date_original DATE,
    fmea_revision_date DATE,
    format_number VARCHAR(50),
    status VARCHAR(20) DEFAULT 'DRAFT',
        -- Status: DRAFT, REVIEW, APPROVED, IMPLEMENTATION, CLOSED
    
    -- Design Phase & Standards
    design_phase VARCHAR(50) DEFAULT 'DETAILED',
        -- CONCEPT, PRELIMINARY, DETAILED, PRODUCTION_DESIGN
    design_standards TEXT[] DEFAULT '{}',
        -- e.g., ['IEC 61000-6-2', 'ISO 13849-1', 'JESD22-A104']
    
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
-- 3. DESIGN FUNCTIONS (Functional hierarchy within a DFMEA)
-- ============================================================================
CREATE TABLE IF NOT EXISTS process_steps (
    id SERIAL PRIMARY KEY,
    pfmea_record_id INT NOT NULL REFERENCES pfmea_records(id) ON DELETE CASCADE,
    step_number INT NOT NULL,  -- Component sequence (1, 2, 3, ...)
    
    -- Design Function Hierarchy & Intent
    step_name VARCHAR(256) NOT NULL,  -- e.g., "Copper Coil"
    function_hierarchy VARCHAR(512),  -- e.g., "Main Assembly > Electrical System > Copper Coil"
    design_intent TEXT,  -- e.g., "Generate 2.5A magnetic field at 12V DC, survive 150°C thermal cycling"
    critical_parameters JSONB DEFAULT '[]',  -- e.g., ["wire_gauge_AWG24", "turns_count_850", "insulation_class_F"]
    
    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_process_steps_pfmea_id ON process_steps(pfmea_record_id);
CREATE INDEX idx_process_steps_step_number ON process_steps(step_number);

-- ============================================================================
-- 4. DFMEA FAILURE MODE ENTRIES (Design failure modes with validation scores)
-- ============================================================================
CREATE TABLE IF NOT EXISTS pfmea_failure_mode_entries (
    id SERIAL PRIMARY KEY,
    pfmea_record_id INT NOT NULL REFERENCES pfmea_records(id) ON DELETE CASCADE,
    process_step_id INT REFERENCES process_steps(id) ON DELETE SET NULL,
    process_step_number INT,  -- Denormalized for query speed
    
    -- Failure Mode Reference
    failure_mode_id INT NOT NULL REFERENCES failure_mode_taxonomy(id),
    
    -- RPN Scoring (User Input)
    -- New Semantics: S=functional consequence, O=design margin probability, D=validation test effectiveness
    severity_user_input INT,  -- 1-10: Functional impact (loss vs degradation)
    occurrence_user_input INT,  -- 1-10: Probability given current design margins
    detection_user_input INT,  -- 1-10: Effectiveness of design validation tests
    rpn_user_calculated INT,  -- S × O × D
    
    -- RPN Scoring (Historical Suggestion)
    severity_suggested INT,
    occurrence_suggested INT,  -- Based on historical margin losses
    detection_suggested INT,  -- Based on historical validation effectiveness
    rpn_suggested INT,
    similar_incidents_count INT DEFAULT 0,
    
    -- Risk Classification
    rpn_risk_class VARCHAR(10),  -- HIGH, MED, LOW (auto-calculated)
    
    -- Context
    potential_effect TEXT,
    justification TEXT,
    source_excerpt TEXT,
    canvas_notes TEXT,
    
    -- Design Validation Test Results
    design_validation_test_results JSONB DEFAULT '{}',  
        -- e.g., {"fea_stress_margin": "15%", "thermal_sim": {"pass": true, "max_temp_c": 147},
        --        "lab_test": {"cycles": 500, "status": "PASS"}}
    
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
-- 5. DESIGN FAILURE MODE CAUSES (Root causes with design margin analysis)
-- ============================================================================
CREATE TABLE IF NOT EXISTS failure_mode_causes (
    id SERIAL PRIMARY KEY,
    fmea_entry_id INT NOT NULL REFERENCES pfmea_failure_mode_entries(id) ON DELETE CASCADE,
    cause_sequence INT DEFAULT 1,  -- Order for display (1, 2, 3, etc.)
    
    -- Cause Information
    canonical_cause VARCHAR(256) NOT NULL,
    cause_category VARCHAR(50),
        -- Design-focused categories: MATERIAL, GEOMETRY, SPECIFICATION, TOLERANCE, DESIGN_INTERFACE, ENVIRONMENTAL
    description TEXT,
    
    -- Design Margin Analysis (for O score calculation)
    design_margin_loss FLOAT,  -- e.g., 0.15 = 15% margin loss
    safety_factor_assumed FLOAT,  -- e.g., 1.5x baseline safety factor
    
    -- Semantic Search
    embedding vector(1536),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_causes_fmea_entry ON failure_mode_causes(fmea_entry_id);
CREATE INDEX idx_causes_canonical ON failure_mode_causes(canonical_cause);
CREATE INDEX idx_causes_category ON failure_mode_causes(cause_category);

-- ============================================================================
-- 6. DESIGN VALIDATION MEASURES (Testing, simulation, analysis for D score)
-- ============================================================================
CREATE TABLE IF NOT EXISTS process_controls (
    id SERIAL PRIMARY KEY,
    fmea_entry_id INT NOT NULL REFERENCES pfmea_failure_mode_entries(id) ON DELETE CASCADE,
    control_type VARCHAR(50) NOT NULL,  -- ANALYSIS, TESTING, PROTOTYPE, SIMULATION
    
    -- Validation Description
    control_description TEXT NOT NULL,  -- e.g., "ANSYS Thermal Analysis of coil-housing interface"
    test_method VARCHAR(100),  -- e.g., "FEA", "ANSYS Thermal", "Lab Thermal Cycling", "IEC 61000 EMC"
    
    -- Validation Confidence (for D score calculation)
    effectiveness_percent INT DEFAULT 90,  -- 0-100: Confidence in validation result
    
    -- Test Result Details (Phase 3 data capture)
    test_results_json JSONB DEFAULT '{}',
        -- e.g., {"fea_stress_margin": "15%", "max_temperature_c": 147, "pass_fail": "PASS"}
    
    -- Semantic Search
    embedding vector(1536),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_controls_fmea_entry ON process_controls(fmea_entry_id);
CREATE INDEX idx_controls_type ON process_controls(control_type);

-- ============================================================================
-- 7. DESIGN VALIDATION HISTORICAL DATA (Field/design level failures for trending)
-- ============================================================================
CREATE TABLE IF NOT EXISTS historical_incidents (
    id SERIAL PRIMARY KEY,
    part_number VARCHAR(50) NOT NULL,
    failure_mode_id INT NOT NULL REFERENCES failure_mode_taxonomy(id),
    
    -- Incident Details (Design-level validation findings)
    incident_date DATE NOT NULL,
    location VARCHAR(256),  -- Lab, field trial, prototype, thermal chamber, etc.
    description TEXT,
    root_cause TEXT,
    
    -- Design Margin Metrics (for O score trending)
    design_margin_loss FLOAT,  -- e.g., 0.15 = 15% design margin loss
    
    -- Impact Metrics
    impact_hours INT,  -- Hours of testing/operation before detection
    impact_units INT,  -- Number of test samples affected
    severity_actual INT,  -- Field/test-observed severity (1-10)
    
    -- Resolution
    corrective_action TEXT,
    action_completion_date DATE,
    
    -- Semantic Search
    embedding vector(1536),
    
    -- Reference
    source_document VARCHAR(256),  -- Test report, design review document, etc.
    
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
-- Sample Data Insertion (Design-focused DFMEA examples)
-- ============================================================================

-- Insert sample failure mode taxonomy (design-relevant)
INSERT INTO failure_mode_taxonomy (canonical_name, category, typical_severity_range, aliases, description)
VALUES 
    ('Resistance Drift Outside Specification', 'ELECTRICAL', '{5,8}', '{"Out-of-spec resistance", "Resistance variation", "High/low resistance"}', 'Component resistance exceeds design tolerance band'),
    ('Thermal Runaway', 'ELECTRICAL', '{8,10}', '{"Thermal failure", "Overheating", "Heat dissipation failure"}', 'Uncontrolled temperature rise leading to component failure'),
    ('Insulation Breakdown', 'ELECTRICAL', '{7,10}', '{"Dielectric failure", "Short circuit", "Insulation puncture"}', 'Loss of insulation integrity due to voltage/moisture/temperature'),
    ('Mechanical Fracture Under Load', 'MECHANICAL', '{7,10}', '{"Crack propagation", "Fatigue failure", "Component break"}', 'Structural failure due to static/fatigue loading exceeding design margin'),
    ('Thermal Interface Degradation', 'MECHANICAL', '{6,9}', '{"Thermal contact loss", "Gap formation", "Heat transfer reduction"}', 'Reduced thermal coupling between components'),
    ('Materials Property Drift', 'MATERIAL', '{4,7}', '{"Material degradation", "Property change", "Aging effect"}', 'Physical or chemical property change outside design assumptions'),
    ('Design Intent Not Met', 'DESIGN_INTERFACE', '{5,9}', '{"Function loss", "Performance degradation", "Specification not achieved"}', 'Design requirement not satisfied due to implementation gap'),
    ('Environmental Stress Exceeds Margin', 'ENVIRONMENTAL', '{5,8}', '{"Harsh environment impact", "Environmental stress", "Margin exceeded"}', 'External stress (vibration, humidity, temperature) exceeds design tolerance')
ON CONFLICT (canonical_name) DO NOTHING;

COMMIT;
