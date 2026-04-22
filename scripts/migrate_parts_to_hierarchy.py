"""
Migration Script: Move flat parts → hierarchical structure
File: scripts/migrate_parts_to_hierarchy.py
Purpose: Populate vehicles, systems, assemblies, parts, part_revisions with existing data
"""

import json
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
from uuid import uuid4
import sys

# Database connection
def get_db_connection():
    """Connect to PostgreSQL"""
    try:
        conn = psycopg2.connect(
            dbname="decisionledger",
            user="postgres",
            password="postgres",
            host="localhost"
        )
        return conn
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        sys.exit(1)

def serialize_part_specs(part):
    """Convert part record to JSON specs"""
    return {
        "part_name": part.get('part_name'),
        "part_number": part.get('part_number'),
        "supplier": part.get('supplier'),
        "material": part.get('material'),
        "cost": float(part.get('cost')) if part.get('cost') else None,
        "mass": float(part.get('mass')) if part.get('mass') else None,
        "domain": part.get('domain'),
        "model": part.get('model')
    }

def create_vehicle(conn, name, category, model_year):
    """Create or get vehicle"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Check if exists
    cur.execute("""
        SELECT id FROM vehicles WHERE name = %s AND model_year = %s
    """, (name, model_year))
    
    result = cur.fetchone()
    if result:
        return result['id']
    
    # Create new
    vehicle_id = str(uuid4())
    cur.execute("""
        INSERT INTO vehicles (id, name, category, model_year)
        VALUES (%s, %s, %s, %s)
    """, (vehicle_id, name, category, model_year))
    
    conn.commit()
    return vehicle_id

def create_system(conn, vehicle_id, system_name):
    """Create or get vehicle system"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Check if exists
    cur.execute("""
        SELECT id FROM vehicle_systems 
        WHERE vehicle_id = %s AND system_name = %s
    """, (vehicle_id, system_name))
    
    result = cur.fetchone()
    if result:
        return result['id']
    
    # Create new
    system_id = str(uuid4())
    cur.execute("""
        INSERT INTO vehicle_systems (id, vehicle_id, system_name, description)
        VALUES (%s, %s, %s, %s)
    """, (system_id, vehicle_id, system_name, f"{system_name} System"))
    
    conn.commit()
    return system_id

def create_assembly(conn, system_id, assembly_name, part_number):
    """Create assembly"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    assembly_id = str(uuid4())
    cur.execute("""
        INSERT INTO assemblies (id, system_id, assembly_name, part_number, description)
        VALUES (%s, %s, %s, %s, %s)
    """, (assembly_id, system_id, assembly_name, part_number, f"{assembly_name} Assembly"))
    
    conn.commit()
    return assembly_id

def create_part(conn, assembly_id, part_name, supplier, material):
    """Create part"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    part_id = str(uuid4())
    cur.execute("""
        INSERT INTO parts (id, assembly_id, part_name, supplier, material)
        VALUES (%s, %s, %s, %s, %s)
    """, (part_id, assembly_id, part_name, supplier, material))
    
    conn.commit()
    return part_id

def create_baseline_revision(conn, part_id, specs_json):
    """Create revision 1 for part (baseline from existing data)"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    revision_id = str(uuid4())
    cur.execute("""
        INSERT INTO part_revisions 
        (id, part_id, revision_number, change_type, new_specs_json, 
         change_description, changed_by, approval_status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        revision_id,
        part_id,
        1,
        'baseline_migration',
        json.dumps(specs_json),
        'Migrated from legacy flat structure',
        'migration_script',
        'approved'
    ))
    
    conn.commit()
    return revision_id

def link_fmea_to_revision(conn, old_part_id, new_revision_id):
    """Update FMEA records to link to new part_revision"""
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Find all FMEA records for old part
    cur.execute("""
        SELECT id FROM fmea_records WHERE part_id = %s
    """, (old_part_id,))
    
    fmea_records = cur.fetchall()
    count = 0
    
    for record in fmea_records:
        cur.execute("""
            UPDATE fmea_records 
            SET part_revision_id = %s
            WHERE id = %s
        """, (new_revision_id, record['id']))
        count += 1
    
    conn.commit()
    return count

def migrate_parts_to_hierarchy():
    """Main migration: flat parts → hierarchical structure"""
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    print("\n" + "="*70)
    print("MIGRATION: Flat Parts → Hierarchical Structure")
    print("="*70 + "\n")
    
    # Step 1: Try to get existing parts from old flat structure
    # If the old schema doesn't exist, fall back to demo vehicles
    print("📋 Checking for existing parts...")
    try:
        cur.execute("""
            SELECT id, part_name, part_number, domain, model, supplier, material
            FROM parts
            WHERE domain IS NOT NULL OR part_name IS NOT NULL
            ORDER BY domain, part_name
        """)
        old_parts = cur.fetchall()
        if old_parts:
            print(f"   Found {len(old_parts)} existing parts\n")
        else:
            print("   No parts found. Creating demo vehicle...\n")
            create_demo_vehicle(conn)
            return
    except Exception as e:
        print(f"   ⚠️  Old flat parts table not accessible: {e}")
        print("   Creating demo vehicle instead...\n")
        conn.rollback()  # Rollback the failed transaction
        create_demo_vehicle(conn)
        return
    
    # Step 2: Group by domain (for system creation)
    domains = {}
    for part in old_parts:
        domain = part['domain'] or 'General'
        if domain not in domains:
            domains[domain] = []
        domains[domain].append(part)
    
    print(f"📦 Found {len(domains)} domains:")
    for domain in sorted(domains.keys()):
        print(f"   • {domain} ({len(domains[domain])} parts)")
    print()
    
    # Step 3: Create base vehicle (legacy container)
    print("🚗 Creating vehicle: 'Legacy System'...")
    vehicle_id = create_vehicle(conn, "Legacy System", "industrial", 2025)
    print(f"   ✓ Vehicle ID: {vehicle_id}\n")
    
    # Step 4: Migrate parts
    stats = {
        'systems_created': 0,
        'assemblies_created': 0,
        'parts_created': 0,
        'revisions_created': 0,
        'fmea_linked': 0,
        'errors': 0
    }
    
    for domain in sorted(domains.keys()):
        print(f"\n📦 Processing System: {domain}")
        
        # Create system
        system_id = create_system(conn, vehicle_id, domain)
        stats['systems_created'] += 1
        
        # Migrate each part in this domain
        for part in domains[domain]:
            try:
                # Create assembly (treat as single-item assembly for simplicity)
                assembly_id = create_assembly(
                    conn, 
                    system_id, 
                    part['part_name'],
                    part['part_number'] or f"AUTO-{part['id'][:8]}"
                )
                stats['assemblies_created'] += 1
                
                # Create part record in new structure
                new_part_id = create_part(
                    conn,
                    assembly_id,
                    part['part_name'],
                    part['supplier'] or 'Unknown',
                    part['material'] or 'Unknown'
                )
                stats['parts_created'] += 1
                
                # Create baseline revision (version 1)
                specs = serialize_part_specs(part)
                revision_id = create_baseline_revision(conn, new_part_id, specs)
                stats['revisions_created'] += 1
                
                # Link existing FMEA records to this revision
                fmea_count = link_fmea_to_revision(conn, part['id'], revision_id)
                stats['fmea_linked'] += fmea_count
                
                print(f"   ✓ {part['part_name']} → Revision 1 (FMEA: {fmea_count})")
                
            except Exception as e:
                stats['errors'] += 1
                print(f"   ❌ Error migrating {part['part_name']}: {e}")
    
    # Summary
    print("\n" + "="*70)
    print("MIGRATION SUMMARY")
    print("="*70)
    print(f"✓ Vehicle created: 1")
    print(f"✓ Systems created: {stats['systems_created']}")
    print(f"✓ Assemblies created: {stats['assemblies_created']}")
    print(f"✓ Parts created: {stats['parts_created']}")
    print(f"✓ Revisions created: {stats['revisions_created']}")
    print(f"✓ FMEA records linked: {stats['fmea_linked']}")
    if stats['errors'] > 0:
        print(f"❌ Errors: {stats['errors']}")
    print("="*70 + "\n")
    
    conn.close()

def create_demo_vehicle(conn):
    """Create demo multi-vehicle structure for testing"""
    
    print("Creating demo vehicles for testing...\n")
    
    # Check if demo vehicles already exist
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT COUNT(*) as cnt FROM vehicles WHERE name LIKE '%Honda%'")
    existing = cur.fetchone()
    if existing and existing['cnt'] > 0:
        print(f"⚠️  Demo vehicles already exist ({existing['cnt']} found). Skipping creation.\n")
        conn.close()
        return
    
    # ============================================================================
    # VEHICLE 1: 2026 Honda Civic (Automotive)
    # ============================================================================
    civic_2026_id = create_vehicle(conn, "2026 Honda Civic", "automotive", 2026)
    
    # Systems for Civic
    elec_sys = create_system(conn, civic_2026_id, "Electrical System")
    power_sys = create_system(conn, civic_2026_id, "Powertrain System")
    chassis_sys = create_system(conn, civic_2026_id, "Chassis System")
    
    # --- ELECTRICAL SYSTEM ---
    # Horn Assembly
    horn_asm = create_assembly(conn, elec_sys, "Horn Assembly", "HORN-COIL-001")
    housing_id = create_part(conn, horn_asm, "Housing", "Metal Fabricators Inc", "Aluminum")
    speaker_id = create_part(conn, horn_asm, "Horn Speaker", "Audio Dynamics", "Brass")
    coil_id = create_part(conn, horn_asm, "Electromagnetic Coil", "Electronics Ltd", "Copper Wire")
    
    housing_v1 = {"material": "Aluminum", "weight": 2.1, "cost": 45, "thermal_range": "-40 to 80°C"}
    create_baseline_revision(conn, housing_id, housing_v1)
    create_baseline_revision(conn, speaker_id, {"material": "Brass", "impedance": "8 ohms", "cost": 28})
    create_baseline_revision(conn, coil_id, {"turns": 2500, "wire_gauge": "26 AWG", "cost": 15})
    
    # Seat Assembly
    seat_asm = create_assembly(conn, elec_sys, "Seat Assembly", "SEAT-ASS-001")
    seat_frame_id = create_part(conn, seat_asm, "Seat Frame", "Seating Dynamics", "Steel")
    seat_heater_id = create_part(conn, seat_asm, "Heating Element", "Thermal Systems", "Nichrome Wire")
    seat_adjuster_id = create_part(conn, seat_asm, "Electric Adjuster Motor", "Motors Inc", "DC Motor")
    
    create_baseline_revision(conn, seat_frame_id, {"material": "Steel", "weight": 8.5, "cost": 120})
    create_baseline_revision(conn, seat_heater_id, {"wattage": 150, "coverage": "full", "cost": 45})
    create_baseline_revision(conn, seat_adjuster_id, {"voltage": "12V", "torque": "50 Nm", "cost": 65})
    
    # Lighting Assembly
    light_asm = create_assembly(conn, elec_sys, "Headlight Assembly", "HEADLIGHT-001")
    lens_id = create_part(conn, light_asm, "LED Lens", "Optics Corp", "Polycarbonate")
    led_array_id = create_part(conn, light_asm, "LED Array Module", "Light Tech", "LED")
    reflector_id = create_part(conn, light_asm, "Reflector", "Mirror Systems", "Aluminum")
    
    create_baseline_revision(conn, lens_id, {"material": "Polycarbonate", "clarity": "99%", "cost": 35})
    create_baseline_revision(conn, led_array_id, {"lumens": 3000, "color_temp": "6000K", "cost": 150})
    create_baseline_revision(conn, reflector_id, {"material": "Aluminum", "finish": "chrome", "cost": 25})
    
    # --- POWERTRAIN SYSTEM ---
    # Engine Assembly
    engine_asm = create_assembly(conn, power_sys, "Engine Assembly", "ENGINE-2026")
    cylinder_id = create_part(conn, engine_asm, "Cylinder Block", "Casting Foundry", "Cast Iron")
    piston_id = create_part(conn, engine_asm, "Piston", "Precision Parts", "Aluminum Alloy")
    gasket_id = create_part(conn, engine_asm, "Head Gasket", "Sealing Solutions", "Composite")
    
    create_baseline_revision(conn, cylinder_id, {"material": "Cast Iron", "displacement": "1.5L", "cost": 200})
    create_baseline_revision(conn, piston_id, {"material": "Aluminum", "bore": "73mm", "cost": 45})
    create_baseline_revision(conn, gasket_id, {"material": "Composite", "thickness": "1.5mm", "cost": 25})
    
    # Transmission Assembly
    trans_asm = create_assembly(conn, power_sys, "Transmission Assembly", "TRANS-CVT-2026")
    belt_id = create_part(conn, trans_asm, "Drive Belt", "Belt Systems", "Rubber")
    pulley_id = create_part(conn, trans_asm, "Primary Pulley", "Pulley Corp", "Steel")
    fluid_id = create_part(conn, trans_asm, "CVT Fluid", "Lubricants Inc", "Synthetic")
    
    create_baseline_revision(conn, belt_id, {"material": "Rubber", "width": "25mm", "cost": 35})
    create_baseline_revision(conn, pulley_id, {"material": "Steel", "diameter": "110mm", "cost": 55})
    create_baseline_revision(conn, fluid_id, {"viscosity": "CVT", "capacity": "3.7L", "cost": 28})
    
    # --- CHASSIS SYSTEM ---
    # Suspension Assembly
    susp_asm = create_assembly(conn, chassis_sys, "Front Suspension", "SUSP-FRONT-2026")
    spring_id = create_part(conn, susp_asm, "Coil Spring", "Spring Systems", "Steel")
    damper_id = create_part(conn, susp_asm, "Shock Damper", "Damper Tech", "Steel")
    control_arm_id = create_part(conn, susp_asm, "Control Arm", "Chassis Parts", "Aluminum")
    
    create_baseline_revision(conn, spring_id, {"material": "Steel", "rate": "25 N/mm", "cost": 85})
    create_baseline_revision(conn, damper_id, {"type": "Telescopic", "travel": "150mm", "cost": 120})
    create_baseline_revision(conn, control_arm_id, {"material": "Aluminum", "length": "320mm", "cost": 95})
    
    # Brake Assembly
    brake_asm = create_assembly(conn, chassis_sys, "Brake Assembly", "BRAKE-FRONT-2026")
    rotor_id = create_part(conn, brake_asm, "Brake Rotor", "Braking Systems", "Cast Iron")
    pad_id = create_part(conn, brake_asm, "Brake Pad", "Friction Materials", "Ceramic")
    caliper_id = create_part(conn, brake_asm, "Brake Caliper", "Hydraulics Ltd", "Aluminum")
    
    create_baseline_revision(conn, rotor_id, {"material": "Cast Iron", "diameter": "330mm", "cost": 75})
    create_baseline_revision(conn, pad_id, {"material": "Ceramic", "thickness": "12mm", "cost": 35})
    create_baseline_revision(conn, caliper_id, {"material": "Aluminum", "pistons": 2, "cost": 145})
    
    print(f"✓ 2026 Honda Civic created (3 systems, 9 assemblies, 27 parts)")
    
    # ============================================================================
    # VEHICLE 2: 2025 Honda Accord (Automotive)
    # ============================================================================
    accord_2025_id = create_vehicle(conn, "2025 Honda Accord", "automotive", 2025)
    
    acc_elec = create_system(conn, accord_2025_id, "Electrical System")
    acc_power = create_system(conn, accord_2025_id, "Powertrain System")
    acc_chassis = create_system(conn, accord_2025_id, "Chassis System")
    
    # Electrical with similar components
    acc_horn = create_assembly(conn, acc_elec, "Horn Assembly", "HORN-ACCORD-001")
    acc_housing = create_part(conn, acc_horn, "Housing", "Metal Fabricators Inc", "Aluminum")
    acc_speaker = create_part(conn, acc_horn, "Horn Speaker", "Audio Dynamics", "Brass")
    
    create_baseline_revision(conn, acc_housing, housing_v1)
    create_baseline_revision(conn, acc_speaker, {"material": "Brass", "impedance": "8 ohms", "cost": 28})
    
    # Seats
    acc_seat = create_assembly(conn, acc_elec, "Seat Assembly", "SEAT-ACCORD-001")
    acc_seat_frame = create_part(conn, acc_seat, "Seat Frame", "Seating Dynamics", "Steel")
    create_baseline_revision(conn, acc_seat_frame, {"material": "Steel", "weight": 9.0, "cost": 125})
    
    # Powertrain
    acc_engine = create_assembly(conn, acc_power, "Engine Assembly", "ENGINE-2025")
    acc_cylinder = create_part(conn, acc_engine, "Cylinder Block", "Casting Foundry", "Cast Iron")
    acc_piston = create_part(conn, acc_engine, "Piston", "Precision Parts", "Aluminum Alloy")
    create_baseline_revision(conn, acc_cylinder, {"material": "Cast Iron", "displacement": "1.5L", "cost": 200})
    create_baseline_revision(conn, acc_piston, {"material": "Aluminum", "bore": "73mm", "cost": 45})
    
    # Chassis
    acc_brake = create_assembly(conn, acc_chassis, "Brake Assembly", "BRAKE-ACCORD-001")
    acc_rotor = create_part(conn, acc_brake, "Brake Rotor", "Braking Systems", "Cast Iron")
    create_baseline_revision(conn, acc_rotor, {"material": "Cast Iron", "diameter": "320mm", "cost": 70})
    
    print(f"✓ 2025 Honda Accord created (3 systems, 4 assemblies, 8 parts)")
    
    # ============================================================================
    # VEHICLE 3: 2024 Honda Pilot (Commercial/SUV)
    # ============================================================================
    pilot_2024_id = create_vehicle(conn, "2024 Honda Pilot", "commercial", 2024)
    
    pilot_elec = create_system(conn, pilot_2024_id, "Electrical System")
    pilot_power = create_system(conn, pilot_2024_id, "Powertrain System")
    
    # Electrical
    pilot_light = create_assembly(conn, pilot_elec, "Headlight Assembly", "HEADLIGHT-PILOT")
    pilot_lens = create_part(conn, pilot_light, "LED Lens", "Optics Corp", "Polycarbonate")
    pilot_led = create_part(conn, pilot_light, "LED Array Module", "Light Tech", "LED")
    create_baseline_revision(conn, pilot_lens, {"material": "Polycarbonate", "clarity": "99%", "cost": 40})
    create_baseline_revision(conn, pilot_led, {"lumens": 4000, "color_temp": "6500K", "cost": 180})
    
    # Powertrain
    pilot_engine = create_assembly(conn, pilot_power, "Engine Assembly", "ENGINE-PILOT")
    pilot_cylinder = create_part(conn, pilot_engine, "Cylinder Block", "Casting Foundry", "Cast Iron")
    create_baseline_revision(conn, pilot_cylinder, {"material": "Cast Iron", "displacement": "3.5L", "cost": 350})
    
    print(f"✓ 2024 Honda Pilot created (2 systems, 2 assemblies, 3 parts)")
    
    conn.close()

if __name__ == "__main__":
    try:
        migrate_parts_to_hierarchy()
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
