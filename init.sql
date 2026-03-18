-- ============================================================================
-- FMEA (Failure Mode and Effects Analysis) Database Schema
-- Based on AIAG-VDA FMEA 4.0 Harmonized Standard
-- ============================================================================

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- ENUMS (Controlled value lists)
-- ============================================================================

-- FMEA phase tracking
CREATE TYPE fmea_phase AS ENUM (
    'planning',
    'structural',
    'functional',
    'failure_analysis',
    'risk_analysis',
    'optimization',
    'documentation'
);

-- Failure mode types (4 basic modes)
CREATE TYPE failure_mode_type AS ENUM (
    'no_function',      -- Complete functional failure
    'partial_function', -- Only fulfills part of function
    'intermittent',     -- Works intermittently
    'unintended'        -- Unexpected function occurs
);

-- Ishikawa diagram categories (7 Ms)
CREATE TYPE ishikawa_category AS ENUM (
    'materials',
    'methods',
    'machines',
    'maintenance',
    'measurements',
    'environment',
    'management'
);

-- Control type (prevention vs. detection)
CREATE TYPE control_type AS ENUM (
    'prevention',  -- Prevents failure
    'detection'    -- Detects failure before reaching customer
);

-- FMEA status
CREATE TYPE fmea_status AS ENUM (
    'not_started',
    'in_progress',
    'under_review',
    'completed'
);

-- Action status
CREATE TYPE action_status AS ENUM (
    'open',
    'in_progress',
    'completed',
    'closed'
);

-- ============================================================================
-- CORE PRODUCT/SYSTEM TABLES
-- ============================================================================

-- Product System (the item being analyzed)
CREATE TABLE product_system (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(100) NOT NULL, -- 'automotive', 'medical', 'manufacturing', etc.
    system_level VARCHAR(50) NOT NULL, -- 'system', 'subsystem', 'component'
    description TEXT,
    system_function TEXT NOT NULL, -- Primary function of the system
    scope TEXT, -- What's included/excluded from analysis
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Risk Factors (Severity, Occurrence, Detection, Action Priority)
CREATE TABLE risk_factor (
    id SERIAL PRIMARY KEY,
    factor_type VARCHAR(50) NOT NULL, -- 'severity', 'occurrence', 'detection', 'action_priority'
    name VARCHAR(100) NOT NULL,
    scale_min INTEGER DEFAULT 1,
    scale_max INTEGER DEFAULT 10,
    description TEXT,
    guidance TEXT, -- Scoring guidance
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Organizational Standards (risk acceptance levels)
CREATE TABLE organizational_standard (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(100) NOT NULL,
    risk_factor_id INTEGER NOT NULL REFERENCES risk_factor(id),
    min_acceptable DECIMAL(5, 2),
    max_acceptable DECIMAL(5, 2),
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(domain, risk_factor_id)
);

-- ============================================================================
-- EXPERT MANAGEMENT
-- ============================================================================

-- Expert profiles (team members)
CREATE TABLE expert_profile (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    department VARCHAR(100),
    expertise JSONB, -- Array of skill tags: {"skills": ["design", "testing", "supplier", "manufacturing"]}
    skills_embedding vector(1536), -- OpenAI embedding of expertise
    contact_info TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- FMEA PROJECT MANAGEMENT
-- ============================================================================

-- FMEA Record (main container for one FMEA analysis)
CREATE TABLE fmea_record (
    id SERIAL PRIMARY KEY,
    product_system_id INTEGER NOT NULL REFERENCES product_system(id),
    project_name VARCHAR(255) NOT NULL,
    team_leads TEXT, -- JSON array of expert_profile IDs
    team_members TEXT, -- JSON array of expert_profile IDs
    current_phase fmea_phase DEFAULT 'planning',
    status fmea_status DEFAULT 'not_started',
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    created_by VARCHAR(100),
    UNIQUE(project_name)
);

-- Phase completion tracking
CREATE TABLE fmea_phase_checklist (
    id SERIAL PRIMARY KEY,
    fmea_record_id INTEGER NOT NULL REFERENCES fmea_record(id),
    phase fmea_phase NOT NULL,
    is_complete BOOLEAN DEFAULT FALSE,
    completed_at TIMESTAMP,
    notes TEXT,
    UNIQUE(fmea_record_id, phase)
);

-- ============================================================================
-- FAILURE ANALYSIS TABLES
-- ============================================================================

-- Failure Modes (potential failures)
CREATE TABLE failure_mode (
    id SERIAL PRIMARY KEY,
    fmea_record_id INTEGER NOT NULL REFERENCES fmea_record(id),
    product_system_id INTEGER NOT NULL REFERENCES product_system(id),
    mode_type failure_mode_type NOT NULL,
    description TEXT NOT NULL,
    potential_effects TEXT, -- What happens if failure occurs
    severity_score INTEGER DEFAULT 5, -- S: 1-10
    severity_justification TEXT,
    source TEXT, -- Where this failure mode came from (historical, team brainstorm, standard, etc.)
    description_embedding vector(1536), -- OpenAI embedding for similarity search
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Failure Causes (root causes of failure modes)
CREATE TABLE failure_cause (
    id SERIAL PRIMARY KEY,
    failure_mode_id INTEGER NOT NULL REFERENCES failure_mode(id),
    cause_description TEXT NOT NULL,
    ishikawa_category ishikawa_category,
    occurrence_score INTEGER DEFAULT 5, -- O: 1-10
    occurrence_justification TEXT,
    cause_embedding vector(1536), -- OpenAI embedding for similarity search
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Current Controls (existing prevention and detection controls)
CREATE TABLE current_control (
    id SERIAL PRIMARY KEY,
    failure_cause_id INTEGER NOT NULL REFERENCES failure_cause(id),
    control_description TEXT NOT NULL,
    control_type control_type NOT NULL, -- prevention or detection
    detection_score INTEGER DEFAULT 5, -- D: 1-10
    detection_justification TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- RISK CALCULATION & OPTIMIZATION TABLES
-- ============================================================================

-- Risk Scores (calculated S × O × D = RPN or Action Priority)
CREATE TABLE risk_score (
    id SERIAL PRIMARY KEY,
    failure_cause_id INTEGER NOT NULL UNIQUE REFERENCES failure_cause(id),
    severity INTEGER NOT NULL, -- S
    occurrence INTEGER NOT NULL, -- O
    detection INTEGER NOT NULL, -- D
    rpn INTEGER GENERATED ALWAYS AS (severity * occurrence * detection) STORED, -- Risk Priority Number
    action_priority VARCHAR(50), -- 'high', 'medium', 'low' (AIAG-VDA AP classification)
    is_current_state BOOLEAN DEFAULT TRUE, -- Mark as current (vs. post-action)
    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Mitigation Actions (proposed improvements)
CREATE TABLE mitigation_action (
    id SERIAL PRIMARY KEY,
    failure_cause_id INTEGER NOT NULL REFERENCES failure_cause(id),
    action_description TEXT NOT NULL,
    action_type VARCHAR(50), -- 'prevention', 'detection', 'both'
    responsibility VARCHAR(100), -- Name/team responsible
    target_date DATE,
    status action_status DEFAULT 'open',
    action_embedding vector(1536), -- For similarity search with historical actions
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Post-Action Risk Scores (after mitigation measures)
CREATE TABLE post_action_risk_score (
    id SERIAL PRIMARY KEY,
    mitigation_action_id INTEGER NOT NULL REFERENCES mitigation_action(id),
    failure_cause_id INTEGER NOT NULL REFERENCES failure_cause(id),
    new_severity INTEGER,
    new_occurrence INTEGER,
    new_detection INTEGER,
    new_rpn INTEGER GENERATED ALWAYS AS (new_severity * new_occurrence * new_detection) STORED,
    new_action_priority VARCHAR(50),
    effectiveness_rating INTEGER, -- 1-10 how effective was action
    effectiveness_notes TEXT,
    estimated_cost DECIMAL(10, 2),
    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- HISTORICAL LEARNING
-- ============================================================================

-- Historical FMEA records (for AI learning and pattern matching)
CREATE TABLE historical_fmea (
    id SERIAL PRIMARY KEY,
    fmea_record_id INTEGER REFERENCES fmea_record(id), -- Link to original
    domain VARCHAR(100) NOT NULL,
    system_function TEXT NOT NULL,
    product_name VARCHAR(255),
    failure_modes_summary JSONB, -- Aggregated failure info
    mitigation_actions_summary JSONB, -- Aggregated actions
    effectiveness_summary TEXT, -- How successful was the FMEA
    lessons_learned TEXT, -- AI-generated insights
    key_findings JSONB, -- Important patterns
    summary_embedding vector(1536), -- For similarity search
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- INDEXES (Vector + Standard)
-- ============================================================================

-- Vector indexes for similarity search (HNSW)
CREATE INDEX idx_failure_mode_embedding ON failure_mode USING hnsw (description_embedding vector_cosine_ops);
CREATE INDEX idx_failure_cause_embedding ON failure_cause USING hnsw (cause_embedding vector_cosine_ops);
CREATE INDEX idx_mitigation_action_embedding ON mitigation_action USING hnsw (action_embedding vector_cosine_ops);
CREATE INDEX idx_expert_skills_embedding ON expert_profile USING hnsw (skills_embedding vector_cosine_ops);
CREATE INDEX idx_historical_fmea_embedding ON historical_fmea USING hnsw (summary_embedding vector_cosine_ops);

-- Standard indexes for foreign keys and lookups
CREATE INDEX idx_failure_mode_fmea ON failure_mode(fmea_record_id);
CREATE INDEX idx_failure_cause_mode ON failure_cause(failure_mode_id);
CREATE INDEX idx_current_control_cause ON current_control(failure_cause_id);
CREATE INDEX idx_risk_score_cause ON risk_score(failure_cause_id);
CREATE INDEX idx_mitigation_action_cause ON mitigation_action(failure_cause_id);
CREATE INDEX idx_post_action_action ON post_action_risk_score(mitigation_action_id);
CREATE INDEX idx_post_action_cause ON post_action_risk_score(failure_cause_id);
CREATE INDEX idx_fmea_phase_checklist ON fmea_phase_checklist(fmea_record_id);
CREATE INDEX idx_fmea_record_system ON fmea_record(product_system_id);
CREATE INDEX idx_fmea_record_status ON fmea_record(status);
CREATE INDEX idx_organizational_standard_domain ON organizational_standard(domain);

-- ============================================================================
-- VIEWS (Useful queries)
-- ============================================================================

-- Complete failure analysis view (failure mode + causes + controls + risk)
CREATE VIEW v_failure_analysis AS
SELECT 
    fm.id as failure_mode_id,
    fm.description as failure_mode,
    fm.mode_type,
    fm.severity_score as s,
    fc.id as failure_cause_id,
    fc.cause_description,
    fc.ishikawa_category,
    fc.occurrence_score as o,
    cc.id as control_id,
    cc.control_description,
    cc.control_type,
    cc.detection_score as d,
    rs.rpn,
    rs.action_priority,
    frec.project_name,
    frec.current_phase,
    frec.status
FROM failure_mode fm
LEFT JOIN failure_cause fc ON fm.id = fc.failure_mode_id
LEFT JOIN current_control cc ON fc.id = cc.failure_cause_id
LEFT JOIN risk_score rs ON fc.id = rs.failure_cause_id
LEFT JOIN fmea_record frec ON fm.fmea_record_id = frec.id
WHERE rs.is_current_state = TRUE;

-- Mitigation actions with impact view
CREATE VIEW v_mitigation_impact AS
SELECT 
    ma.id as action_id,
    ma.action_description,
    fc.cause_description,
    fm.description as failure_mode,
    rs.rpn as current_rpn,
    rs.action_priority,
    pars.new_rpn,
    pars.new_action_priority,
    pars.effectiveness_rating,
    ma.status,
    ma.target_date,
    ma.responsibility
FROM mitigation_action ma
LEFT JOIN failure_cause fc ON ma.failure_cause_id = fc.id
LEFT JOIN failure_mode fm ON fc.failure_mode_id = fm.id
LEFT JOIN risk_score rs ON fc.id = rs.failure_cause_id
LEFT JOIN post_action_risk_score pars ON ma.id = pars.mitigation_action_id;

-- FMEA progress view
CREATE VIEW v_fmea_progress AS
SELECT 
    frec.id,
    frec.project_name,
    ps.name as product_system,
    frec.current_phase,
    frec.status,
    COUNT(DISTINCT fm.id) as total_failure_modes,
    COUNT(DISTINCT fc.id) as total_causes,
    COUNT(DISTINCT ma.id) as total_actions,
    COUNT(DISTINCT CASE WHEN ma.status = 'completed' THEN ma.id END) as completed_actions,
    frec.created_at,
    frec.completed_at
FROM fmea_record frec
LEFT JOIN product_system ps ON frec.product_system_id = ps.id
LEFT JOIN failure_mode fm ON frec.id = fm.fmea_record_id
LEFT JOIN failure_cause fc ON fm.id = fc.failure_mode_id
LEFT JOIN mitigation_action ma ON fc.id = ma.failure_cause_id
GROUP BY frec.id, frec.project_name, ps.name, frec.current_phase, frec.status, frec.created_at, frec.completed_at;

-- ============================================================================
-- SEED DATA (Sample FMEA - Automotive Brake System)
-- ============================================================================

-- Insert sample product system
INSERT INTO product_system (name, domain, system_level, description, system_function, scope) VALUES
    ('Automotive Brake System', 'automotive', 'system',
     'Hydraulic disc brake system with ABS for passenger vehicle',
     'Provide controlled deceleration and stopping of the vehicle under all operating conditions',
     'Includes brake pedal, master cylinder, brake fluid, hoses, calipers, pads, rotors, ABS module, sensors, and parking brake. Excludes wheel assembly and suspension.');

-- Insert risk factors (Severity, Occurrence, Detection)
INSERT INTO risk_factor (factor_type, name, scale_min, scale_max, description, guidance) VALUES
    ('severity', 'Severity', 1, 10, 'Impact if failure reaches customer or production',
     '1=No hazard, 10=Safety-critical (injury/death threat)'),
    ('occurrence', 'Occurrence', 1, 10, 'How likely is the failure to occur',
     '1=Rarely/never, 10=Frequently/very likely'),
    ('detection', 'Detection', 1, 10, 'Ability to detect before production/customer',
     '1=Always detected, 10=Never detected');

-- Insert organizational standards (acceptable thresholds)
INSERT INTO organizational_standard (domain, risk_factor_id, min_acceptable, max_acceptable, notes) VALUES
    ('automotive', 1, 1, 10, 'Severity threshold applies across all severities'),
    ('automotive', 2, 1, 10, 'Occurrence threshold varies by severity'),
    ('automotive', 3, 1, 10, 'Detection threshold varies by severity');

-- Insert expert profiles
INSERT INTO expert_profile (name, email, department, expertise, contact_info) VALUES
    ('John Smith', 'john.smith@company.com', 'Design Engineering', 
     '{"skills": ["design", "hydraulics", "CAD", "simulation"]}', 'Ext. 1001'),
    ('Sarah Johnson', 'sarah.johnson@company.com', 'Quality & Testing',
     '{"skills": ["testing", "validation", "ABS", "sensors"]}', 'Ext. 1002'),
    ('Mike Chen', 'mike.chen@company.com', 'Manufacturing',
     '{"skills": ["manufacturing", "assembly", "quality", "supplier"]}', 'Ext. 1003'),
    ('Lisa Brown', 'lisa.brown@company.com', 'Systems Engineering',
     '{"skills": ["systems", "integration", "requirements", "standards"]}', 'Ext. 1004');

-- Insert FMEA record
INSERT INTO fmea_record (product_system_id, project_name, team_leads, team_members, current_phase, status, description, created_by) VALUES
    (1, 'Brake System DFMEA - Phase 1', '[1, 2]', '[1, 2, 3, 4]', 'planning', 'in_progress',
     'Design FMEA for automotive brake system - 2026 model year', 'admin');

-- Insert failure modes (sample data from brake system)
INSERT INTO failure_mode (fmea_record_id, product_system_id, mode_type, description, potential_effects, severity_score, source) VALUES
    (1, 1, 'no_function', 'Master cylinder internal leakage', 'Loss of braking pressure, increased stopping distance, complete brake failure', 9, 'historical_failure_data'),
    (1, 1, 'partial_function', 'Brake caliper piston stuck', 'Uneven braking, vehicle pull, reduced braking efficiency', 8, 'field_complaint'),
    (1, 1, 'intermittent', 'ABS module fails to activate', 'Wheel lock, loss of traction control, skidding on wet surfaces', 9, 'safety_review'),
    (1, 1, 'no_function', 'Brake fluid boiling (vapor lock)', 'Sudden brake failure under high temperature, pedal goes to floor', 10, 'thermal_analysis');

-- Insert failure causes
INSERT INTO failure_cause (failure_mode_id, cause_description, ishikawa_category, occurrence_score) VALUES
    (1, 'Seal wear, poor material compatibility', 'materials', 3),
    (2, 'Corrosion from moisture, salt exposure', 'environment', 4),
    (2, 'Improper caliper maintenance', 'maintenance', 2),
    (3, 'Sensor contamination, wiring issue', 'measurements', 4),
    (4, 'Low boiling point fluid, overheating', 'materials', 2);

-- Insert current controls
INSERT INTO current_control (failure_cause_id, control_description, control_type, detection_score) VALUES
    (1, 'Seal material validation, pressure testing', 'prevention', 4),
    (2, 'Corrosion testing, dust seals', 'prevention', 5),
    (3, 'Post-production inspection', 'detection', 3),
    (4, 'Self-diagnostics, redundancy', 'detection', 3),
    (5, 'Fluid specification (DOT 4), thermal testing', 'prevention', 5);

-- Insert risk scores
INSERT INTO risk_score (failure_cause_id, severity, occurrence, detection, action_priority, is_current_state) VALUES
    (1, 9, 3, 4, 'high', TRUE),  -- RPN = 108
    (2, 8, 4, 5, 'high', TRUE),  -- RPN = 160
    (3, 8, 2, 3, 'medium', TRUE), -- RPN = 48
    (4, 9, 4, 3, 'high', TRUE),  -- RPN = 108 (not calculated yet, approx)
    (5, 10, 2, 5, 'high', TRUE); -- RPN = 100

-- Insert sample mitigation actions
INSERT INTO mitigation_action (failure_cause_id, action_description, action_type, responsibility, target_date, status) VALUES
    (1, 'Use higher-grade seal material, add redundancy', 'prevention', 'John Smith', '2026-06-30', 'in_progress'),
    (2, 'Improve sealing, add corrosion-resistant coating', 'prevention', 'Mike Chen', '2026-07-15', 'open'),
    (4, 'Improve sensor shielding, add redundancy', 'prevention', 'Sarah Johnson', '2026-08-30', 'open'),
    (5, 'Improve cooling system, transition to DOT 5.1', 'prevention', 'John Smith', '2026-09-15', 'open');

