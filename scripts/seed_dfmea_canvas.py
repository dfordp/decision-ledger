"""
Seed DFMEA Canvas Demo Data - Comprehensive
Populates database with Design FMEA records based on real automotive and manufacturing examples
Design-focused failure modes with design margins, validation tests, and safety factors
Includes multiple parts (Horn, Sand Blasting, Seat Assembly) for cross-part isolation testing
Generates embeddings for pgvector semantic search
"""

import os
from datetime import datetime
from psycopg2.extras import Json
from app.database import execute_query, insert_and_return_id, fetch_one

# Import embedding function
try:
    from app.embeddings import generate_embedding
    EMBEDDINGS_ENABLED = True
except ImportError:
    print("⚠️  OpenAI embeddings not available - seeding without embeddings")
    EMBEDDINGS_ENABLED = False


def safe_embed(text: str):
    """Safely generate embedding, returning Json-wrapped vector or None"""
    if not EMBEDDINGS_ENABLED or not text:
        return None
    try:
        embedding = generate_embedding(text)
        return Json(embedding)
    except Exception as e:
        print(f"    ⚠️  Embedding failed: {str(e)[:50]}")
        return None


def seed_demo_dfmea():
    """
    Populate database with comprehensive demo Design FMEA records.
    Includes multiple parts across different domains for isolation testing.
    """
    
    demo_parts = [
        {
            "part_name": "Horn Coil Assembly",
            "part_number": "HORN-COIL-001",
            "model_year": "2024-AUTO",
            "customer": "Automotive OEM",
            "fmea_date": datetime(2024, 3, 15).date(),
            "format_number": "DFMEA-ELEC-001",
            "design_phase": "DETAILED",
            "domain": "ELECTRICAL",
            "design_standards": ["IEC 61000-6-2", "ISO 13849-1", "JESD22-A104"],
            
            "design_functions": [
                {
                    "step_number": 1,
                    "step_name": "Copper Coil",
                    "function_hierarchy": "Main Assembly > Electrical System > Copper Coil",
                    "design_intent": "Generate 2.5A magnetic field at 12V DC input, survive 150°C thermal cycling",
                    "critical_parameters": ["wire_gauge_AWG24", "turns_count_850", "insulation_class_F", "resistance_4.8_ohm"]
                },
                {
                    "step_number": 2,
                    "step_name": "Coil Housing",
                    "function_hierarchy": "Main Assembly > Mechanical System > Coil Housing",
                    "design_intent": "Vibration isolation, thermal protection, environmental sealing",
                    "critical_parameters": ["wall_thickness_2mm", "material_aluminum_A380", "vent_hole_dia_3mm"]
                },
                {
                    "step_number": 3,
                    "step_name": "Thermal Interface",
                    "function_hierarchy": "Main Assembly > Thermal Interface > Coil-Housing Coupling",
                    "design_intent": "Efficient heat transfer from coil to housing under continuous load",
                    "critical_parameters": ["air_gap_0_5mm", "contact_pressure_0_3_mpa", "thermal_paste_k_0_8"]
                }
            ],
            
            "failure_modes": [
                {
                    "step_number": 1,
                    "failure_mode": "Resistance Drift Outside Specification",
                    "effect": "Insufficient current → weak magnetic field, reduced horn volume",
                    "s": 7, "o": 0, "d": 0,
                    "causes": [
                        {
                            "canonical_cause": "Wire gauge AWG26 instead of spec AWG24",
                            "cause_category": "SPECIFICATION",
                            "design_margin_loss": 0.12,
                            "safety_factor_assumed": 1.5
                        },
                        {
                            "canonical_cause": "Insulation thickness 0.5mm not 0.3mm per spec",
                            "cause_category": "TOLERANCE",
                            "design_margin_loss": 0.05,
                            "safety_factor_assumed": 1.25
                        }
                    ],
                    "validation_measures": [
                        {
                            "control_type": "SIMULATION",
                            "control_description": "ANSYS electromagnetic analysis of coil resistance with tolerance stack",
                            "test_method": "FEA Electromagnetic",
                            "effectiveness_percent": 92,
                            "test_results_json": {"fea_resistance_ohm": 4.82, "tolerance_band": "±0.1", "margin": "96%"}
                        },
                        {
                            "control_type": "TESTING",
                            "control_description": "Lab resistance measurement at temperature extremes (-10°C, +150°C)",
                            "test_method": "Lab Thermal Cycling",
                            "effectiveness_percent": 95,
                            "test_results_json": {"temp_minus10_ohm": 4.75, "temp_plus150_ohm": 4.88, "result": "PASS"}
                        },
                        {
                            "control_type": "PROTOTYPE",
                            "control_description": "Prototype bench test: DC resistance verification across 10 units",
                            "test_method": "Prototype Spot Check",
                            "effectiveness_percent": 85,
                            "test_results_json": {"units_tested": 10, "units_pass": 10, "avg_resistance_ohm": 4.79}
                        }
                    ]
                },
                {
                    "step_number": 1,
                    "failure_mode": "Thermal Runaway Under Max Load",
                    "effect": "Coil melts, complete loss of horn function, safety hazard",
                    "s": 9, "o": 0, "d": 0,
                    "causes": [
                        {
                            "canonical_cause": "Copper conductivity decreases 0.4%/°C, thermal feedback effect neglected",
                            "cause_category": "MATERIAL",
                            "design_margin_loss": 0.08,
                            "safety_factor_assumed": 1.8
                        },
                        {
                            "canonical_cause": "Coil-to-housing thermal interface not optimized, air gap effects",
                            "cause_category": "DESIGN_INTERFACE",
                            "design_margin_loss": 0.15,
                            "safety_factor_assumed": 1.5
                        }
                    ],
                    "validation_measures": [
                        {
                            "control_type": "SIMULATION",
                            "control_description": "Computational Fluid Dynamics (CFD) of coil-housing thermal coupling",
                            "test_method": "CFD Thermal",
                            "effectiveness_percent": 88,
                            "test_results_json": {"max_coil_temp_c": 142, "spec_limit_c": 150, "margin_percent": "95%"}
                        },
                        {
                            "control_type": "TESTING",
                            "control_description": "Thermal camera imaging during 60s continuous operation at 14V over-voltage",
                            "test_method": "Thermal Imaging",
                            "effectiveness_percent": 90,
                            "test_results_json": {"over_voltage_v": 14, "duration_sec": 60, "peak_temp_c": 148, "result": "PASS"}
                        },
                        {
                            "control_type": "TESTING",
                            "control_description": "Thermal endurance bench test: 2000 hours at 150°C housing temperature",
                            "test_method": "Thermal Endurance",
                            "effectiveness_percent": 92,
                            "test_results_json": {"duration_hours": 2000, "temperature_c": 150, "units_pass": 5, "units_fail": 0}
                        }
                    ]
                },
                {
                    "step_number": 1,
                    "failure_mode": "Insulation Breakdown in High-Humidity Field Condition",
                    "effect": "Short circuit between coil turns, electrical safety hazard",
                    "s": 8, "o": 0, "d": 0,
                    "causes": [
                        {
                            "canonical_cause": "Class F insulation not rated for 95% RH condensation",
                            "cause_category": "SPECIFICATION",
                            "design_margin_loss": 0.18,
                            "safety_factor_assumed": 1.3
                        },
                        {
                            "canonical_cause": "Housing vent holes allow moisture ingress under extreme humidity",
                            "cause_category": "GEOMETRY",
                            "design_margin_loss": 0.22,
                            "safety_factor_assumed": 1.4
                        }
                    ],
                    "validation_measures": [
                        {
                            "control_type": "TESTING",
                            "control_description": "IEC 61000-6-2 EMC pre-compliance testing in climate chamber",
                            "test_method": "EMC Climate Test",
                            "effectiveness_percent": 85,
                            "test_results_json": {"standard": "IEC 61000-6-2", "humidity_percent": 95, "result": "PASS"}
                        },
                        {
                            "control_type": "TESTING",
                            "control_description": "65°C / 95% RH humidity cycling test per MIL-STD-810",
                            "test_method": "Humidity Cycling",
                            "effectiveness_percent": 92,
                            "test_results_json": {"cycles": 500, "temp_c": 65, "humidity_rh": 95, "insulation_resistance_ohm": 1e8, "result": "PASS"}
                        }
                    ]
                },
                {
                    "step_number": 2,
                    "failure_mode": "Housing Crack Under Vibration",
                    "effect": "Coolant/moisture leakage, coil failure secondary",
                    "s": 6, "o": 0, "d": 0,
                    "causes": [
                        {
                            "canonical_cause": "Housing wall thickness 1.5mm below design 2mm",
                            "cause_category": "TOLERANCE",
                            "design_margin_loss": 0.09,
                            "safety_factor_assumed": 1.6
                        },
                        {
                            "canonical_cause": "Vibration amplitude at resonance frequency not damped sufficiently",
                            "cause_category": "DESIGN_INTERFACE",
                            "design_margin_loss": 0.10,
                            "safety_factor_assumed": 1.5
                        }
                    ],
                    "validation_measures": [
                        {
                            "control_type": "SIMULATION",
                            "control_description": "Modal analysis of housing structure for resonance modes",
                            "test_method": "FEA Modal",
                            "effectiveness_percent": 88,
                            "test_results_json": {"first_mode_hz": 450, "target_excitation_hz": 120, "margin": "3.75x"}
                        },
                        {
                            "control_type": "TESTING",
                            "control_description": "Sinusoidal vibration sweep 20Hz-2kHz at 2G amplitude",
                            "test_method": "Vibration Sweep",
                            "effectiveness_percent": 90,
                            "test_results_json": {"sweep_range_hz": "20-2000", "amplitude_g": 2, "units_fail": 0}
                        }
                    ]
                },
                {
                    "step_number": 3,
                    "failure_mode": "Thermal Interface Degradation",
                    "effect": "Reduced heat transfer efficiency, accelerated coil failure",
                    "s": 7, "o": 0, "d": 0,
                    "causes": [
                        {
                            "canonical_cause": "Air gap increases from 0.5mm to 1.2mm due to assembly tolerance stack-up",
                            "cause_category": "TOLERANCE",
                            "design_margin_loss": 0.11,
                            "safety_factor_assumed": 1.4
                        },
                        {
                            "canonical_cause": "Thermal paste outgasses under 150°C sustained temperature",
                            "cause_category": "MATERIAL",
                            "design_margin_loss": 0.06,
                            "safety_factor_assumed": 1.7
                        }
                    ],
                    "validation_measures": [
                        {
                            "control_type": "SIMULATION",
                            "control_description": "Thermal contact resistance modeling with Monte Carlo tolerance analysis",
                            "test_method": "CFD Tolerance",
                            "effectiveness_percent": 87,
                            "test_results_json": {"worst_case_gap_mm": 1.2, "thermal_resistance_k_w": 0.25, "margin_percent": "87%"}
                        },
                        {
                            "control_type": "TESTING",
                            "control_description": "Thermal paste thermal cycling -10 to +150°C × 500 cycles",
                            "test_method": "Thermal Cycling",
                            "effectiveness_percent": 93,
                            "test_results_json": {"cycles": 500, "temp_range": "-10 to +150C", "k_value_before": 0.8, "k_value_after": 0.78}
                        }
                    ]
                }
            ]
        },
        {
            "part_name": "Sand Blasting (Roller)",
            "part_number": "SAND-ROLLER",
            "model_year": "RLR-001",
            "customer": "M/S XYZ LTD.",
            "fmea_date": datetime(2004, 4, 10).date(),
            "format_number": "XYZ/F/020203",
            "design_phase": "MANUFACTURING",
            "domain": "MANUFACTURING",
            "design_standards": ["ISO 6105", "ASTM B117"],
            
            "design_functions": [
                {
                    "step_number": 10,
                    "step_name": "Sand Blasting",
                    "function_hierarchy": "Surface Preparation > Abrasive Blasting > Sand Media",
                    "design_intent": "Remove scale and contaminants via sand abrasion to achieve Ra 3.2-6.3 finish",
                    "critical_parameters": ["sand_type_silica", "median_particle_size_120mesh", "pressure_80psi", "nozzle_distance_150mm"]
                },
                {
                    "step_number": 20,
                    "step_name": "Vapour Degreasing",
                    "function_hierarchy": "Cleanliness > Oil Removal > Solvent Treatment",
                    "design_intent": "Remove residual oils and sand particles in zero-defect cleanroom environment",
                    "critical_parameters": ["solvent_trichloroethylene", "bath_temp_80c", "immersion_time_5min"]
                },
                {
                    "step_number": 30,
                    "step_name": "Pre Heating",
                    "function_hierarchy": "Surface Treatment > Thermal Conditioning > Pre-Cure",
                    "design_intent": "Dry surface and activate adhesion sites at elevated temperature before bonding",
                    "critical_parameters": ["temp_setpoint_120c", "duration_15min", "ramp_rate_5c_per_min"]
                },
            ],
            
            "failure_modes": [
                {
                    "step_number": 10,
                    "failure_mode": "Uneven surface finish",
                    "effect": "Bonding fail in subsequent operation, customer rejection",
                    "s": 7, "o": 3, "d": 3,
                    "causes": [
                        {
                            "canonical_cause": "Unskilled operator technique variation",
                            "cause_category": "OPERATOR",
                            "design_margin_loss": 0.14,
                            "safety_factor_assumed": 1.5
                        },
                        {
                            "canonical_cause": "Abrasive particle size not consistent (120±10 mesh)",
                            "cause_category": "MATERIAL",
                            "design_margin_loss": 0.08,
                            "safety_factor_assumed": 1.6
                        }
                    ],
                    "validation_measures": [
                        {
                            "control_type": "PREVENTION",
                            "control_description": "On-the-job training before operator placement",
                            "test_method": "Training Certification",
                            "effectiveness_percent": 80,
                            "test_results_json": {"trained_operators": 12, "certification_rate": "100%"}
                        },
                        {
                            "control_type": "DETECTION",
                            "control_description": "100% visual inspection per sample limit (Ra 3.2-6.3 gauge)",
                            "test_method": "Surface Inspection",
                            "effectiveness_percent": 90,
                            "test_results_json": {"inspection_frequency": "every_unit", "defect_detection": "100%"}
                        }
                    ]
                },
                {
                    "step_number": 10,
                    "failure_mode": "Over-blasting (surface roughness exceeds spec)",
                    "effect": "Substrate damage, reduced fatigue strength, coating adhesion compromise",
                    "s": 5, "o": 2, "d": 3,
                    "causes": [
                        {
                            "canonical_cause": "Blast pressure too high (>85 psi instead of 80 psi)",
                            "cause_category": "PROCESS_PARAM",
                            "design_margin_loss": 0.07,
                            "safety_factor_assumed": 1.8
                        },
                        {
                            "canonical_cause": "Operator not following SOP, nozzle distance <100mm",
                            "cause_category": "OPERATOR",
                            "design_margin_loss": 0.09,
                            "safety_factor_assumed": 1.5
                        }
                    ],
                    "validation_measures": [
                        {
                            "control_type": "PREVENTION",
                            "control_description": "Pressure gauge with set limit regulator (± 1 psi)",
                            "test_method": "Process Control",
                            "effectiveness_percent": 90,
                            "test_results_json": {"pressure_accuracy": "±1psi", "gauge_calibration_interval_months": 6}
                        },
                        {
                            "control_type": "DETECTION",
                            "control_description": "Surface roughness check (Profilometer Ra measurement)",
                            "test_method": "Roughness Gauge",
                            "effectiveness_percent": 85,
                            "test_results_json": {"measurement_sample_rate": "every_2_hours", "spec_range_ra": "3.2-6.3"}
                        }
                    ]
                },
                {
                    "step_number": 30,
                    "failure_mode": "Incomplete heating (surface temp <100°C)",
                    "effect": "Moisture reabsorption, bonding integrity failure in field",
                    "s": 8, "o": 2, "d": 3,
                    "causes": [
                        {
                            "canonical_cause": "Drying time insufficient (<10 min instead of 15 min spec)",
                            "cause_category": "PROCESS_PARAM",
                            "design_margin_loss": 0.10,
                            "safety_factor_assumed": 1.7
                        },
                        {
                            "canonical_cause": "Temperature setpoint too low (100°C vs 120°C design)",
                            "cause_category": "PROCESS_PARAM",
                            "design_margin_loss": 0.12,
                            "safety_factor_assumed": 1.6
                        }
                    ],
                    "validation_measures": [
                        {
                            "control_type": "PREVENTION",
                            "control_description": "Timer with alarm system (audible alert at 15 min)",
                            "test_method": "Process Timer",
                            "effectiveness_percent": 90,
                            "test_results_json": {"timer_accuracy": "±3sec", "audible_alert_tested": "yes"}
                        },
                        {
                            "control_type": "PREVENTION",
                            "control_description": "Temperature controller with PID feedback loop (±2°C)",
                            "test_method": "PID Controller",
                            "effectiveness_percent": 90,
                            "test_results_json": {"control_accuracy": "±2C", "sensor_calibration_interval_months": 12}
                        }
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
            "design_phase": "MANUFACTURING",
            "domain": "MANUFACTURING",
            "design_standards": ["ISO 1502", "FMVSS 207"],
            
            "design_functions": [
                {
                    "step_number": 10,
                    "step_name": "Foam Cutting",
                    "function_hierarchy": "Seat Cushion > Base Layer > Foam Substrate",
                    "design_intent": "Cut polyurethane foam to tolerance 25mm ± 1mm for comfort and durability",
                    "critical_parameters": ["foam_density_25kg_m3", "thickness_25mm", "blade_sharpness_>8_rockwell"]
                },
                {
                    "step_number": 20,
                    "step_name": "Stitching",
                    "function_hierarchy": "Seat Cover > Attachment > Thread Assembly",
                    "design_intent": "Secure cover to foam with stitch density 6-8 stitches/inch to prevent separation",
                    "critical_parameters": ["thread_tensile_strength_10n", "stitch_length_4mm", "needle_gauge_80_pointe"]
                },
                {
                    "step_number": 30,
                    "step_name": "Assembly",
                    "function_hierarchy": "Seat System > Frame Integration > Final Assembly",
                    "design_intent": "Mount cushion assembly to frame with ±2mm alignment for ergonomic comfort",
                    "critical_parameters": ["mounting_height_tolerance_2mm", "tilt_angle_range_15_25deg"]
                },
            ],
            
            "failure_modes": [
                {
                    "step_number": 10,
                    "failure_mode": "Incorrect foam thickness",
                    "effect": "Comfort degradation, customer complaint, warranty return",
                    "s": 4, "o": 3, "d": 2,
                    "causes": [
                        {
                            "canonical_cause": "Cutting tool blade dulled (Rockwell <5)",
                            "cause_category": "EQUIPMENT",
                            "design_margin_loss": 0.08,
                            "safety_factor_assumed": 1.6
                        },
                        {
                            "canonical_cause": "Foam specification variation batch-to-batch (24-26mm received)",
                            "cause_category": "MATERIAL",
                            "design_margin_loss": 0.06,
                            "safety_factor_assumed": 1.7
                        }
                    ],
                    "validation_measures": [
                        {
                            "control_type": "PREVENTION",
                            "control_description": "Regular tool maintenance schedule (blade replacement every 8 hrs)",
                            "test_method": "Maintenance Log",
                            "effectiveness_percent": 85,
                            "test_results_json": {"replacement_interval_hours": 8, "blade_cost": "$12"}
                        },
                        {
                            "control_type": "DETECTION",
                            "control_description": "Thickness gauge check 100% of production (digital calipers ±0.5mm)",
                            "test_method": "Gauge Inspection",
                            "effectiveness_percent": 95,
                            "test_results_json": {"inspection_rate": "100%", "gauge_accuracy": "±0.5mm"}
                        }
                    ]
                },
                {
                    "step_number": 20,
                    "failure_mode": "Thread breakage during stitching",
                    "effect": "Seat cover separation, functional failure, safety risk",
                    "s": 5, "o": 2, "d": 3,
                    "causes": [
                        {
                            "canonical_cause": "Thread quality poor or degraded (tensile <9N vs 10N spec)",
                            "cause_category": "MATERIAL",
                            "design_margin_loss": 0.07,
                            "safety_factor_assumed": 1.8
                        },
                        {
                            "canonical_cause": "Machine needle wear or deflection (needle gauge >80 pointe)",
                            "cause_category": "EQUIPMENT",
                            "design_margin_loss": 0.08,
                            "safety_factor_assumed": 1.6
                        }
                    ],
                    "validation_measures": [
                        {
                            "control_type": "PREVENTION",
                            "control_description": "Use only certified thread material with tensile test certs",
                            "test_method": "Material Cert",
                            "effectiveness_percent": 90,
                            "test_results_json": {"certified_suppliers": 2, "tensile_min_n": 10}
                        },
                        {
                            "control_type": "PREVENTION",
                            "control_description": "Needle replacement schedule every 2000 stitches",
                            "test_method": "Maintenance Log",
                            "effectiveness_percent": 85,
                            "test_results_json": {"replacement_interval_stitches": 2000, "needle_cost": "$0.50"}
                        }
                    ]
                },
                {
                    "step_number": 30,
                    "failure_mode": "Misalignment of components (>2mm offset)",
                    "effect": "Uneven seat surface, ergonomic discomfort, fit/function issues",
                    "s": 3, "o": 3, "d": 2,
                    "causes": [
                        {
                            "canonical_cause": "Assembly jig tolerance loose or frame warp (tolerance stack >2mm)",
                            "cause_category": "EQUIPMENT",
                            "design_margin_loss": 0.09,
                            "safety_factor_assumed": 1.5
                        },
                        {
                            "canonical_cause": "Operator error in positioning, inconsistent procedure",
                            "cause_category": "OPERATOR",
                            "design_margin_loss": 0.11,
                            "safety_factor_assumed": 1.4
                        }
                    ],
                    "validation_measures": [
                        {
                            "control_type": "PREVENTION",
                            "control_description": "Jig maintenance and calibration (checked monthly)",
                            "test_method": "Calibration",
                            "effectiveness_percent": 90,
                            "test_results_json": {"calibration_interval_days": 30, "tolerance_target": "±1mm"}
                        },
                        {
                            "control_type": "DETECTION",
                            "control_description": "100% assembly verification with alignment gauge",
                            "test_method": "Go/No-Go Gauge",
                            "effectiveness_percent": 95,
                            "test_results_json": {"verification_rate": "100%", "tolerance_check_2mm": "yes"}
                        }
                    ]
                },
            ]
        }
    ]
    
    # Insert each part
    for part_data in demo_parts:
        print(f"\n🔧 Seeding Design FMEA: {part_data['part_name']}...")
        
        # Generate embedding for part (for similarity search)
        part_embedding_text = f"{part_data['part_name']} {part_data['part_number']} {part_data['domain']} {' '.join(part_data.get('design_standards', []))}"
        part_embedding = safe_embed(part_embedding_text)
        
        # Insert DFMEA record with embedding
        part_id = insert_and_return_id("""
            INSERT INTO pfmea_records 
            (part_number, part_name, model_year, process_responsibility, 
             customer_name, status, fmea_date_original, format_number, domain,
             design_phase, design_standards, embedding)
            VALUES (%s, %s, %s, %s, %s, 'APPROVED', %s, %s, %s, %s, %s, %s)
        """, (
            part_data['part_number'],
            part_data['part_name'],
            part_data['model_year'],
            "Lead Design Engineer",
            part_data['customer'],
            part_data.get('fmea_date', datetime.now().date()),
            part_data.get('format_number', f"DFMEA/{part_data['part_number']}"),
            part_data.get('domain', 'ELECTRICAL'),
            part_data.get('design_phase', 'DETAILED'),
            part_data.get('design_standards', []),
            part_embedding
        ))
        print(f"  ✓ DFMEA Record created (ID: {part_id})")
        
        # Insert design functions
        step_id_map = {}
        for step in part_data['design_functions']:
            step_id = insert_and_return_id("""
                INSERT INTO process_steps 
                (pfmea_record_id, step_number, step_name, function_hierarchy, design_intent, critical_parameters)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                part_id, 
                step['step_number'], 
                step['step_name'],
                step.get('function_hierarchy'),
                step.get('design_intent'),
                Json(step.get('critical_parameters', []))
            ))
            step_id_map[step['step_number']] = step_id
            print(f"    ✓ Design Function: {step['step_name']}")
        
        # Insert failure modes with causes and validation measures
        for fm_data in part_data['failure_modes']:
            # Get or create failure mode in taxonomy
            fm_name = fm_data['failure_mode']
            fm_record = fetch_one("""
                SELECT id FROM failure_mode_taxonomy WHERE canonical_name = %s
            """, (fm_name,))
            
            if fm_record:
                failure_mode_id = fm_record['id']
            else:
                # Infer category from failure mode name
                if 'Thermal' in fm_name or 'Temperature' in fm_name or 'Heat' in fm_name:
                    category = 'ELECTRICAL'
                elif 'Crack' in fm_name or 'Fracture' in fm_name or 'Vibration' in fm_name:
                    category = 'MECHANICAL'
                elif 'Insulation' in fm_name or 'Short' in fm_name or 'Breakdown' in fm_name:
                    category = 'ELECTRICAL'
                else:
                    category = 'DESIGN_INTERFACE'
                
                # Generate embedding for failure mode taxonomy
                fm_embedding = safe_embed(f"{fm_name} {fm_data['effect']} {category}")
                
                failure_mode_id = insert_and_return_id("""
                    INSERT INTO failure_mode_taxonomy 
                    (canonical_name, category, version, approved_by, embedding)
                    VALUES (%s, %s, 1, %s, %s)
                """, (fm_name, category, 'DFMEA Demo', fm_embedding))
            
            # Insert DFMEA entry with embedding
            entry_embedding_text = f"{fm_name} {fm_data['effect']} {fm_data.get('potential_effect', 'N/A')}"
            entry_embedding = safe_embed(entry_embedding_text)
            
            step_id = step_id_map.get(fm_data['step_number'])
            # Note: o and d are 0 initially; will be populated by user edits or suggestions
            entry_id = insert_and_return_id("""
                INSERT INTO pfmea_failure_mode_entries
                (pfmea_record_id, process_step_id, process_step_number, failure_mode_id,
                 potential_effect, severity_user_input, occurrence_user_input, detection_user_input, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                part_id, step_id, fm_data['step_number'], failure_mode_id, 
                fm_data['effect'],
                fm_data['s'], fm_data['o'], fm_data['d'],
                entry_embedding
            ))
            print(f"    ✓ Failure Mode: {fm_name[:50]}...")
            
            # Insert causes with design margin data and embeddings
            for idx, cause in enumerate(fm_data.get('causes', []), start=1):
                cause_embedding = safe_embed(f"{cause['canonical_cause']} {cause['cause_category']}")
                execute_query("""
                    INSERT INTO failure_mode_causes
                    (fmea_entry_id, cause_sequence, canonical_cause, cause_category, 
                     design_margin_loss, safety_factor_assumed, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    entry_id, idx, 
                    cause['canonical_cause'], 
                    cause['cause_category'],
                    cause.get('design_margin_loss'),
                    cause.get('safety_factor_assumed'),
                    cause_embedding
                ))
            
            # Insert validation measures with embeddings
            for vm in fm_data.get('validation_measures', []):
                vm_embedding = safe_embed(f"{vm['control_type']} {vm.get('test_method', '')} {vm['control_description']}")
                execute_query("""
                    INSERT INTO process_controls
                    (fmea_entry_id, control_type, control_description, test_method,
                     effectiveness_percent, test_results_json, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    entry_id, 
                    vm['control_type'], 
                    vm['control_description'],
                    vm.get('test_method'),
                    vm.get('effectiveness_percent', 85),
                    Json(vm.get('test_results_json')),
                    vm_embedding
                ))
        
        print(f"  ✅ {part_data['part_name']} DFMEA seeded successfully!")
    
    # Insert sample historical incidents (for cross-part isolation testing)
    print("\n📋 Seeding historical incidents for isolation testing...")
    incidents_data = [
        # HORN incidents
        {
            "part_number": "HORN-COIL-001",
            "failure_mode": "Resistance Drift Outside Specification",
            "incident_date": datetime(2023, 8, 15).date(),
            "location": "Manufacturing Plant - Electrical Line A",
            "severity": 7,
            "impact_hours": 12,
            "action": "Recalibrated wire gauge measurement, verified AWG24 specification"
        },
        {
            "part_number": "HORN-COIL-001",
            "failure_mode": "Thermal Runaway Under Max Load",
            "incident_date": datetime(2023, 11, 20).date(),
            "location": "Manufacturing Plant - Thermal Testing Lab",
            "severity": 9,
            "impact_hours": 24,
            "action": "Implemented CFD thermal interface optimization, extended testing duration"
        },
        {
            "part_number": "HORN-COIL-001",
            "failure_mode": "Insulation Breakdown in High-Humidity Field Condition",
            "incident_date": datetime(2023, 12, 5).date(),
            "location": "Field Testing - Coastal Region",
            "severity": 8,
            "impact_hours": 48,
            "action": "Upgraded to Class H insulation, added internal moisture barrier"
        },
        # SAND-ROLLER incidents (Manufacturing domain)
        {
            "part_number": "SAND-ROLLER",
            "failure_mode": "Uneven surface finish",
            "incident_date": datetime(2023, 10, 28).date(),
            "location": "Sand Blasting Shop - Station 1",
            "severity": 6,
            "impact_hours": 8,
            "action": "Implemented operator training program, standardized abrasive material source"
        },
        {
            "part_number": "SAND-ROLLER",
            "failure_mode": "Over-blasting (surface roughness exceeds spec)",
            "incident_date": datetime(2023, 9, 15).date(),
            "location": "Sand Blasting Shop - Station 2",
            "severity": 5,
            "impact_hours": 6,
            "action": "Installed pressure gauge limiter at 80±1 psi, calibrated regulators"
        },
        {
            "part_number": "SAND-ROLLER",
            "failure_mode": "Incomplete heating (surface temp <100°C)",
            "incident_date": datetime(2023, 11, 10).date(),
            "location": "Pre-Heating Section",
            "severity": 8,
            "impact_hours": 16,
            "action": "Installed PID temperature controller with alarm, calibrated thermocouples"
        },
        # SEAT-ASS incidents (Manufacturing domain)
        {
            "part_number": "SEAT-ASS",
            "failure_mode": "Incorrect foam thickness",
            "incident_date": datetime(2023, 7, 22).date(),
            "location": "Foam Cutting Station - Line A",
            "severity": 4,
            "impact_hours": 4,
            "action": "Implemented blade replacement every 8 hours, added 100% thickness inspection"
        },
        {
            "part_number": "SEAT-ASS",
            "failure_mode": "Thread breakage during stitching",
            "incident_date": datetime(2023, 11, 3).date(),
            "location": "Stitching Section - Machine 3",
            "severity": 5,
            "impact_hours": 4,
            "action": "Switched to certified thread with tensile specs, increased needle replacement frequency"
        },
        {
            "part_number": "SEAT-ASS",
            "failure_mode": "Misalignment of components (>2mm offset)",
            "incident_date": datetime(2024, 1, 12).date(),
            "location": "Assembly Section - Workstation 2",
            "severity": 3,
            "impact_hours": 2,
            "action": "Recalibrated assembly jig, implemented 100% alignment verification"
        },
    ]
    
    for incident in incidents_data:
        fm_record = fetch_one("""
            SELECT id FROM failure_mode_taxonomy WHERE canonical_name = %s
        """, (incident['failure_mode'],))
        
        if fm_record:
            # Generate embedding for incident
            incident_embedding_text = f"{incident['failure_mode']} {incident['part_number']} {incident['action']}"
            incident_embedding = safe_embed(incident_embedding_text)
            
            execute_query("""
                INSERT INTO historical_incidents
                (part_number, failure_mode_id, incident_date, location, 
                 severity_actual, impact_hours, corrective_action, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                incident['part_number'],
                fm_record['id'],
                incident['incident_date'],
                incident['location'],
                incident['severity'],
                incident['impact_hours'],
                incident['action'],
                incident_embedding
            ))
            print(f"  ✓ Incident: {incident['failure_mode'][:40]}... ({incident['part_number']})")
    
    print("\n✅ Demo Design FMEA data with historical incidents seeded successfully!")


if __name__ == "__main__":
    seed_demo_dfmea()
