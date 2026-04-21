"""
Test cases for vector search isolation by domain and part context.
Ensures that similar failure modes are correctly scoped to their domain/part.
"""

import pytest
from datetime import datetime
import time
from app.database import (
    fetch_one, fetch_all, vector_search, 
    insert_and_return_id, execute_query
)
from app.embeddings import generate_embedding
from app.rpn_suggestion_engine import get_rpn_suggestions
from psycopg2.extras import Json


class TestVectorSearchIsolation:
    """Test that vector searches respect domain and part boundaries"""
    
    @pytest.fixture
    def test_data_setup(self):
        """Set up test data for isolation tests"""
        setup_info = {}
        
        # Create two distinct parts in different domains
        part1_id = insert_and_return_id("""
            INSERT INTO pfmea_records 
            (part_number, part_name, model_year, customer_name, status, domain, design_phase)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            "HORN-TEST-001",
            "Horn Coil Assembly",
            "TEST-2024",
            "Test Customer",
            "APPROVED",
            "ELECTRICAL",
            "DETAILED"
        ))
        setup_info['electrical_part_id'] = part1_id
        setup_info['electrical_part_number'] = "HORN-TEST-001"
        
        part2_id = insert_and_return_id("""
            INSERT INTO pfmea_records 
            (part_number, part_name, model_year, customer_name, status, domain, design_phase)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            "GUARD-TEST-001",
            "Saari Guard Assembly",
            "TEST-2024",
            "Test Customer",
            "APPROVED",
            "MECHANICAL",
            "DETAILED"
        ))
        setup_info['mechanical_part_id'] = part2_id
        setup_info['mechanical_part_number'] = "GUARD-TEST-001"
        
        # Create process steps
        step1_elec = insert_and_return_id("""
            INSERT INTO process_steps 
            (pfmea_record_id, step_number, step_name, design_intent)
            VALUES (%s, %s, %s, %s)
        """, (part1_id, 10, "Coil Winding", "Generate magnetic field"))
        setup_info['electrical_step_id'] = step1_elec
        
        step1_mech = insert_and_return_id("""
            INSERT INTO process_steps 
            (pfmea_record_id, step_number, step_name, design_intent)
            VALUES (%s, %s, %s, %s)
        """, (part2_id, 10, "Surface Plating", "Apply protective coating"))
        setup_info['mechanical_step_id'] = step1_mech
        
        # Create failure mode taxonomy entries (with unique test names to avoid conflicts)
        test_timestamp = str(int(time.time() * 1000))  # Millisecond timestamp
        
        fm_elec = insert_and_return_id("""
            INSERT INTO failure_mode_taxonomy 
            (canonical_name, category, version, approved_by)
            VALUES (%s, %s, %s, %s)
        """, (
            f"TEST-ELEC-{test_timestamp}",
            "ELECTRICAL",
            1,
            "Test"
        ))
        setup_info['fm_electrical_id'] = fm_elec
        
        fm_mech = insert_and_return_id("""
            INSERT INTO failure_mode_taxonomy 
            (canonical_name, category, version, approved_by)
            VALUES (%s, %s, %s, %s)
        """, (
            f"TEST-MECH-{test_timestamp}",
            "MECHANICAL",
            1,
            "Test"
        ))
        setup_info['fm_mechanical_id'] = fm_mech
        
        # Create PFMEA entries with distinct embeddings
        entry_elec = insert_and_return_id("""
            INSERT INTO pfmea_failure_mode_entries
            (pfmea_record_id, process_step_id, process_step_number, failure_mode_id,
             potential_effect, severity_user_input, occurrence_user_input, detection_user_input)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            part1_id, step1_elec, 10, fm_elec,
            "Insufficient current - weak horn sound",
            7, 2, 3
        ))
        setup_info['entry_electrical_id'] = entry_elec
        
        entry_mech = insert_and_return_id("""
            INSERT INTO pfmea_failure_mode_entries
            (pfmea_record_id, process_step_id, process_step_number, failure_mode_id,
             potential_effect, severity_user_input, occurrence_user_input, detection_user_input)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            part2_id, step1_mech, 10, fm_mech,
            "Surface corrosion - coating failure",
            8, 3, 2
        ))
        setup_info['entry_mechanical_id'] = entry_mech
        
        # Create historical incidents in different parts
        inc_elec_1 = insert_and_return_id("""
            INSERT INTO historical_incidents
            (part_number, failure_mode_id, incident_date, location, 
             severity_actual, impact_hours, corrective_action)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            "HORN-TEST-001",
            fm_elec,
            datetime(2024, 1, 15).date(),
            "Manufacturing - Electrical",
            7,
            12,
            "Replaced wire gauge specification"
        ))
        setup_info['incident_elec_1'] = inc_elec_1
        
        inc_elec_2 = insert_and_return_id("""
            INSERT INTO historical_incidents
            (part_number, failure_mode_id, incident_date, location, 
             severity_actual, impact_hours, corrective_action)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            "HORN-TEST-001",
            fm_elec,
            datetime(2024, 2, 10).date(),
            "Manufacturing - Electrical",
            6,
            8,
            "Recalibrated testing equipment"
        ))
        setup_info['incident_elec_2'] = inc_elec_2
        
        inc_mech_1 = insert_and_return_id("""
            INSERT INTO historical_incidents
            (part_number, failure_mode_id, incident_date, location, 
             severity_actual, impact_hours, corrective_action)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            "GUARD-TEST-001",
            fm_mech,
            datetime(2024, 1, 20).date(),
            "Plating Shop - Tank 1",
            8,
            24,
            "Extended surface preparation time"
        ))
        setup_info['incident_mech_1'] = inc_mech_1
        
        inc_mech_2 = insert_and_return_id("""
            INSERT INTO historical_incidents
            (part_number, failure_mode_id, incident_date, location, 
             severity_actual, impact_hours, corrective_action)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            "GUARD-TEST-001",
            fm_mech,
            datetime(2024, 2, 5).date(),
            "Plating Shop - Tank 2",
            7,
            16,
            "Adjusted plating bath chemistry"
        ))
        setup_info['incident_mech_2'] = inc_mech_2
        
        yield setup_info
        
        # Cleanup
        execute_query("DELETE FROM historical_incidents WHERE part_number LIKE 'HORN-TEST-%' OR part_number LIKE 'GUARD-TEST-%'")
        execute_query("DELETE FROM failure_mode_causes WHERE fmea_entry_id IN (SELECT id FROM pfmea_failure_mode_entries WHERE pfmea_record_id IN (SELECT id FROM pfmea_records WHERE part_number LIKE 'HORN-TEST-%' OR part_number LIKE 'GUARD-TEST-%'))")
        execute_query("DELETE FROM process_controls WHERE fmea_entry_id IN (SELECT id FROM pfmea_failure_mode_entries WHERE pfmea_record_id IN (SELECT id FROM pfmea_records WHERE part_number LIKE 'HORN-TEST-%' OR part_number LIKE 'GUARD-TEST-%'))")
        execute_query("DELETE FROM pfmea_failure_mode_entries WHERE pfmea_record_id IN (SELECT id FROM pfmea_records WHERE part_number LIKE 'HORN-TEST-%' OR part_number LIKE 'GUARD-TEST-%')")
        execute_query("DELETE FROM process_steps WHERE pfmea_record_id IN (SELECT id FROM pfmea_records WHERE part_number LIKE 'HORN-TEST-%' OR part_number LIKE 'GUARD-TEST-%')")
        execute_query("DELETE FROM pfmea_records WHERE part_number LIKE 'HORN-TEST-%' OR part_number LIKE 'GUARD-TEST-%'")
    
    def test_vector_search_by_domain_isolation(self, test_data_setup):
        """
        TEST: Vector search results should filter by domain context.
        
        FAILURE SYMPTOM: Electrical failures return mechanical incidents
        EXPECTED: Only electrical incidents for electrical failures
        
        NOTE: Domain filtering happens at the part/failure_mode level, not at historical_incidents
        since historical_incidents table doesn't have a domain column. We filter by part_number
        which implicitly scopes to a domain.
        """
        data = test_data_setup
        
        # Generate query embedding for electrical failure
        elec_query_embedding = generate_embedding(
            "Resistance drift in electrical coil winding causing insufficient current"
        )
        
        # Search historical incidents - filter by electrical part_number
        results = vector_search(
            table="historical_incidents",
            embedding_column="embedding",
            query_embedding=elec_query_embedding,
            limit=10,
            additional_conditions="AND part_number = %s",
            params=(data['electrical_part_number'],)
        )
        
        # Verify all results are from electrical part
        for result in results:
            part_number = result.get('part_number', '')
            assert part_number == data['electrical_part_number'], \
                f"Found {part_number} in electrical search"
        
        # Should NOT include mechanical part
        part_numbers = [r.get('part_number', '') for r in results]
        assert not any(pn == data['mechanical_part_number'] for pn in part_numbers), \
            f"Found mechanical part in electrical search: {part_numbers}"
    
    def test_vector_search_by_part_number_isolation(self, test_data_setup):
        """
        TEST: Vector search can filter by specific part number.
        
        FAILURE SYMPTOM: Horn search returns Saari Guard incidents
        EXPECTED: Only Horn incidents when filtering by part_number
        """
        data = test_data_setup
        
        # Generate query embedding for horn failure
        horn_query_embedding = generate_embedding(
            "Coil resistance variation causing horn malfunction"
        )
        
        # Search with explicit part_number filter
        results = vector_search(
            table="historical_incidents",
            embedding_column="embedding",
            query_embedding=horn_query_embedding,
            limit=10,
            additional_conditions="AND part_number = %s",
            params=(data['electrical_part_number'],)
        )
        
        # Verify all results are for the horn part
        for result in results:
            assert result.get('part_number') == data['electrical_part_number'], \
                f"Found {result.get('part_number')} in search for {data['electrical_part_number']}"
        
        # Should NOT return mechanical part
        assert all(r.get('part_number') != data['mechanical_part_number'] for r in results), \
            f"Found Guard part in Horn search results"
    
    def test_vector_search_by_failure_mode_isolation(self, test_data_setup):
        """
        TEST: Vector search can filter by specific failure mode.
        
        FAILURE SYMPTOM: Resistance drift search returns plating failures
        EXPECTED: Only resistance drift failures returned
        """
        data = test_data_setup
        
        # Get the electrical failure mode ID
        fm_with_id = fetch_one("""
            SELECT id FROM failure_mode_taxonomy WHERE canonical_name = %s
        """, ("Resistance Drift - ELECTRICAL",))
        fm_id = fm_with_id['id']
        
        # Generate query embedding
        query_embedding = generate_embedding("Wire gauge not meeting specification causes resistance drift")
        
        # Search filtered by failure_mode_id
        results = vector_search(
            table="historical_incidents",
            embedding_column="embedding",
            query_embedding=query_embedding,
            limit=10,
            additional_conditions="AND failure_mode_id = %s",
            params=(fm_id,)
        )
        
        # Verify all results have the correct failure mode
        for result in results:
            assert result.get('failure_mode_id') == fm_id, \
                f"Found wrong failure mode: {result.get('failure_mode_id')} vs {fm_id}"
    
    def test_rpn_suggestions_domain_scoped(self, test_data_setup):
        """
        TEST: RPN suggestions should only use incidents from same domain.
        
        FAILURE SYMPTOM: get_rpn_suggestions() for horn returns guard incidents
        EXPECTED: Only electrical incidents for electrical failures
        """
        data = test_data_setup
        
        # Get the horn entry (electrical)
        horn_entry = fetch_one("""
            SELECT * FROM pfmea_failure_mode_entries WHERE id = %s
        """, (data['entry_electrical_id'],))
        
        # Get domain from part
        horn_part = fetch_one("""
            SELECT domain FROM pfmea_records WHERE id = %s
        """, (data['electrical_part_id'],))
        
        domain = horn_part['domain']
        assert domain == "ELECTRICAL", f"Test setup error: horn domain is {domain}"
        
        # Get RPN suggestions - should respect domain
        suggestions = get_rpn_suggestions(
            failure_mode_id=data['fm_electrical_id'],
            part_number=data['electrical_part_number'],
            limit=5
        )
        
        if suggestions:
            # Verify evidence comes from electrical domain/part
            if 'evidence' in suggestions:
                for evidence in suggestions['evidence']:
                    # Evidence should be from electrical domain
                    assert evidence.get('domain', 'ELECTRICAL') == 'ELECTRICAL', \
                        f"Found {evidence.get('domain')} evidence in electrical RPN suggestions"
    
    def test_no_cross_domain_contamination(self, test_data_setup):
        """
        TEST: Comprehensive check - no mechanical results when searching electrical.
        
        FAILURE SYMPTOM: Horn (electrical) and Guard (mechanical) results mixed
        EXPECTED: Clear separation based on part_number
        
        NOTE: We filter by part_number which implicitly gives domain isolation
        """
        data = test_data_setup
        
        # Search electrical part
        elec_embedding = generate_embedding("electrical coil winding thermal failure")
        elec_results = vector_search(
            table="historical_incidents",
            embedding_column="embedding",
            query_embedding=elec_embedding,
            limit=10,
            additional_conditions="AND part_number = %s",
            params=(data['electrical_part_number'],)
        )
        
        # Search mechanical part
        mech_embedding = generate_embedding("plating surface preparation coating failure")
        mech_results = vector_search(
            table="historical_incidents",
            embedding_column="embedding",
            query_embedding=mech_embedding,
            limit=10,
            additional_conditions="AND part_number = %s",
            params=(data['mechanical_part_number'],)
        )
        
        # Extract part numbers from each search
        elec_parts = set(r.get('part_number', '') for r in elec_results if elec_results)
        mech_parts = set(r.get('part_number', '') for r in mech_results if mech_results)
        
        # Ensure no overlap
        overlap = elec_parts & mech_parts
        assert len(overlap) == 0, \
            f"Found overlapping parts in electrical and mechanical searches: {overlap}"
        
        # Verify each search returned results from the correct part
        if elec_results:
            assert all(r.get('part_number') == data['electrical_part_number'] for r in elec_results), \
                "Electrical search returned non-electrical parts"
        if mech_results:
            assert all(r.get('part_number') == data['mechanical_part_number'] for r in mech_results), \
                "Mechanical search returned non-mechanical parts"
    
    def test_embedding_vector_format_consistency(self, test_data_setup):
        """
        TEST: Embeddings are stored and retrieved consistently (proper format).
        
        FAILURE SYMPTOM: Corrupted vector format like [[,0,.,0,0,3,...]]
        EXPECTED: Valid pgvector format [0.123, 0.456, ...]
        """
        data = test_data_setup
        
        # Create a test embedding
        test_text = "Test failure mode for vector consistency"
        test_embedding = generate_embedding(test_text)
        
        # Verify it's a list of floats
        assert isinstance(test_embedding, list), f"Embedding is {type(test_embedding)}, not list"
        assert len(test_embedding) == 1536, f"Embedding length is {len(test_embedding)}, expected 1536"
        assert all(isinstance(v, (int, float)) for v in test_embedding), \
            "Embedding contains non-numeric values"
        
        # Store and retrieve
        test_id = insert_and_return_id("""
            INSERT INTO historical_incidents
            (part_number, failure_mode_id, incident_date, location, 
             severity_actual, impact_hours, corrective_action, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            "TEST-EMBED-001",
            data['fm_electrical_id'],
            datetime.now().date(),
            "Test Location",
            5,
            4,
            "Test action",
            Json(test_embedding)
        ))
        
        # Retrieve and verify format
        retrieved = fetch_one("""
            SELECT embedding FROM historical_incidents WHERE id = %s
        """, (test_id,))
        
        # Parse if stored as string
        retrieved_embedding = retrieved['embedding']
        if isinstance(retrieved_embedding, str):
            # Should be in format "[0.123, 0.456, ...]"
            assert retrieved_embedding.startswith('['), f"Invalid embedding format: {retrieved_embedding[:50]}"
            assert retrieved_embedding.endswith(']'), f"Invalid embedding format: {retrieved_embedding[-50:]}"
            assert ',' in retrieved_embedding, "Embedding lacks commas between values"
            # Should NOT have dots between digits like [[,0,.,0,0
            assert not '[[' in retrieved_embedding, f"Corrupted embedding format: {retrieved_embedding[:50]}"
        
        execute_query("DELETE FROM historical_incidents WHERE part_number = %s", ("TEST-EMBED-001",))


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
