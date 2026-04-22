-- Add Housing Crack historical incidents (failure_mode_id = 11)
DELETE FROM historical_incidents WHERE failure_mode_id = 11;

INSERT INTO historical_incidents (part_number, failure_mode_id, incident_date, location, severity_actual, impact_hours, corrective_action)
VALUES 
  ('HORN COMP.', 11, '2003-07-10', 'Manufacturing Plant - Vibration Testing', 7, 32, 'Increased material thickness, improved damping material in housing'),
  ('HORN COMP.', 11, '2023-08-15', 'Field Testing - Customer Site A', 8, 48, 'Redesigned housing geometry with reinforced ribs, field retrofits completed'),
  ('HORN COMP.', 11, '2023-11-20', 'Manufacturing Plant - Thermal Testing Lab', 9, 24, 'Implemented CFD thermal interface optimization, extended testing duration');

SELECT COUNT(*) as "Incidents Added" FROM historical_incidents WHERE failure_mode_id = 11;
