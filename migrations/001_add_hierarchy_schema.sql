-- Migration: Add Hierarchical PLM Structure to DecisionLedger
-- File: migrations/001_add_hierarchy_schema.sql
-- Purpose: Implement Vehicle → System → Assembly → Part hierarchy with revision control

BEGIN;

-- ============================================================================
-- TABLE 1: VEHICLES (Top-level containers)
-- ============================================================================
CREATE TABLE IF NOT EXISTS vehicles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    category VARCHAR(50) NOT NULL CHECK (category IN ('automotive', 'commercial', 'industrial', 'electronics')),
    model_year INTEGER,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT unique_vehicle UNIQUE(name, model_year)
);

CREATE INDEX idx_vehicles_category ON vehicles(category);
CREATE INDEX idx_vehicles_model_year ON vehicles(model_year);

-- ============================================================================
-- TABLE 2: VEHICLE_SYSTEMS (E.g., Electrical, Powertrain)
-- ============================================================================
CREATE TABLE IF NOT EXISTS vehicle_systems (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vehicle_id UUID NOT NULL REFERENCES vehicles(id) ON DELETE CASCADE,
    system_name VARCHAR(255) NOT NULL,
    description TEXT,
    sequence_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT unique_system UNIQUE(vehicle_id, system_name)
);

CREATE INDEX idx_vehicle_systems_vehicle_id ON vehicle_systems(vehicle_id);

-- ============================================================================
-- TABLE 3: ASSEMBLIES (E.g., Horn Assembly, Seat Assembly)
-- ============================================================================
CREATE TABLE IF NOT EXISTS assemblies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    system_id UUID NOT NULL REFERENCES vehicle_systems(id) ON DELETE CASCADE,
    assembly_name VARCHAR(255) NOT NULL,
    part_number VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    part_owner_team VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_assemblies_system_id ON assemblies(system_id);
CREATE INDEX idx_assemblies_part_number ON assemblies(part_number);

-- ============================================================================
-- TABLE 4: PARTS (Leaf nodes: actuators, sensors, hardware)
-- ============================================================================
CREATE TABLE IF NOT EXISTS parts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assembly_id UUID NOT NULL REFERENCES assemblies(id) ON DELETE CASCADE,
    part_name VARCHAR(255) NOT NULL,
    part_number VARCHAR(100),
    supplier VARCHAR(255),
    material VARCHAR(100),
    cost DECIMAL(10, 2),
    mass DECIMAL(10, 3),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_parts_assembly_id ON parts(assembly_id);
CREATE INDEX idx_parts_part_number ON parts(part_number);

-- ============================================================================
-- TABLE 5: PART_REVISIONS (Version control for parts)
-- ============================================================================
CREATE TABLE IF NOT EXISTS part_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    part_id UUID NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL,
    change_type VARCHAR(50) DEFAULT 'design_change',
    previous_specs_json JSONB,
    new_specs_json JSONB NOT NULL,
    change_description TEXT,
    changed_by VARCHAR(255) DEFAULT 'system',
    change_date TIMESTAMP DEFAULT NOW(),
    approval_status VARCHAR(50) DEFAULT 'draft' CHECK (approval_status IN ('draft', 'approved', 'rejected')),
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT unique_part_revision UNIQUE(part_id, revision_number)
);

CREATE INDEX idx_part_revisions_part_id ON part_revisions(part_id);
CREATE INDEX idx_part_revisions_approval ON part_revisions(approval_status);
CREATE INDEX idx_part_revisions_change_date ON part_revisions(change_date);

-- ============================================================================
-- TABLE 6: REVISION_IMPACT_ANALYSIS (AI-generated change analysis)
-- ============================================================================
CREATE TABLE IF NOT EXISTS revision_impact_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    part_revision_id UUID NOT NULL REFERENCES part_revisions(id) ON DELETE CASCADE,
    analysis_json JSONB,
    previous_rpn_median DECIMAL(10, 2),
    new_rpn_estimate DECIMAL(10, 2),
    rpn_delta DECIMAL(10, 2),
    confidence_score INTEGER DEFAULT 0 CHECK (confidence_score >= 0 AND confidence_score <= 100),
    analysis_timestamp TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_revision_analysis_part_revision ON revision_impact_analysis(part_revision_id);
CREATE INDEX idx_revision_analysis_confidence ON revision_impact_analysis(confidence_score);

-- ============================================================================
-- MODIFICATION 1: Refactor PFMEA_RECORDS to link to part_revisions
-- ============================================================================
-- NOTE: This assumes pfmea_records table exists. If it does, add the new column.
-- If it doesn't exist yet, it will be created separately.

-- Check if pfmea_records has part_id (old structure)
ALTER TABLE pfmea_records 
ADD COLUMN IF NOT EXISTS part_revision_id UUID REFERENCES part_revisions(id);

-- Existing part_id will remain for backward compatibility during migration
-- It will be populated during the migration script

CREATE INDEX IF NOT EXISTS idx_fmea_part_revision ON pfmea_records(part_revision_id);

-- ============================================================================
-- TABLE 7: PART_VARIANTS (Track when same part used in multiple assemblies)
-- ============================================================================
CREATE TABLE IF NOT EXISTS part_variants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    primary_part_id UUID NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    variant_part_id UUID NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    similarity_score DECIMAL(3, 2),
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT different_parts CHECK (primary_part_id != variant_part_id)
);

CREATE INDEX idx_part_variants_primary ON part_variants(primary_part_id);
CREATE INDEX idx_part_variants_variant ON part_variants(variant_part_id);

-- ============================================================================
-- TABLE 8: CROSS_VEHICLE_LEARNING (Link similar parts across vehicles)
-- ============================================================================
CREATE TABLE IF NOT EXISTS cross_vehicle_learning (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_vehicle_id UUID NOT NULL REFERENCES vehicles(id),
    target_vehicle_id UUID NOT NULL REFERENCES vehicles(id),
    source_part_id UUID NOT NULL REFERENCES parts(id),
    target_part_id UUID NOT NULL REFERENCES parts(id),
    similarity_reason VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT different_vehicles CHECK (source_vehicle_id != target_vehicle_id)
);

CREATE INDEX idx_cross_learning_source ON cross_vehicle_learning(source_vehicle_id);
CREATE INDEX idx_cross_learning_target ON cross_vehicle_learning(target_vehicle_id);

-- ============================================================================
-- Helper View: Complete Hierarchy
-- ============================================================================
CREATE OR REPLACE VIEW v_complete_hierarchy AS
SELECT 
    v.id as vehicle_id,
    v.name as vehicle_name,
    v.model_year,
    v.category,
    vs.id as system_id,
    vs.system_name,
    a.id as assembly_id,
    a.assembly_name,
    a.part_number as assembly_part_number,
    p.id as part_id,
    p.part_name,
    p.part_number,
    p.supplier,
    p.material,
    COUNT(DISTINCT pr.id) as revision_count,
    MAX(pr.revision_number) as latest_revision,
    MAX(pr.change_date) as last_changed
FROM vehicles v
LEFT JOIN vehicle_systems vs ON v.id = vs.vehicle_id
LEFT JOIN assemblies a ON vs.id = a.system_id
LEFT JOIN parts p ON a.id = p.assembly_id
LEFT JOIN part_revisions pr ON p.id = pr.part_id
GROUP BY v.id, v.name, v.model_year, v.category, vs.id, vs.system_name, 
         a.id, a.assembly_name, a.part_number, p.id, p.part_name, p.part_number, 
         p.supplier, p.material;

-- ============================================================================
-- Helper View: Latest Revision Per Part
-- ============================================================================
CREATE OR REPLACE VIEW v_latest_part_revisions AS
SELECT DISTINCT ON (p.id)
    p.id as part_id,
    pr.id as revision_id,
    pr.revision_number,
    pr.change_type,
    pr.new_specs_json,
    pr.approval_status,
    pr.change_date,
    ria.analysis_json,
    ria.confidence_score
FROM parts p
LEFT JOIN part_revisions pr ON p.id = pr.part_id
LEFT JOIN revision_impact_analysis ria ON pr.id = ria.part_revision_id
ORDER BY p.id, pr.revision_number DESC;

-- ============================================================================
-- Helper Function: Get Part Hierarchy as JSON
-- ============================================================================
CREATE OR REPLACE FUNCTION get_vehicle_hierarchy(vehicle_id UUID)
RETURNS jsonb AS $$
SELECT jsonb_build_object(
    'id', v.id,
    'name', v.name,
    'model_year', v.model_year,
    'category', v.category,
    'systems', (
        SELECT COALESCE(jsonb_agg(
            jsonb_build_object(
                'id', vs.id,
                'name', vs.system_name,
                'assemblies', (
                    SELECT COALESCE(jsonb_agg(
                        jsonb_build_object(
                            'id', a.id,
                            'name', a.assembly_name,
                            'part_number', a.part_number,
                            'parts', (
                                SELECT COALESCE(jsonb_agg(
                                    jsonb_build_object(
                                        'id', p.id,
                                        'name', p.part_name,
                                        'part_number', p.part_number,
                                        'revision_count', (
                                            SELECT COUNT(*)
                                            FROM part_revisions pr2
                                            WHERE pr2.part_id = p.id
                                        )
                                    )
                                ), '[]'::jsonb)
                                FROM parts p
                                WHERE p.assembly_id = a.id
                            )
                        )
                    ), '[]'::jsonb)
                    FROM assemblies a
                    WHERE a.system_id = vs.id
                )
            )
        ), '[]'::jsonb)
        FROM vehicle_systems vs
        WHERE vs.vehicle_id = $1
    )
)
FROM vehicles v
WHERE v.id = $1;
$$ LANGUAGE SQL STABLE;

-- ============================================================================
-- Trigger: Update updated_at timestamps
-- ============================================================================
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tr_vehicles_updated BEFORE UPDATE ON vehicles
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER tr_vehicle_systems_updated BEFORE UPDATE ON vehicle_systems
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER tr_assemblies_updated BEFORE UPDATE ON assemblies
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TRIGGER tr_parts_updated BEFORE UPDATE ON parts
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

-- ============================================================================
-- Commit Transaction
-- ============================================================================
COMMIT;

-- ============================================================================
-- Post-Migration Notes:
-- ============================================================================
-- 1. Run migration with: psql -U postgres -d decisionledger -f migrations/001_add_hierarchy_schema.sql
-- 2. Then run: python scripts/migrate_parts_to_hierarchy.py
-- 3. This will populate vehicles, systems, assemblies, parts, part_revisions from existing data
-- 4. Old part_id foreign keys will remain but be unused after migration
-- 5. FMEA records will be linked to part_revision_id via migration script
