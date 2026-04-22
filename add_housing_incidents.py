#!/usr/bin/env python3
import psycopg2

conn = psycopg2.connect('dbname=decisionledger user=postgres password=postgres host=localhost')
cur = conn.cursor()

# Delete existing incidents for Housing Crack (FM ID 11)
cur.execute("DELETE FROM historical_incidents WHERE failure_mode_id = 11")

# Insert new incidents
incidents = [
    ('HORN COMP.', 11, '2003-07-10', 'Manufacturing Plant - Vibration Testing', 7, 32, 'Increased material thickness, improved damping material in housing'),
    ('HORN COMP.', 11, '2023-08-15', 'Field Testing - Customer Site A', 8, 48, 'Redesigned housing geometry with reinforced ribs, field retrofits completed'),
    ('HORN COMP.', 11, '2023-11-20', 'Manufacturing Plant - Thermal Testing Lab', 9, 24, 'Implemented CFD thermal interface optimization, extended testing duration'),
]

for part_num, fm_id, date, location, severity, impact, action in incidents:
    cur.execute("""
        INSERT INTO historical_incidents (part_number, failure_mode_id, incident_date, location, severity_actual, impact_hours, corrective_action)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (part_num, fm_id, date, location, severity, impact, action))

conn.commit()

# Verify
cur.execute("SELECT COUNT(*) FROM historical_incidents WHERE failure_mode_id = 11")
count = cur.fetchone()[0]
print(f"✅ {count} incidents added for Housing Crack Under Vibration")

cur.execute("SELECT severity_actual FROM historical_incidents WHERE failure_mode_id = 11 ORDER BY severity_actual")
severities = [row[0] for row in cur.fetchall()]
print(f"   Severities: {severities}")
print(f"   Median: {sorted(severities)[len(severities)//2]}")

conn.close()
