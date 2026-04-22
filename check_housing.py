#!/usr/bin/env python3
import psycopg2

conn = psycopg2.connect('dbname=decisionledger user=postgres password=postgres host=localhost')
cur = conn.cursor()

# Find Housing Crack failure mode
cur.execute("SELECT id, canonical_name FROM failure_mode_taxonomy WHERE canonical_name ILIKE '%housing%crack%'")
fm = cur.fetchone()

if fm:
    fm_id, fm_name = fm
    print(f'Found: {fm_name} (ID: {fm_id})')
    
    # Check for historical incidents
    cur.execute('SELECT COUNT(*) FROM historical_incidents WHERE failure_mode_id = %s', (fm_id,))
    count = cur.fetchone()[0]
    print(f'Historical incidents: {count}')
    
    if count > 0:
        cur.execute('SELECT id, severity_actual, incident_date FROM historical_incidents WHERE failure_mode_id = %s LIMIT 5', (fm_id,))
        for row in cur.fetchall():
            print(f'  - Severity: {row[1]}, Date: {row[2]}')
else:
    print('Housing Crack not found')
    print('\nAvailable failure modes:')
    cur.execute("SELECT id, canonical_name FROM failure_mode_taxonomy LIMIT 15")
    for row in cur.fetchall():
        print(f'  - ID {row[0]}: {row[1]}')

conn.close()
