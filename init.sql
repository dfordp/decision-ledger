-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Vendors table
CREATE TABLE vendors (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Evaluation dimensions (controlled enum)
CREATE TYPE dimension_key AS ENUM (
    'MAINTENANCE_DURATION',
    'WARRANTY_YEARS',
    'PAYMENT_TERMS',
    'LOCAL_CONTENT_PERCENT'
);

CREATE TABLE evaluation_dimension (
    id SERIAL PRIMARY KEY,
    key dimension_key UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    unit VARCHAR(20) NOT NULL
    data_type VARCHAR(16) NOT NULL DEFAULT 'NUMERIC'
);

-- Insert fixed dimensions
INSERT INTO evaluation_dimension (key, display_name, unit) VALUES
    ('MAINTENANCE_DURATION', 'Maintenance Duration', 'years'),
    ('WARRANTY_YEARS', 'Warranty Period', 'years'),
    ('PAYMENT_TERMS', 'Payment Terms', 'days'),
    ('LOCAL_CONTENT_PERCENT', 'Local Content', '%');

-- Vendor policy (bounds and flexibility per dimension)
CREATE TABLE vendor_policy (
    id SERIAL PRIMARY KEY,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    dimension_id INTEGER NOT NULL REFERENCES evaluation_dimension(id),
    domain VARCHAR(100) NOT NULL, -- 'RAIL_HVAC', 'POWER_GRID', 'GLOBAL'
    min_value DECIMAL(10, 2) NOT NULL,
    max_value DECIMAL(10, 2) NOT NULL,
    default_value DECIMAL(10, 2),
    flexibility VARCHAR(20) NOT NULL, -- 'fixed', 'negotiable', 'flexible'
    notes TEXT,
    embedding vector(1536), -- OpenAI text-embedding-3-small dimension
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(vendor_id, dimension_id, domain)
);

-- Proposals (historical submissions)
CREATE TYPE proposal_outcome AS ENUM ('WON', 'LOST', 'REJECTED');

CREATE TABLE proposals (
    id SERIAL PRIMARY KEY,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    tender_name VARCHAR(255) NOT NULL,
    domain VARCHAR(100) NOT NULL,
    outcome proposal_outcome NOT NULL,
    outcome_reason TEXT,
    submitted_at TIMESTAMP NOT NULL,
    embedding vector(1536), -- Overall proposal context embedding
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Proposal decisions (per dimension, per proposal)
CREATE TABLE proposal_decisions (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER NOT NULL REFERENCES proposals(id),
    dimension_id INTEGER NOT NULL REFERENCES evaluation_dimension(id),
    offered_value DECIMAL(10, 2) NOT NULL,
    justification TEXT NOT NULL,
    source_excerpt TEXT, -- Evidence quote
    embedding vector(1536), -- Decision context embedding
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(proposal_id, dimension_id)
);

-- Tenders (current opportunities)
CREATE TYPE tender_status AS ENUM ('OPEN', 'EVALUATING', 'DECIDED', 'CLOSED');

CREATE TABLE tenders (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(100) NOT NULL,
    year INTEGER NOT NULL,
    status tender_status DEFAULT 'OPEN',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tender requirements (per dimension, per tender)
CREATE TYPE strictness_level AS ENUM ('mandatory', 'preferred');

CREATE TABLE tender_requirements (
    id SERIAL PRIMARY KEY,
    tender_id INTEGER NOT NULL REFERENCES tenders(id),
    dimension_id INTEGER NOT NULL REFERENCES evaluation_dimension(id),
    required_value DECIMAL(10, 2) NOT NULL,
    strictness strictness_level NOT NULL,
    description TEXT,
    embedding vector(1536), -- Requirement context embedding
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tender_id, dimension_id)
);

-- Create vector indexes for similarity search (HNSW for performance)
CREATE INDEX idx_vendor_policy_embedding ON vendor_policy USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_proposals_embedding ON proposals USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_proposal_decisions_embedding ON proposal_decisions USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_tender_requirements_embedding ON tender_requirements USING hnsw (embedding vector_cosine_ops);

-- Standard indexes for foreign keys
CREATE INDEX idx_vendor_policy_vendor ON vendor_policy(vendor_id);
CREATE INDEX idx_vendor_policy_dimension ON vendor_policy(dimension_id);
CREATE INDEX idx_proposals_vendor ON proposals(vendor_id);
CREATE INDEX idx_proposal_decisions_proposal ON proposal_decisions(proposal_id);
CREATE INDEX idx_proposal_decisions_dimension ON proposal_decisions(dimension_id);
CREATE INDEX idx_tender_requirements_tender ON tender_requirements(tender_id);
CREATE INDEX idx_tender_requirements_dimension ON tender_requirements(dimension_id);

-- Useful view for querying decisions with dimension details
CREATE VIEW v_proposal_decisions_detail AS
SELECT 
    pd.*,
    p.tender_name,
    p.domain,
    p.outcome,
    p.submitted_at,
    ed.key as dimension_key,
    ed.display_name as dimension_name,
    ed.unit as dimension_unit
FROM proposal_decisions pd
JOIN proposals p ON pd.proposal_id = p.id
JOIN evaluation_dimension ed ON pd.dimension_id = ed.id;

-- View for vendor policies with dimension details
CREATE VIEW v_vendor_policy_detail AS
SELECT 
    vp.*,
    ed.key as dimension_key,
    ed.display_name as dimension_name,
    ed.unit as dimension_unit
FROM vendor_policy vp
JOIN evaluation_dimension ed ON vp.dimension_id = ed.id;

