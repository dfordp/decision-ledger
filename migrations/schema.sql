-- filepath: d:\Projects\Development\DecisionLedger\migrations\schema.sql
-- ============================================================================
-- DecisionLedger POC Database Schema
-- ============================================================================

-- Enable pgvector extension (optional)
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- ENUMS (created first, before tables)
-- ============================================================================

CREATE TYPE dimension_enum AS ENUM (
  'MAINTENANCE_DURATION',
  'WARRANTY_YEARS',
  'RESPONSE_TIME_HOURS',
  'UPTIME_GUARANTEE',
  'SUPPORT_AVAILABILITY',
  'COMPLIANCE_LEVEL',
  'PRICE_TOLERANCE',
  'DELIVERY_WINDOW_DAYS'
);

CREATE TYPE risk_profile_enum AS ENUM (
  'conservative',
  'balanced',
  'aggressive'
);

CREATE TYPE outcome_enum AS ENUM (
  'WON',
  'LOST',
  'REJECTED'
);

CREATE TYPE nature_enum AS ENUM (
  'default',
  'conditional',
  'exception'
);

CREATE TYPE strictness_enum AS ENUM (
  'mandatory',
  'preferred'
);

CREATE TYPE flexibility_enum AS ENUM (
  'fixed',
  'conditional',
  'flexible'
);

-- ============================================================================
-- TABLES
-- ============================================================================

-- VENDORS: Core vendor entity
CREATE TABLE IF NOT EXISTS vendors (
  id SERIAL PRIMARY KEY,
  name VARCHAR(255) NOT NULL UNIQUE,
  primary_domains TEXT[] DEFAULT '{}',
  risk_profile risk_profile_enum NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE vendors IS 'Vendor entity representing a company with policies and proposal history';
COMMENT ON COLUMN vendors.primary_domains IS 'Array of domain names vendor specializes in (e.g. ["infrastructure", "cloud"])';
COMMENT ON COLUMN vendors.risk_profile IS 'Vendor approach: conservative (lower bounds), balanced (middle), aggressive (higher bounds)';

-- VENDOR_POLICY: Vendor constraints and preferences
CREATE TABLE IF NOT EXISTS vendor_policy (
  id SERIAL PRIMARY KEY,
  vendor_id INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
  dimension dimension_enum NOT NULL,
  domain VARCHAR(100) NOT NULL,
  max_value NUMERIC(10, 2) NOT NULL,
  flexibility flexibility_enum NOT NULL,
  notes TEXT,
  effective_from DATE NOT NULL DEFAULT CURRENT_DATE,
  effective_to DATE,
  embedding TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT unique_policy UNIQUE(vendor_id, dimension, domain, effective_from)
);

COMMENT ON TABLE vendor_policy IS 'Vendor policies: bounds and constraints for responding to tenders';
COMMENT ON COLUMN vendor_policy.domain IS '"GLOBAL" for all domains, or specific domain name (e.g. "infrastructure")';
COMMENT ON COLUMN vendor_policy.max_value IS 'Maximum acceptable value for this dimension in this domain';
COMMENT ON COLUMN vendor_policy.flexibility IS 'Whether policy is fixed (absolute), conditional (negotiable), or flexible (loose)';
COMMENT ON COLUMN vendor_policy.embedding IS 'Vector embedding (1536-dim) for semantic similarity search';

-- PROPOSALS: Historical vendor proposals for tenders
CREATE TABLE IF NOT EXISTS proposals (
  id SERIAL PRIMARY KEY,
  vendor_id INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
  year INTEGER NOT NULL,
  outcome outcome_enum NOT NULL,
  outcome_reason TEXT,
  proposal_summary TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE proposals IS 'Historical proposals vendor submitted: outcome + summary';
COMMENT ON COLUMN proposals.outcome_reason IS 'Why proposal won, lost, or was rejected (optional context)';

-- PROPOSAL_DECISIONS: Individual decisions made in a proposal
CREATE TABLE IF NOT EXISTS proposal_decisions (
  id SERIAL PRIMARY KEY,
  proposal_id INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
  dimension dimension_enum NOT NULL,
  value NUMERIC(10, 2) NOT NULL,
  nature nature_enum NOT NULL,
  confidence NUMERIC(3, 2),
  violation_flag BOOLEAN DEFAULT FALSE,
  source_excerpt TEXT,
  embedding TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT confidence_range CHECK (confidence >= 0 AND confidence <= 1)
);

COMMENT ON TABLE proposal_decisions IS 'Each dimension value decided in a proposal (reasoning memory)';
COMMENT ON COLUMN proposal_decisions.nature IS 'Type of decision: default (standard), conditional (depends on X), exception (broke rules)';
COMMENT ON COLUMN proposal_decisions.violation_flag IS 'TRUE if this value violated vendor policy at the time';
COMMENT ON COLUMN proposal_decisions.source_excerpt IS 'Text from proposal document supporting this decision';
COMMENT ON COLUMN proposal_decisions.embedding IS 'Vector embedding for similarity search across past decisions';

-- TENDERS: Incoming tender requests to evaluate
CREATE TABLE IF NOT EXISTS tenders (
  id SERIAL PRIMARY KEY,
  tender_name VARCHAR(255) NOT NULL,
  domain VARCHAR(100) NOT NULL,
  year INTEGER NOT NULL,
  tender_summary TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE tenders IS 'Incoming tender RFPs to evaluate and respond to';
COMMENT ON COLUMN tenders.domain IS 'Business domain of tender (e.g. "infrastructure", "cloud")';

-- TENDER_REQUIREMENTS: Individual requirements in a tender
CREATE TABLE IF NOT EXISTS tender_requirements (
  id SERIAL PRIMARY KEY,
  tender_id INTEGER NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
  dimension dimension_enum NOT NULL,
  required_value NUMERIC(10, 2) NOT NULL,
  strictness strictness_enum NOT NULL,
  embedding TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT unique_requirement UNIQUE(tender_id, dimension)
);

COMMENT ON TABLE tender_requirements IS 'Each dimension requirement in a tender (what we must respond to)';
COMMENT ON COLUMN tender_requirements.required_value IS 'Required value or minimum acceptable value for this dimension';
COMMENT ON COLUMN tender_requirements.strictness IS 'mandatory (must meet), preferred (nice to have)';
COMMENT ON COLUMN tender_requirements.embedding IS 'Vector embedding for semantic search against vendor policies and past decisions';

-- ============================================================================
-- INDEXES
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_vendor_policy_vendor_id ON vendor_policy(vendor_id);
CREATE INDEX IF NOT EXISTS idx_vendor_policy_dimension ON vendor_policy(dimension, domain);
CREATE INDEX IF NOT EXISTS idx_proposals_vendor_id ON proposals(vendor_id);
CREATE INDEX IF NOT EXISTS idx_proposal_decisions_proposal_id ON proposal_decisions(proposal_id);
CREATE INDEX IF NOT EXISTS idx_proposal_decisions_dimension ON proposal_decisions(dimension);
CREATE INDEX IF NOT EXISTS idx_tender_requirements_tender_id ON tender_requirements(tender_id);
CREATE INDEX IF NOT EXISTS idx_tender_requirements_dimension ON tender_requirements(dimension);

-- ============================================================================
-- SAMPLE DATA
-- ============================================================================

INSERT INTO vendors (name, risk_profile, primary_domains)
VALUES ('TechVendor Solutions', 'balanced', '{"infrastructure", "cloud"}')
ON CONFLICT (name) DO NOTHING;