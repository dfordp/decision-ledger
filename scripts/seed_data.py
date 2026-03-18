"""
FMEA Seed Script - Populate database with product systems, experts, and example failure modes.
Provides realistic sample data for FMEA analysis demonstrations and learning.
Based on AIAG-VDA FMEA 4.0 standard.
"""

import sys
import os
from datetime import datetime, timedelta
import json

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import (
    execute_query, insert_and_return_id, fetch_all
)
from app.embeddings import (
    generate_failure_mode_embedding,
    generate_failure_cause_embedding,
    generate_mitigation_action_embedding,
    generate_expert_skills_embedding,
    generate_system_function_embedding
)

def clear_existing_data():
    """Clear all FMEA-related data from tables"""
    print("🗑️ Clearing existing FMEA data...")
    
    tables = [
        'post_action_risk_score',
        'mitigation_action',
        'fmea_phase_checklist',
        'fmea_record',
        'historical_fmea',
        'risk_score',
        'current_control',
        'failure_cause',
        'failure_mode',
        'expert_profile',
        'organizational_standard',
        'risk_factor',
        'product_system'
    ]
    
    for table in tables:
        try:
            execute_query(f"TRUNCATE TABLE {table} CASCADE")
        except:
            execute_query(f"DELETE FROM {table}")
    
    print("✓ Database cleared\n")

def seed_product_systems():
    """Create realistic product systems across different domains"""
    print("🏭 Seeding product systems...")
    
    systems = [
        {
            'name': 'Brake System',
            'system_function': 'Prevent vehicle through controlled friction',
            'domain': 'automotive',
            'system_level': 'system',
            'scope': 'Anti-lock braking system (ABS) for passenger vehicles',
            'description': 'Safety-critical brake system preventing wheel lockup during emergency braking'
        },
        {
            'name': 'Power Steering System',
            'system_function': 'Assist driver steering control with hydraulic pressure',
            'domain': 'automotive',
            'system_level': 'system',
            'scope': 'Hydraulic power steering for light vehicles',
            'description': 'Hydraulic assist steering system with pressure regulation'
        },
        {
            'name': 'Fuel Injection System',
            'system_function': 'Deliver precise fuel quantity to engine cylinders',
            'domain': 'automotive',
            'system_level': 'subsystem',
            'scope': 'Direct injection system for gasoline engines',
            'description': 'Electronic fuel injector control and delivery system'
        },
        {
            'name': 'Pacemaker Electrode Array',
            'system_function': 'Deliver electrical stimulation to cardiac tissue',
            'domain': 'medical',
            'system_level': 'component',
            'scope': 'Cardiac rhythm management electrode system',
            'description': 'Implantable electrode arrays for pacemaker lead function'
        },
        {
            'name': 'Infusion Pump Control',
            'system_function': 'Deliver medication at controlled rate and pressure',
            'domain': 'medical',
            'system_level': 'system',
            'scope': 'Programmable IV medication delivery pump',
            'description': 'Drug delivery pump with pressure monitoring and alarms'
        },
        {
            'name': 'Industrial Motor Control',
            'system_function': 'Control speed and torque of induction motor',
            'domain': 'industrial',
            'system_level': 'subsystem',
            'scope': '15kW 3-phase induction motor controller',
            'description': 'Soft-start motor controller for factory automation'
        },
        {
            'name': 'HVAC Compressor Unit',
            'system_function': 'Compress refrigerant for heat transfer cycle',
            'domain': 'industrial',
            'system_level': 'component',
            'scope': 'Refrigeration scroll compressor assembly',
            'description': 'Oil-flooded refrigeration compressor with discharge valve'
        },
    ]
    
    system_ids = []
    for sys in systems:
        sys_id = insert_and_return_id(
            """INSERT INTO product_system 
               (name, system_function, domain, system_level, scope, description)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (sys['name'], sys['system_function'], sys['domain'], 
             sys['system_level'], sys['scope'], sys['description'])
        )
        system_ids.append(sys_id)
        print(f"  ✓ {sys['name']} ({sys['domain']})")
    
    print(f"✓ Created {len(system_ids)} product systems\n")
    return system_ids

def seed_experts():
    """Create expert profiles for team assignment"""
    print("👥 Seeding expert profiles...")
    
    experts = [
        {
            'name': 'John Smith',
            'department': 'Engineering',
            'email': 'john.smith@company.com',
            'expertise': ['product design', 'mechanical systems', 'stress analysis'],
            'contact_info': 'Ext. 1234'
        },
        {
            'name': 'Sarah Johnson',
            'department': 'Quality',
            'email': 'sarah.johnson@company.com',
            'expertise': ['process control', 'statistical analysis', 'FMEA methodology'],
            'contact_info': 'Ext. 1235'
        },
        {
            'name': 'Mike Chen',
            'department': 'Manufacturing',
            'email': 'mike.chen@company.com',
            'expertise': ['process capability', 'production equipment', 'lean manufacturing'],
            'contact_info': 'Ext. 1236'
        },
        {
            'name': 'Lisa Garcia',
            'department': 'Engineering',
            'email': 'lisa.garcia@company.com',
            'expertise': ['reliability analysis', 'requirement definition', 'systems thinking'],
            'contact_info': 'Ext. 1237'
        },
        {
            'name': 'David Brown',
            'department': 'Quality',
            'email': 'david.brown@company.com',
            'expertise': ['failure testing', 'test planning', 'data analysis'],
            'contact_info': 'Ext. 1238'
        },
        {
            'name': 'Jennifer Lee',
            'department': 'Engineering',
            'email': 'jen.lee@company.com',
            'expertise': ['electrical systems', 'control logic', 'safety critical'],
            'contact_info': 'Ext. 1239'
        },
        {
            'name': 'Robert Martinez',
            'department': 'Manufacturing',
            'email': 'robert.martinez@company.com',
            'expertise': ['equipment troubleshooting', 'worker safety', 'quality first'],
            'contact_info': 'Ext. 1240'
        },
    ]
    
    expert_ids = []
    for expert in experts:
        # Generate embedding for expert skills
        skills_emb = generate_expert_skills_embedding(
            expert['expertise'],
            expert['department'],
            expert['name']
        )
        
        # Convert embedding to PostgreSQL array format
        embedding_str = "[" + ",".join(map(str, skills_emb)) + "]"
        
        expert_id = insert_and_return_id(
            """INSERT INTO expert_profile 
               (name, department, email, expertise, skills_embedding, contact_info)
               VALUES (%s, %s, %s, %s, %s::vector, %s)""",
            (expert['name'], expert['department'], expert['email'],
             json.dumps({"skills": expert['expertise']}), embedding_str, expert['contact_info'])
        )
        expert_ids.append(expert_id)
        print(f"  ✓ {expert['name']} - {expert['department']}")
    
    print(f"✓ Created {len(expert_ids)} experts\n")
    return expert_ids

def seed_risk_factors():
    """Create organizational risk factors and standards"""
    print("📊 Seeding risk factors and standards...")
    
    # Risk factors define the S/O/D scale and guidance
    risk_factors = [
        {
            'factor_type': 'severity',
            'name': 'Severity',
            'guidance': '1=No effect, 5=Moderate effect on customer, 10=Safety hazard or non-compliance'
        },
        {
            'factor_type': 'occurrence',
            'name': 'Occurrence',
            'guidance': '1=Remote (< 0.01%), 5=Moderate (0.1-1%), 10=High (> 10%)'
        },
        {
            'factor_type': 'detection',
            'name': 'Detection',
            'guidance': '1=Certain (100% detection), 5=Moderate (50% detection), 10=Uncertain (< 10% detection)'
        },
        {
            'factor_type': 'action_priority',
            'name': 'Action Priority',
            'guidance': '1=Low priority, 5=Medium priority, 10=Urgent/Critical'
        },
    ]
    
    factor_ids = {}
    for factor in risk_factors:
        factor_id = insert_and_return_id(
            """INSERT INTO risk_factor 
               (factor_type, name, scale_min, scale_max, guidance)
               VALUES (%s, %s, %s, %s, %s)""",
            (factor['factor_type'], factor['name'], 1, 10, factor['guidance'])
        )
        factor_ids[factor['factor_type']] = factor_id
        print(f"  ✓ {factor['name']} - {factor['factor_type']}")
    
    # Organizational standards define acceptance thresholds per domain
    standards = [
        {
            'domain': 'automotive',
            'factor_type': 'severity',
            'min_acceptable': 1,
            'max_acceptable': 10,
            'notes': 'All severity levels acceptable; RPN threshold is the control'
        },
        {
            'domain': 'automotive',
            'factor_type': 'action_priority',
            'min_acceptable': 1,
            'max_acceptable': 100,  # This will be RPN-based
            'notes': 'AIAG-VDA: RPN > 100 requires action'
        },
        {
            'domain': 'medical',
            'factor_type': 'severity',
            'min_acceptable': 1,
            'max_acceptable': 10,
            'notes': 'Safety-critical domain; high severity items need strong controls'
        },
        {
            'domain': 'medical',
            'factor_type': 'action_priority',
            'min_acceptable': 1,
            'max_acceptable': 50,  # Stricter threshold
            'notes': 'ISO 14971: RPN > 50 on safety items requires action'
        },
        {
            'domain': 'industrial',
            'factor_type': 'action_priority',
            'min_acceptable': 1,
            'max_acceptable': 75,
            'notes': 'IEC 60812: Risk assessment required for critical items'
        },
    ]
    
    for standard in standards:
        if standard['factor_type'] not in factor_ids:
            print(f"  ⚠ Skipping standard for {standard['factor_type']} - factor not found")
            continue
        
        insert_and_return_id(
            """INSERT INTO organizational_standard 
               (domain, risk_factor_id, min_acceptable, max_acceptable, notes)
               VALUES (%s, %s, %s, %s, %s)""",
            (standard['domain'], factor_ids[standard['factor_type']], 
             standard['min_acceptable'], standard['max_acceptable'], standard['notes'])
        )
        print(f"  ✓ Standard: {standard['domain']} - {standard['factor_type']}")
    
    print()

def seed_brake_system_failures(system_id: int):
    """Seed brake system failure examples - placeholder for future implementation"""
    # Failure modes require linking to FMEA records
    # These should be created through the UI or via full FMEA project creation
    pass

def seed_medical_device_failures(system_id: int):
    """Seed medical device failure examples - placeholder for future implementation"""
    # Failure modes require linking to FMEA records
    # These should be created through the UI or via full FMEA project creation
    pass

def seed_mitigation_actions():
    """Seed mitigation action knowledge base - placeholder for future implementation"""
    # Mitigation actions reference failure causes which don't exist in initial seed
    # These should be created as part of FMEA analysis workflow
    pass

def seed_historical_fmea():
    """Create historical FMEA records for pattern learning"""
    print("📚 Seeding historical FMEA records...")
    
    historical = [
        {
            'product_name': 'Brake System - Model Year 2020',
            'domain': 'automotive',
            'system_function': 'Prevent vehicle movement through controlled friction',
            'failure_modes_summary': {
                'major': [
                    'Fluid leak due to seal degradation',
                    'ABS malfunction from sensor failure',
                    'Brake fade from overheating',
                    'Contamination of brake fluid',
                    'Loss of pressure in hydraulic line'
                ],
                'count': 5
            },
            'effectiveness_summary': 'Successfully identified and mitigated 95% of failure modes',
            'lessons_learned': 'Improved seal selection prevents 95% of leakage failures. Temperature-accelerated testing catches fatigue failures early.',
            'key_findings': {'critical': 'Thermal cycling is primary degradation driver', 'improvement': 'Enhanced seal geometry'}
        },
        {
            'product_name': 'Power Steering - MY2018',
            'domain': 'automotive',
            'system_function': 'Assist driver steering control with hydraulic pressure',
            'failure_modes_summary': {
                'major': [
                    'Pump cavitation during rapid steering movements',
                    'Hose burst from pressure cycling fatigue',
                    'Control valve stiction from contaminant buildup',
                    'Fluid temperature rise exceeding limits',
                    'Seal erosion from particulate wear',
                    'Filter bypass due to clogging',
                    'Bearing wear in pump assembly',
                    'Relief valve malfunction or drift'
                ],
                'count': 8
            },
            'effectiveness_summary': 'FMEA led to 40% reduction in warranty failures post-implementation',
            'lessons_learned': 'Anti-cavitation design prevents pump noise. Pressure relief valve improvements reduce burst failures by 40%.',
            'key_findings': {'critical': 'Pressure cycles cause material fatigue', 'improvement': 'Better relief valve design'}
        },
        {
            'product_name': 'Cardiac Pacemaker v2.1',
            'domain': 'medical',
            'system_function': 'Deliver electrical stimulation to cardiac tissue',
            'failure_modes_summary': {
                'major': [
                    'Electrode contact loss from passive fixation',
                    'Current lead degradation from insulation breakdown',
                    'Firmware reset causing loss of parameters',
                    'Battery depletion faster than expected',
                    'Connector corrosion from body fluid exposure',
                    'Sensing failure due to signal loss'
                ],
                'count': 6
            },
            'effectiveness_summary': 'Identified key design improvements reducing patient safety risk',
            'lessons_learned': 'Active fixation electrodes reduce contact loss from 2% to 0.1%. Hermetic sealing prevents corrosion failures.',
            'key_findings': {'critical': 'Electrode fixation is primary concern', 'improvement': 'Active fixation technology'}
        },
    ]
    
    for rec in historical:
        # Generate summary embedding
        summary_emb = generate_system_function_embedding(
            rec['system_function'],
            rec['lessons_learned'],
            rec['domain'],
            rec['product_name']
        )
        summary_embedding_str = "[" + ",".join(map(str, summary_emb)) + "]"
        
        insert_and_return_id(
            """INSERT INTO historical_fmea 
               (domain, system_function, product_name, failure_modes_summary, effectiveness_summary, 
                lessons_learned, key_findings, summary_embedding)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)""",
            (rec['domain'], rec['system_function'], rec['product_name'],
             json.dumps(rec['failure_modes_summary']), rec['effectiveness_summary'],
             rec['lessons_learned'], json.dumps(rec['key_findings']),
             summary_embedding_str)
        )
        print(f"  ✓ {rec['product_name']}")
    
    print()

def main():
    """Execute all seeding operations"""
    print("\n" + "="*60)
    print("FMEA DATABASE SEEDING")
    print("="*60 + "\n")
    
    try:
        clear_existing_data()
        
        system_ids = seed_product_systems()
        seed_experts()
        seed_risk_factors()
        
        # Seed specific failure examples for learning
        seed_brake_system_failures(system_ids[0])  # Brake System
        seed_medical_device_failures(system_ids[3])  # Pacemaker
        
        seed_mitigation_actions()
        seed_historical_fmea()
        
        print("="*60)
        print("✅ SEEDING COMPLETE")
        print("="*60)
        print("\nDatabase is ready for FMEA analysis!")
        print("\nTo create a new FMEA project:")
        print("  1. Start the application: uvicorn app.main:app --reload")
        print("  2. Open http://localhost:8000/")
        print("  3. Click 'Create New FMEA' and select a product system")
        print("\n")
        
    except Exception as e:
        print(f"\n❌ SEEDING FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
