docker cp init_pfmea.sql decisionledger_db:/tmp/init_pfmea.sql
docker exec decisionledger_db psql -U postgres -d decisionledger -f /tmp/init_pfmea.sql
docker exec decisionledger_backend python -m scripts.seed_pfmea_canvas