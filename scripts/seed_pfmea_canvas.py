"""
Seed PFMEA Canvas Demo Data
Populates database with demo FMEA records based on real XYZ LTD examples
"""

import os
from datetime import datetime
from app.database import execute_query, insert_and_return_id, fetch_one


def seed_demo_pfmea():
    """Populate database with demo FMEA records"""
    
    demo_parts = [
        {
            "part_name": "Horn Comp Assembly",
            "part_number": "HORN COMP.",
            "model_year": "CORE1",
            "customer": "M/S XYZ LTD.",
            "fmea_date": datetime(2004, 2, 24).date(),
            "format_number": "XYZ/F/020201",
            "process_steps": [
                {"step_number": 10, "step_name": "Coil winding", "process_function": "Wind coil wire to specifications"},
                {"step_number": 20, "step_name": "Coil enamel removing", "process_function": "Remove insulation from coil ends"},
                {"step_number": 30, "step_name": "Coil assy.", "process_function": "Assemble coil into housing"},
                {"step_number": 40, "step_name": "Soldering of capacitor wire & insulation taping", "process_function": "Solder and tape insulation"},
            ],
            "failure_modes": [
                {
                    "step_number": 10,
                    "failure_mode": "Resistance more or less",
                    "effect": "Low current lead to chattering in sound",
                    "s": 5, "o": 2, "d": 3,
                    "causes": [
                        {"canonical_cause": "Nos of turn setting not proper", "cause_category": "PROCESS_PARAM"},
                        {"canonical_cause": "Variation in resistance of wire", "cause_category": "MATERIAL"}
                    ],
                    "controls": [
                        {"control_type": "PREVENTION", "description": "Automatic counter & setting", "effectiveness": 95},
                        {"control_type": "DETECTION", "description": "Resistance checking frequency every hour", "effectiveness": 85}
                    ]
                },
                {
                    "step_number": 10,
                    "failure_mode": "High current leads to burning of coil",
                    "effect": "Coil malfunction and loss of horn function",
                    "s": 5, "o": 2, "d": 2,
                    "causes": [
                        {"canonical_cause": "Variation in resistance of wire", "cause_category": "MATERIAL"},
                        {"canonical_cause": "Wire gauge specification not met", "cause_category": "MATERIAL"}
                    ],
                    "controls": [
                        {"control_type": "PREVENTION", "description": "Wire specification verification before winding", "effectiveness": 90},
                        {"control_type": "DETECTION", "description": "Resistance checking with ohm meter", "effectiveness": 85}
                    ]
                },
                {
                    "step_number": 20,
                    "failure_mode": "No magnetic field generate",
                    "effect": "Horn will not working",
                    "s": 3, "o": 4, "d": 3,
                    "causes": [
                        {"canonical_cause": "Insulation removing chemical not effective", "cause_category": "MATERIAL"},
                        {"canonical_cause": "Quality of enamel on copper wire hard", "cause_category": "MATERIAL"}
                    ],
                    "controls": [
                        {"control_type": "PREVENTION", "description": "Enamel removing 100% ensure by visual inspection", "effectiveness": 90},
                        {"control_type": "DETECTION", "description": "Enamel removing check every spool before winding", "effectiveness": 85}
                    ]
                },
                {
                    "step_number": 30,
                    "failure_mode": "Short circuiting",
                    "effect": "Fuse blow off of vehicle",
                    "s": 4, "o": 3, "d": 3,
                    "causes": [
                        {"canonical_cause": "Nylon washer broken / crack", "cause_category": "MATERIAL"},
                        {"canonical_cause": "Wire position not O.K.", "cause_category": "PROCESS_PARAM"}
                    ],
                    "controls": [
                        {"control_type": "DETECTION", "description": "100% checking for short circuiting", "effectiveness": 95}
                    ]
                },
                {
                    "step_number": 40,
                    "failure_mode": "Due to more carbon deposition circuit not properly completed & horn not working after some time",
                    "effect": "Horn will not work after some time",
                    "s": 3, "o": 2, "d": 3,
                    "causes": [
                        {"canonical_cause": "Inside circuit of capacitor short", "cause_category": "DEFECT"},
                        {"canonical_cause": "Improper soldering technique", "cause_category": "PROCESS_PARAM"}
                    ],
                    "controls": [
                        {"control_type": "DETECTION", "description": "100% checking for short circuiting", "effectiveness": 95}
                    ]
                },
                {
                    "step_number": 40,
                    "failure_mode": "Capacitor storage capacity low",
                    "effect": "Horn performance degradation",
                    "s": 3, "o": 2, "d": 2,
                    "causes": [
                        {"canonical_cause": "Low quality capacitor component", "cause_category": "MATERIAL"},
                        {"canonical_cause": "Component aging", "cause_category": "MATERIAL"}
                    ],
                    "controls": [
                        {"control_type": "PREVENTION", "description": "Use only certified capacitor components", "effectiveness": 90},
                        {"control_type": "DETECTION", "description": "Capacitance of capacitor checked on sampling", "effectiveness": 80}
                    ]
                },
            ]
        },
        {
            "part_name": "Sand Blasting (Roller)",
            "part_number": "SAND-ROLLER",
            "model_year": "RLR-001",
            "customer": "M/S XYZ LTD.",
            "fmea_date": datetime(2004, 4, 10).date(),
            "format_number": "XYZ/F/020203",
            "process_steps": [
                {"step_number": 10, "step_name": "Sand Blasting", "process_function": "Clean surface with sand"},
                {"step_number": 20, "step_name": "Vapour Degreasing", "process_function": "Remove oils and grease"},
                {"step_number": 30, "step_name": "Pre Heating", "process_function": "Heat part before bonding"},
                {"step_number": 40, "step_name": "Bonding Agent Application", "process_function": "Apply bonding coating"},
            ],
            "failure_modes": [
                {
                    "step_number": 10,
                    "failure_mode": "Uneven surface finish",
                    "effect": "Bonding fail in subsequent operation",
                    "s": 7, "o": 3, "d": 3,
                    "causes": [
                        {"canonical_cause": "Unskilled operator", "cause_category": "OPERATOR"},
                        {"canonical_cause": "Abrasive particle size not consistent", "cause_category": "MATERIAL"}
                    ],
                    "controls": [
                        {"control_type": "PREVENTION", "description": "On-the-job training before placement", "effectiveness": 80},
                        {"control_type": "DETECTION", "description": "100% visual inspection per limit sample", "effectiveness": 90}
                    ]
                },
                {
                    "step_number": 10,
                    "failure_mode": "Over-blasting",
                    "effect": "Surface roughness exceeds specification",
                    "s": 5, "o": 2, "d": 3,
                    "causes": [
                        {"canonical_cause": "Blast pressure too high", "cause_category": "PROCESS_PARAM"},
                        {"canonical_cause": "Operator not following SOP", "cause_category": "OPERATOR"}
                    ],
                    "controls": [
                        {"control_type": "PREVENTION", "description": "Pressure gauge with set limit", "effectiveness": 90},
                        {"control_type": "DETECTION", "description": "Surface roughness check", "effectiveness": 85}
                    ]
                },
                {
                    "step_number": 30,
                    "failure_mode": "Incomplete heating",
                    "effect": "Bonding fail in subsequent operation",
                    "s": 8, "o": 2, "d": 3,
                    "causes": [
                        {"canonical_cause": "Drying time insufficient", "cause_category": "PROCESS_PARAM"},
                        {"canonical_cause": "Temperature too low", "cause_category": "PROCESS_PARAM"}
                    ],
                    "controls": [
                        {"control_type": "PREVENTION", "description": "Timer with alarm provided", "effectiveness": 90},
                        {"control_type": "PREVENTION", "description": "Temperature controller provided", "effectiveness": 90}
                    ]
                },
                {
                    "step_number": 40,
                    "failure_mode": "Bonding agent not uniform",
                    "effect": "Poor adhesion / delamination",
                    "s": 6, "o": 2, "d": 2,
                    "causes": [
                        {"canonical_cause": "Mixing not proper", "cause_category": "PROCESS_PARAM"},
                        {"canonical_cause": "Application technique poor", "cause_category": "OPERATOR"}
                    ],
                    "controls": [
                        {"control_type": "PREVENTION", "description": "Automated mixing equipment", "effectiveness": 95},
                        {"control_type": "DETECTION", "description": "Visual uniformity check", "effectiveness": 85}
                    ]
                },
            ]
        },
        {
            "part_name": "Seat Assembly",
            "part_number": "SEAT-ASS",
            "model_year": "SAT-001",
            "customer": "M/S XYZ LTD.",
            "fmea_date": datetime(2004, 5, 8).date(),
            "format_number": "XYZ/F/020204",
            "process_steps": [
                {"step_number": 10, "step_name": "Foam Cutting", "process_function": "Cut foam to specifications"},
                {"step_number": 20, "step_name": "Stitching", "process_function": "Stitch cover to foam"},
                {"step_number": 30, "step_name": "Assembly", "process_function": "Assemble complete seat"},
                {"step_number": 40, "step_name": "Quality Inspection", "process_function": "Final quality check"},
            ],
            "failure_modes": [
                {
                    "step_number": 10,
                    "failure_mode": "Incorrect foam thickness",
                    "effect": "Comfort issue - Customer complaint",
                    "s": 4, "o": 3, "d": 2,
                    "causes": [
                        {"canonical_cause": "Cutting tool not sharp", "cause_category": "EQUIPMENT"},
                        {"canonical_cause": "Foam specification variation", "cause_category": "MATERIAL"}
                    ],
                    "controls": [
                        {"control_type": "PREVENTION", "description": "Regular tool maintenance schedule", "effectiveness": 85},
                        {"control_type": "DETECTION", "description": "Thickness gauge check 100%", "effectiveness": 95}
                    ]
                },
                {
                    "step_number": 20,
                    "failure_mode": "Thread breakage during stitching",
                    "effect": "Seat cover separation",
                    "s": 5, "o": 2, "d": 3,
                    "causes": [
                        {"canonical_cause": "Thread quality poor", "cause_category": "MATERIAL"},
                        {"canonical_cause": "Machine needle wear", "cause_category": "EQUIPMENT"}
                    ],
                    "controls": [
                        {"control_type": "PREVENTION", "description": "Use certified thread material", "effectiveness": 90},
                        {"control_type": "PREVENTION", "description": "Needle replacement schedule", "effectiveness": 85}
                    ]
                },
                {
                    "step_number": 30,
                    "failure_mode": "Misalignment of components",
                    "effect": "Uneven seat surface",
                    "s": 3, "o": 3, "d": 2,
                    "causes": [
                        {"canonical_cause": "Assembly jig tolerance loose", "cause_category": "EQUIPMENT"},
                        {"canonical_cause": "Operator error", "cause_category": "OPERATOR"}
                    ],
                    "controls": [
                        {"control_type": "PREVENTION", "description": "Jig maintenance and calibration", "effectiveness": 90},
                        {"control_type": "DETECTION", "description": "100% assembly verification", "effectiveness": 95}
                    ]
                },
                {
                    "step_number": 40,
                    "failure_mode": "Surface defects missed",
                    "effect": "Defective product shipped",
                    "s": 6, "o": 2, "d": 4,
                    "causes": [
                        {"canonical_cause": "Inadequate inspection training", "cause_category": "OPERATOR"},
                        {"canonical_cause": "Poor lighting conditions", "cause_category": "PROCESS_PARAM"}
                    ],
                    "controls": [
                        {"control_type": "PREVENTION", "description": "Comprehensive inspection training", "effectiveness": 85},
                        {"control_type": "PREVENTION", "description": "Adequate lighting fixtures provided", "effectiveness": 90}
                    ]
                },
            ]
        }

    ]
    
    # Insert each part
    for part_data in demo_parts:
        print(f"Seeding {part_data['part_name']}...")
        
        # Insert PFMEA record
        part_id = insert_and_return_id("""
            INSERT INTO pfmea_records 
            (part_number, part_name, model_year, process_responsibility, 
             customer_name, status, fmea_date_original, format_number, domain)
            VALUES (%s, %s, %s, %s, %s, 'APPROVED', %s, %s, %s)
        """, (
            part_data['part_number'],
            part_data['part_name'],
            part_data['model_year'],
            "MR. A1",
            part_data['customer'],
            part_data.get('fmea_date', datetime.now().date()),
            part_data.get('format_number', f"DEMO/{part_data['part_number']}"),
            "MANUFACTURING"
        ))
        
        # Insert process steps
        step_id_map = {}
        for step in part_data['process_steps']:
            step_id = insert_and_return_id("""
                INSERT INTO process_steps (pfmea_record_id, step_number, step_name, process_function)
                VALUES (%s, %s, %s, %s)
            """, (part_id, step['step_number'], step['step_name'], step.get('process_function')))
            step_id_map[step['step_number']] = step_id
        
        # Insert failure modes and related data
        for fm_data in part_data['failure_modes']:
            # Get or create failure mode in taxonomy
            fm_name = fm_data['failure_mode']
            fm_record = fetch_one("""
                SELECT id FROM failure_mode_taxonomy WHERE canonical_name = %s
            """, (fm_name,))
            
            if fm_record:
                failure_mode_id = fm_record['id']
            else:
                failure_mode_id = insert_and_return_id("""
                    INSERT INTO failure_mode_taxonomy 
                    (canonical_name, category, version, approved_by)
                    VALUES (%s, %s, 1, %s)
                """, (fm_name, 'MANUFACTURING', 'Demo'))
            
            # Insert PFMEA entry
            step_id = step_id_map.get(fm_data['step_number'])
            entry_id = insert_and_return_id("""
                INSERT INTO pfmea_failure_mode_entries
                (pfmea_record_id, process_step_id, process_step_number, failure_mode_id,
                 potential_effect, severity_user_input, occurrence_user_input, detection_user_input)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                part_id, step_id, fm_data['step_number'], failure_mode_id, 
                fm_data['effect'],
                fm_data['s'], fm_data['o'], fm_data['d']
            ))
            
            # Insert causes
            for idx, cause in enumerate(fm_data.get('causes', []), start=1):
                execute_query("""
                    INSERT INTO failure_mode_causes
                    (fmea_entry_id, cause_sequence, canonical_cause, cause_category)
                    VALUES (%s, %s, %s, %s)
                """, (entry_id, idx, cause['canonical_cause'], cause['cause_category']))
            
            # Insert controls
            for control in fm_data.get('controls', []):
                execute_query("""
                    INSERT INTO process_controls
                    (fmea_entry_id, control_type, control_description, effectiveness_percent)
                    VALUES (%s, %s, %s, %s)
                """, (entry_id, control['control_type'], control['description'], control['effectiveness']))
        
        print(f"  ✓ {part_data['part_name']} seeded successfully")
    
    # Insert sample historical incidents
    print("\nSeeding historical incidents...")
    incidents_data = [
        {
            "part_number": "HORN COMP.",
            "failure_mode": "Short circuiting",
            "incident_date": datetime(2003, 8, 15).date(),
            "location": "Manufacturing Plant - Line A",
            "severity": 8,
            "impact_hours": 24,
            "action": "Replaced washer material with reinforced nylon, increased inspection frequency"
        },
        {
            "part_number": "HORN COMP.",
            "failure_mode": "Resistance more or less",
            "incident_date": datetime(2003, 11, 20).date(),
            "location": "Manufacturing Plant - Line B",
            "severity": 5,
            "impact_hours": 8,
            "action": "Recalibrated automatic counter, verified wire resistance specification"
        },
        {
            "part_number": "SARI-GUARD",
            "failure_mode": "Plating peel-off",
            "incident_date": datetime(2004, 1, 10).date(),
            "location": "Plating Plant - Tank 3",
            "severity": 7,
            "impact_hours": 48,
            "action": "Increased surface preparation time by 15%, installed current monitoring"
        },
        {
            "part_number": "SARI-GUARD",
            "failure_mode": "Less plating thickness",
            "incident_date": datetime(2003, 12, 5).date(),
            "location": "Plating Plant - Tank 2",
            "severity": 6,
            "impact_hours": 12,
            "action": "Adjusted bath time, recalibrated thickness measurement equipment"
        },
        {
            "part_number": "SAND-ROLLER",
            "failure_mode": "Uneven surface finish",
            "incident_date": datetime(2003, 10, 28).date(),
            "location": "Sand Blasting Shop - Station 1",
            "severity": 6,
            "impact_hours": 8,
            "action": "Provided additional operator training, standardized abrasive material"
        },
        {
            "part_number": "SAND-ROLLER",
            "failure_mode": "Incomplete heating",
            "incident_date": datetime(2003, 9, 15).date(),
            "location": "Pre-Heating Section",
            "severity": 8,
            "impact_hours": 16,
            "action": "Installed temperature controller with alarm, calibrated timer"
        },
        {
            "part_number": "SEAT-ASS",
            "failure_mode": "Thread breakage during stitching",
            "incident_date": datetime(2003, 11, 3).date(),
            "location": "Stitching Section",
            "severity": 5,
            "impact_hours": 4,
            "action": "Changed to certified thread material, increased needle replacement frequency"
        },
        {
            "part_number": "SEAT-ASS",
            "failure_mode": "Surface defects missed",
            "incident_date": datetime(2004, 1, 22).date(),
            "location": "Quality Inspection",
            "severity": 7,
            "impact_hours": 24,
            "action": "Enhanced inspection training, improved lighting in inspection area"
        },
    ]
    
    for incident in incidents_data:
        fm_record = fetch_one("""
            SELECT id FROM failure_mode_taxonomy WHERE canonical_name = %s
        """, (incident['failure_mode'],))
        
        if fm_record:
            execute_query("""
                INSERT INTO historical_incidents
                (part_number, failure_mode_id, incident_date, location, 
                 severity_actual, impact_hours, corrective_action)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                incident['part_number'],
                fm_record['id'],
                incident['incident_date'],
                incident['location'],
                incident['severity'],
                incident['impact_hours'],
                incident['action']
            ))
            print(f"  ✓ Incident: {incident['failure_mode']} ({incident['part_number']})")
    
    print("\n✅ Demo PFMEA data seeded successfully!")


if __name__ == "__main__":
    seed_demo_pfmea()
