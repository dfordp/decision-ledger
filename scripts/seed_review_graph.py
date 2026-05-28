"""
Seed script for ReviewGraph engineering review intelligence.
Generates deterministic revision comparison dataset from HORN-HSG-2705 drawing family.

Revisions:
- R1: Initial design with incomplete specifications
- R2: Evolved design with added features but validation gaps
- R3: Approved manufacturing baseline with complete specifications

Process:
1. Extract dimensions from each revision
2. Classify dimension criticality
3. Apply deterministic validation rules
4. Generate revision deltas (R1→R2→R3)
5. Create engineering review sessions
6. Populate evidence graph relationships
"""

import sys
import os
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import execute_query, fetch_one, fetch_all, insert_and_return_id
from psycopg2.extras import Json

# ============================================================================
# DIMENSION DEFINITIONS
# ============================================================================

R1_DIMENSIONS = {
    'body-height': {'value': 101.9, 'tolerance': None, 'unit': 'mm', 'criticality': 'HIGH'},
    'upper-horizontal-reference': {'value': 56.6, 'tolerance': None, 'unit': 'mm', 'criticality': 'HIGH'},
    'hole-horizontal-position': {'value': 51.4, 'tolerance': None, 'unit': 'mm', 'criticality': 'SAFETY_CRITICAL'},
    'flange-vertical-offset': {'value': 86.9, 'tolerance': None, 'unit': 'mm', 'criticality': 'HIGH'},
    'overall-height': {'value': 152.1, 'tolerance': None, 'unit': 'mm', 'criticality': 'HIGH'},
    'bottom-offset': {'value': 33, 'tolerance': None, 'unit': 'mm', 'criticality': 'MEDIUM'},
    'overall-width': {'value': 77.5, 'tolerance': None, 'unit': 'mm', 'criticality': 'HIGH'},
    'left-mounting-hole-diameter': {'value': 13, 'tolerance': None, 'unit': 'mm', 'criticality': 'SAFETY_CRITICAL'},
    'right-mounting-hole-diameter': {'value': 12, 'tolerance': None, 'unit': 'mm', 'criticality': 'SAFETY_CRITICAL'},
    'sheet-thickness': {'value': 1.5, 'tolerance': None, 'unit': 'mm', 'criticality': 'SAFETY_CRITICAL'},
}

R2_DIMENSIONS = {
    'centre-cutout-diameter': {'value': 18.1, 'tolerance': None, 'unit': 'mm', 'criticality': 'HIGH'},
    'hole-horizontal-position': {'value': 51.4, 'tolerance': None, 'unit': 'mm', 'criticality': 'SAFETY_CRITICAL'},
    'lower-feature-reference': {'value': 31.5, 'tolerance': None, 'unit': 'mm', 'criticality': 'SAFETY_CRITICAL'},
    'left-mounting-hole-diameter': {'value': 13, 'tolerance': None, 'unit': 'mm', 'criticality': 'SAFETY_CRITICAL'},
    'right-mounting-hole-diameter': {'value': 12, 'tolerance': None, 'unit': 'mm', 'criticality': 'SAFETY_CRITICAL'},
    'flange-vertical-offset': {'value': 86.9, 'tolerance': None, 'unit': 'mm', 'criticality': 'HIGH'},
    'overall-height': {'value': 152.1, 'tolerance': None, 'unit': 'mm', 'criticality': 'HIGH'},
    'upper-horizontal-reference': {'value': 78.9, 'tolerance': None, 'unit': 'mm', 'criticality': 'HIGH'},
    'body-height': {'value': 101.9, 'tolerance': None, 'unit': 'mm', 'criticality': 'HIGH'},
    'bottom-offset': {'value': 33, 'tolerance': None, 'unit': 'mm', 'criticality': 'MEDIUM'},
    'overall-width': {'value': 77.5, 'tolerance': None, 'unit': 'mm', 'criticality': 'HIGH'},
}

R3_DIMENSIONS = {
    'body-height': {'value': 101.9, 'tolerance': '±0.3', 'unit': 'mm', 'criticality': 'HIGH'},
    'upper-horizontal-reference': {'value': 78.9, 'tolerance': '±0.2', 'unit': 'mm', 'criticality': 'HIGH'},
    'hole-horizontal-position': {'value': 38.3, 'tolerance': '±0.1', 'unit': 'mm', 'criticality': 'SAFETY_CRITICAL'},
    'lower-feature-reference': {'value': 31.5, 'tolerance': '±0.1', 'unit': 'mm', 'criticality': 'SAFETY_CRITICAL'},
    'slot-width': {'value': 22.1, 'tolerance': '+0.05/-0.0', 'unit': 'mm', 'criticality': 'SAFETY_CRITICAL'},
    'left-mounting-hole-diameter': {'value': 13, 'tolerance': '+0.11/-0.0', 'unit': 'mm', 'criticality': 'SAFETY_CRITICAL'},
    'right-mounting-hole-diameter': {'value': 12, 'tolerance': '+0.11/-0.0', 'unit': 'mm', 'criticality': 'SAFETY_CRITICAL'},
    'flange-vertical-offset': {'value': 42.1, 'tolerance': '±0.2', 'unit': 'mm', 'criticality': 'HIGH'},
    'overall-height': {'value': 152.1, 'tolerance': '±0.5', 'unit': 'mm', 'criticality': 'HIGH'},
    'overall-width': {'value': 77.5, 'tolerance': '±0.3', 'unit': 'mm', 'criticality': 'HIGH'},
}

# ============================================================================
# DETERMINISTIC VALIDATION RULES
# ============================================================================

VALIDATION_RULES = {
    'MISSING_THICKNESS_CALLOUT': {
        'severity': 'WARN',
        'group': 'DRAWING_COMPLETENESS',
        'description': 'Sheet thickness must be explicitly dimensioned',
    },
    'INCOMPLETE_DIMENSION_CHAIN': {
        'severity': 'WARN',
        'group': 'MANUFACTURING_FEASIBILITY',
        'description': 'Dimension chain incomplete - missing intermediate references',
    },
    'MIXED_FASTENER_INTERFACE': {
        'severity': 'WARN',
        'group': 'ASSEMBLY_INTERFACE',
        'description': 'Mixed fastener sizes without assembly compatibility documentation',
    },
    'ANNOTATION_ALIGNMENT_INCONSISTENCY': {
        'severity': 'WARN',
        'group': 'DRAWING_QUALITY',
        'description': 'Dimension annotations not consistently aligned to datum structure',
    },
    'MISSING_TOLERANCE_SPECIFICATION': {
        'severity': 'BLOCK',
        'group': 'DIMENSIONAL_CONTROL',
        'description': 'Critical dimensions lack tolerance specification for manufacturing',
    },
    'INSPECTION_TRACEABILITY_FAILURE': {
        'severity': 'BLOCK',
        'group': 'QUALITY_CONTROL',
        'description': 'Inspection points cannot be traced to dimensional requirements',
    },
    'ASSEMBLY_ALIGNMENT_RISK': {
        'severity': 'BLOCK',
        'group': 'ASSEMBLY_INTERFACE',
        'description': 'Dimensional changes affect assembly interface alignment',
    },
    'VALIDATION_REVIEW_REQUIRED': {
        'severity': 'BLOCK',
        'group': 'VALIDATION_STATUS',
        'description': 'Design revision requires engineering review before manufacturing approval',
    },
}

# ============================================================================
# SEED DATA GENERATION
# ============================================================================

def clear_existing_review_data():
    """Clear existing ReviewGraph data"""
    print("Clearing existing ReviewGraph data...")
    
    tables = [
        'engineering_review_findings',
        'engineering_review_rule_results',
        'engineering_review_items',
        'engineering_review_sessions',
        'design_revision_changes',
        'design_extracted_features',
        'design_revisions',
        'design_artifacts',
        'engineering_review_rules',
        'engineering_graph_edges',
        'engineering_graph_nodes',
    ]
    
    for table in tables:
        try:
            execute_query(f"DELETE FROM {table}")
        except Exception:
            pass
    
    print("✓ Existing ReviewGraph data cleared\n")


def seed_engineering_rules():
    """Seed deterministic validation rules"""
    print("Seeding engineering rules...")
    
    rule_ids = {}
    for rule_key, rule_data in VALIDATION_RULES.items():
        rule_id = insert_and_return_id("""
            INSERT INTO engineering_review_rules 
            (rule_key, display_name, description, severity, rule_group, enabled)
            VALUES (%s, %s, %s, %s, %s, TRUE)
        """, (
            rule_key,
            rule_key.replace('_', ' '),
            rule_data['description'],
            rule_data['severity'],
            rule_data['group'],
        ))
        rule_ids[rule_key] = rule_id
    
    print(f"✓ {len(rule_ids)} rules seeded\n")
    return rule_ids


def seed_design_artifact():
    """Seed design artifact HORN-HSG-2705"""
    print("Seeding design artifact...")
    
    artifact_id = insert_and_return_id("""
        INSERT INTO design_artifacts 
        (artifact_number, title, artifact_type, domain, supplier, material, metadata_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        'HORN-HSG-2705',
        'Sheet Metal Mounting Bracket Family',
        'ENGINEERING_DRAWING',
        'MECHANICAL_ASSEMBLY',
        'Internal Manufacturing',
        'CRCA Sheet Metal',
        Json({
            'description': 'Laser cut and bent sheet metal mounting bracket with critical assembly interfaces',
            'process': 'Laser Cut + Bend',
        }),
    ))
    
    print(f"✓ Design artifact created: {artifact_id}\n")
    return artifact_id


def seed_design_revisions(artifact_id):
    """Seed three design revisions: R1, R2, R3"""
    print("Seeding design revisions...")
    
    revisions = {}
    
    # R1: Initial design with incomplete specifications
    r1_id = insert_and_return_id("""
        INSERT INTO design_revisions
        (artifact_id, revision_code, revision_sequence, change_summary, design_data_json, approval_status)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        artifact_id,
        'R1',
        1,
        'Initial design - missing thickness callout and tolerance specifications',
        Json({
            'title': 'Sheet Metal Mounting Bracket - R1',
            'process': 'Laser Cut + Bend',
            'material': 'CRCA Sheet Metal',
            'dimensions': R1_DIMENSIONS,
            'notes': 'Missing critical annotations for manufacturing',
        }),
        'draft',
    ))
    revisions['R1'] = r1_id
    
    # R2: Evolved design with added features but validation gaps
    r2_id = insert_and_return_id("""
        INSERT INTO design_revisions
        (artifact_id, revision_code, revision_sequence, change_summary, design_data_json, approval_status)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        artifact_id,
        'R2',
        2,
        'Added centre cutout and lower feature reference - missing tolerances',
        Json({
            'title': 'Sheet Metal Mounting Bracket - R2',
            'process': 'Laser Cut + Bend',
            'material': 'CRCA Sheet Metal',
            'dimensions': R2_DIMENSIONS,
            'notes': 'Added features but lacks tolerance specification for inspection',
        }),
        'in_review',
    ))
    revisions['R2'] = r2_id
    
    # R3: Approved manufacturing baseline
    r3_id = insert_and_return_id("""
        INSERT INTO design_revisions
        (artifact_id, revision_code, revision_sequence, change_summary, design_data_json, approval_status)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        artifact_id,
        'R3',
        3,
        'Manufacturing baseline - complete tolerance specifications and assembly interfaces',
        Json({
            'title': 'Sheet Metal Mounting Bracket - R3 (APPROVED)',
            'process': 'Laser Cut + Bend',
            'material': 'CRCA Sheet Metal',
            'dimensions': R3_DIMENSIONS,
            'notes': 'Approved for manufacturing - all critical dimensions and tolerances specified',
        }),
        'approved',
    ))
    revisions['R3'] = r3_id
    
    print(f"✓ {len(revisions)} design revisions created\n")
    return revisions


def seed_extracted_features(revision_ids):
    """Seed extracted features for each revision"""
    print("Seeding extracted features...")
    
    feature_map = {
        'R1': {},
        'R2': {},
        'R3': {},
    }
    
    # R1 Features
    r1_dims = R1_DIMENSIONS
    for dim_key, dim_data in r1_dims.items():
        feature_id = insert_and_return_id("""
            INSERT INTO design_extracted_features
            (design_revision_id, feature_type, feature_key, display_name, unit, criticality, value_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            revision_ids['R1'],
            'DIMENSION',
            dim_key,
            dim_key.replace('-', ' ').title(),
            dim_data['unit'],
            dim_data['criticality'],
            Json({'value': dim_data['value']}),
        ))
        feature_map['R1'][dim_key] = feature_id
    
    # R2 Features
    r2_dims = R2_DIMENSIONS
    for dim_key, dim_data in r2_dims.items():
        feature_id = insert_and_return_id("""
            INSERT INTO design_extracted_features
            (design_revision_id, feature_type, feature_key, display_name, unit, criticality, value_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            revision_ids['R2'],
            'DIMENSION',
            dim_key,
            dim_key.replace('-', ' ').title(),
            dim_data['unit'],
            dim_data['criticality'],
            Json({'value': dim_data['value']}),
        ))
        feature_map['R2'][dim_key] = feature_id
    
    # R3 Features
    r3_dims = R3_DIMENSIONS
    for dim_key, dim_data in r3_dims.items():
        feature_id = insert_and_return_id("""
            INSERT INTO design_extracted_features
            (design_revision_id, feature_type, feature_key, display_name, unit, criticality, value_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            revision_ids['R3'],
            'DIMENSION',
            dim_key,
            dim_key.replace('-', ' ').title(),
            dim_data['unit'],
            dim_data['criticality'],
            Json({'value': dim_data['value'], 'tolerance': dim_data['tolerance']}),
        ))
        feature_map['R3'][dim_key] = feature_id
    
    print(f"✓ {sum(len(v) for v in feature_map.values())} features extracted\n")
    return feature_map


def seed_revision_changes(revision_ids):
    """Seed revision deltas: R1→R2, R2→R3"""
    print("Seeding revision changes...")
    
    change_count = 0
    
    # R2 Changes (changes from R1)
    changes_r2 = [
        ('centre-cutout-diameter', 'ADDED', None, 18.1, 'HIGH', 'Feature introduced in R2'),
        ('lower-feature-reference', 'ADDED', None, 31.5, 'HIGH', 'New reference feature in R2'),
        ('upper-horizontal-reference', 'MODIFIED', 56.6, 78.9, 'MEDIUM', 'Reference changed from 56.6 to 78.9'),
    ]
    
    for feature_key, change_type, old_val, new_val, importance, reason in changes_r2:
        execute_query("""
            INSERT INTO design_revision_changes
            (design_revision_id, change_type, feature_key, field_path, old_value, new_value, importance, deterministic_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            revision_ids['R2'],
            change_type,
            feature_key,
            'dimensions.' + feature_key,
            Json({'value': old_val}) if old_val else None,
            Json({'value': new_val}) if new_val else None,
            importance,
            reason,
        ))
        change_count += 1
    
    # R3 Changes (changes from R2)
    changes_r3 = [
        ('slot-width', 'ADDED', None, 22.1, 'HIGH', 'Slot feature added in R3 manufacturing baseline'),
        ('hole-horizontal-position', 'MODIFIED', 51.4, 38.3, 'HIGH', 'Critical: hole position adjusted for assembly'),
        ('flange-vertical-offset', 'MODIFIED', 86.9, 42.1, 'MEDIUM', 'Flange offset optimized'),
        ('left-mounting-hole-diameter', 'TOLERANCE_ADDED', 13, 13, 'HIGH', 'Tolerance +0.11/-0.0 added'),
        ('right-mounting-hole-diameter', 'TOLERANCE_ADDED', 12, 12, 'HIGH', 'Tolerance +0.11/-0.0 added'),
        ('body-height', 'TOLERANCE_ADDED', 101.9, 101.9, 'MEDIUM', 'Tolerance ±0.3 added'),
        ('upper-horizontal-reference', 'TOLERANCE_ADDED', 78.9, 78.9, 'MEDIUM', 'Tolerance ±0.2 added'),
        ('overall-height', 'TOLERANCE_ADDED', 152.1, 152.1, 'MEDIUM', 'Tolerance ±0.5 added'),
        ('overall-width', 'TOLERANCE_ADDED', 77.5, 77.5, 'MEDIUM', 'Tolerance ±0.3 added'),
    ]
    
    for feature_key, change_type, old_val, new_val, importance, reason in changes_r3:
        execute_query("""
            INSERT INTO design_revision_changes
            (design_revision_id, change_type, feature_key, field_path, old_value, new_value, importance, deterministic_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            revision_ids['R3'],
            change_type,
            feature_key,
            'dimensions.' + feature_key,
            Json({'value': old_val}) if old_val else None,
            Json({'value': new_val}) if new_val else None,
            importance,
            reason,
        ))
        change_count += 1
    
    print(f"✓ {change_count} revision changes recorded\n")


def seed_engineering_review_sessions(revision_ids, artifact_id, rule_ids):
    """Seed engineering review sessions for each revision"""
    print("Seeding engineering review sessions...")
    
    sessions = {}
    
    # R1 Review Session - IN_REVIEW with WARN findings
    r1_session_id = insert_and_return_id("""
        INSERT INTO engineering_review_sessions
        (session_number, review_type, title, status, risk_status, design_revision_id, summary_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        'RV-HORN-HSG-2705-R1-001',
        'DESIGN_REVIEW',
        'HORN-HSG-2705 R1: Initial Design Review',
        'IN_REVIEW',
        'WARN',
        revision_ids['R1'],
        Json({
            'extraction_summary': 'All 10 base dimensions extracted successfully',
            'validation_summary': 'Incomplete specifications detected - review required before manufacturing',
            'critical_findings_count': 0,
            'warning_findings_count': 4,
            'status': 'REVIEW_REQUIRED',
        }),
    ))
    sessions['R1'] = r1_session_id
    
    # R1 Review Findings
    r1_findings = [
        ('MISSING_THICKNESS_CALLOUT', 'Sheet thickness dimension present but lacks manufacturing tolerance specification', ['sheet-thickness']),
        ('INCOMPLETE_DIMENSION_CHAIN', 'Upper horizontal reference (56.6) not integrated into complete dimension chain', ['upper-horizontal-reference']),
        ('MIXED_FASTENER_INTERFACE', 'Left and right mounting holes have different diameters (13mm vs 12mm) without documented assembly compatibility', ['left-mounting-hole-diameter', 'right-mounting-hole-diameter']),
        ('ANNOTATION_ALIGNMENT_INCONSISTENCY', 'Dimension annotations not consistently positioned relative to datum features', []),
    ]
    
    for rule_key, finding_text, affected_features in r1_findings:
        rule_id = rule_ids.get(rule_key)
        execute_query("""
            INSERT INTO engineering_review_findings
            (session_id, finding_type, title, status, explanation, recommended_action)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            r1_session_id,
            'DESIGN_QUALITY',
            rule_key.replace('_', ' '),
            'WARN',
            finding_text,
            'Add tolerance callout and verify manufacturing process capability',
        ))
    
    # R2 Review Session - IN_REVIEW with BLOCK findings
    r2_session_id = insert_and_return_id("""
        INSERT INTO engineering_review_sessions
        (session_number, review_type, title, status, risk_status, design_revision_id, summary_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        'RV-HORN-HSG-2705-R2-001',
        'DESIGN_REVIEW',
        'HORN-HSG-2705 R2: Feature Addition Review',
        'IN_REVIEW',
        'BLOCK',
        revision_ids['R2'],
        Json({
            'extraction_summary': 'All 11 dimensions extracted - includes new centre cutout feature',
            'validation_summary': 'Critical tolerance and inspection gaps prevent manufacturing approval',
            'critical_findings_count': 4,
            'warning_findings_count': 0,
            'status': 'BLOCKED',
        }),
    ))
    sessions['R2'] = r2_session_id
    
    # R2 Review Findings
    r2_findings = [
        ('MISSING_TOLERANCE_SPECIFICATION', 'Critical dimensions lack tolerance specification: centre-cutout (18.1), hole-position (51.4), lower-feature (31.5), mounting holes', ['centre-cutout-diameter', 'hole-horizontal-position', 'lower-feature-reference', 'left-mounting-hole-diameter', 'right-mounting-hole-diameter']),
        ('INSPECTION_TRACEABILITY_FAILURE', 'New features (centre cutout, lower reference) cannot be inspected without tolerance specification', ['centre-cutout-diameter', 'lower-feature-reference']),
        ('ASSEMBLY_ALIGNMENT_RISK', 'Hole position (51.4) not verified against assembly interface requirements - changes from R1 unvalidated', ['hole-horizontal-position']),
        ('VALIDATION_REVIEW_REQUIRED', 'Design revision must complete engineering validation before manufacturing release', []),
    ]
    
    for rule_key, finding_text, affected_features in r2_findings:
        rule_id = rule_ids.get(rule_key)
        execute_query("""
            INSERT INTO engineering_review_findings
            (session_id, finding_type, title, status, explanation, recommended_action)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            r2_session_id,
            'VALIDATION_FAILURE',
            rule_key.replace('_', ' '),
            'BLOCK',
            finding_text,
            'Add tolerance specifications and validate against assembly requirements before manufacturing',
        ))
    
    # R3 Review Session - APPROVED with no blocking findings
    r3_session_id = insert_and_return_id("""
        INSERT INTO engineering_review_sessions
        (session_number, review_type, title, status, risk_status, design_revision_id, summary_json)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        'RV-HORN-HSG-2705-R3-001',
        'DESIGN_REVIEW',
        'HORN-HSG-2705 R3: Manufacturing Baseline (APPROVED)',
        'APPROVED',
        'SAFE',
        revision_ids['R3'],
        Json({
            'extraction_summary': 'All 10 dimensions with complete tolerance specifications extracted',
            'validation_summary': 'Complete manufacturing baseline - approved for production',
            'critical_findings_count': 0,
            'warning_findings_count': 0,
            'status': 'APPROVED_REFERENCE',
        }),
    ))
    sessions['R3'] = r3_session_id
    
    print(f"✓ {len(sessions)} engineering review sessions created\n")
    return sessions


def seed_graph_relationships(revision_ids, sessions, artifact_id):
    """Seed evidence graph relationships"""
    print("Seeding evidence graph relationships...")
    
    edge_count = 0
    
    # Create graph nodes for each revision
    node_map = {}
    for rev_code, rev_id in revision_ids.items():
        node_id = insert_and_return_id("""
            INSERT INTO engineering_graph_nodes
            (entity_id, entity_type, label, metadata_json)
            VALUES (%s, %s, %s, %s)
        """, (
            str(rev_id),
            'DESIGN_REVISION',
            f'HORN-HSG-2705-{rev_code}',
            Json({'revision_code': rev_code}),
        ))
        node_map[rev_code] = node_id
    
    # Create graph nodes for sessions
    for rev_code, session_id in sessions.items():
        node_id = insert_and_return_id("""
            INSERT INTO engineering_graph_nodes
            (entity_id, entity_type, label, metadata_json)
            VALUES (%s, %s, %s, %s)
        """, (
            str(session_id),
            'REVIEW_SESSION',
            f'Session: R{rev_code}',
            Json({'review_status': sessions[rev_code]}),
        ))
        node_map[f'session_{rev_code}'] = node_id
    
    # REVISED_FROM relationships
    execute_query("""
        INSERT INTO engineering_graph_edges
        (source_node_id, target_node_id, relationship_type, confidence, evidence_json)
        VALUES (%s, %s, %s, %s, %s)
    """, (
        node_map['R2'],
        node_map['R1'],
        'REVISED_FROM',
        100,
        Json({'change_count': 4}),
    ))
    edge_count += 1
    
    execute_query("""
        INSERT INTO engineering_graph_edges
        (source_node_id, target_node_id, relationship_type, confidence, evidence_json)
        VALUES (%s, %s, %s, %s, %s)
    """, (
        node_map['R3'],
        node_map['R2'],
        'REVISED_FROM',
        100,
        Json({'change_count': 9}),
    ))
    edge_count += 1
    
    # CONTAINS_ENTITY relationships (revision contains session)
    for rev_code in ['R1', 'R2', 'R3']:
        execute_query("""
            INSERT INTO engineering_graph_edges
            (source_node_id, target_node_id, relationship_type, confidence, evidence_json)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            node_map[rev_code],
            node_map[f'session_{rev_code}'],
            'CONTAINS_ENTITY',
            100,
            Json({}),
        ))
        edge_count += 1
    
    # APPROVED_BY relationship (R3 is baseline)
    execute_query("""
        INSERT INTO engineering_graph_edges
        (source_node_id, target_node_id, relationship_type, confidence, evidence_json)
        VALUES (%s, %s, %s, %s, %s)
    """, (
        node_map['R3'],
        node_map['R1'],
        'VALIDATES',
        100,
        Json({'baseline_status': 'APPROVED_REFERENCE'}),
    ))
    edge_count += 1
    
    execute_query("""
        INSERT INTO engineering_graph_edges
        (source_node_id, target_node_id, relationship_type, confidence, evidence_json)
        VALUES (%s, %s, %s, %s, %s)
    """, (
        node_map['R3'],
        node_map['R2'],
        'VALIDATES',
        100,
        Json({'baseline_status': 'APPROVED_REFERENCE'}),
    ))
    edge_count += 1
    
    print(f"✓ {edge_count} evidence graph relationships created\n")


def main():
    """Main seed execution"""
    print("=" * 70)
    print("ReviewGraph - HORN-HSG-2705 Deterministic Seed Dataset")
    print("=" * 70)
    print()
    
    try:
        # Clear existing data
        clear_existing_review_data()
        
        # Seed engineering rules
        rule_ids = seed_engineering_rules()
        
        # Seed design artifact and revisions
        artifact_id = seed_design_artifact()
        revision_ids = seed_design_revisions(artifact_id)
        
        # Seed extracted features
        feature_map = seed_extracted_features(revision_ids)
        
        # Seed revision changes
        seed_revision_changes(revision_ids)
        
        # Seed engineering review sessions
        sessions = seed_engineering_review_sessions(revision_ids, artifact_id, rule_ids)
        
        # Seed evidence graph relationships
        seed_graph_relationships(revision_ids, sessions, artifact_id)
        
        print("=" * 70)
        print("✓ SEEDING COMPLETE")
        print("=" * 70)
        print()
        print("Generated Dataset Summary:")
        print(f"  Artifact: HORN-HSG-2705 (Sheet Metal Mounting Bracket)")
        print(f"  Revisions: R1 (REVIEW_REQUIRED), R2 (BLOCKED), R3 (APPROVED_REFERENCE)")
        print(f"  Total Dimensions: {len(R1_DIMENSIONS) + len(R2_DIMENSIONS) + len(R3_DIMENSIONS)}")
        print(f"  Engineering Rules: {len(VALIDATION_RULES)}")
        print(f"  Review Sessions: 3")
        print(f"  Revision Changes: R1→R2 (4), R2→R3 (9)")
        print()
        print("Access the data:")
        print("  - Review Workspace: http://localhost:8000/reviews/[session-id]")
        print("  - Design Artifacts: http://localhost:8000/design/artifacts")
        print("  - Engineering Reviews: http://localhost:8000/engineering/reviews")
        print()
        
    except Exception as e:
        print(f"\n✗ Seeding failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
