"""
RPN Suggestion Engine for DFMEA
Queries historical design incidents for similar failure modes
Returns suggested S/O/D/RPN scores based on design margins and validation effectiveness
"""

from typing import List, Optional, Dict, Any
from statistics import median, mean
from app.database import fetch_one, fetch_all, vector_search


def get_rpn_suggestions(failure_mode_id: int, part_number: str, limit: int = 5) -> Optional[Dict[str, Any]]:
    """
    Find similar historical design validation incidents for a failure mode
    Return suggested S/O/D/RPN scores based on design margins and validation effectiveness
    
    Args:
        failure_mode_id: ID of the failure mode to find suggestions for
        part_number: Part number for part family grouping
        limit: Number of historical incidents to consider
    
    Returns:
        Dictionary with suggested S/O/D/RPN scores incorporating design margins and validation, or None if no history
        
    New DFMEA Semantics:
        - Severity (S): Functional consequence (1-10 unchanged)
        - Occurrence (O): Derived from design_margin_loss / safety_factor_assumed
          Formula: O = clamp(1-10, design_margin_loss / safety_factor × 10)
        - Detection (D): Derived from validation measure effectiveness
          Formula: D = 10 - max(effectiveness_percent from validation measures)
    """
    
    # Query 1: Find historical incidents for same failure mode
    same_mode_incidents = fetch_all("""
        SELECT 
            hi.id,
            hi.part_number,
            hi.incident_date,
            hi.severity_actual,
            hi.design_margin_loss,
            hi.location,
            hi.impact_hours,
            hi.corrective_action
        FROM historical_incidents hi
        WHERE hi.failure_mode_id = %s
        ORDER BY hi.incident_date DESC
        LIMIT %s
    """, (failure_mode_id, limit))
    
    # Query 2: Find similar historical incidents by failure mode embedding
    failure_mode = fetch_one("""
        SELECT * FROM failure_mode_taxonomy WHERE id = %s
    """, (failure_mode_id,))
    
    if not failure_mode:
        return None
    
    similar_mode_incidents = []
    if failure_mode.get('embedding'):
        # Vector search with part context isolation
        # Filter by same part family to avoid cross-contamination
        # (e.g., Horn issues don't pull Saari Guard incidents)
        similar_mode_incidents = vector_search(
            table="historical_incidents",
            embedding_column="embedding",
            query_embedding=failure_mode['embedding'],
            limit=limit,
            additional_conditions="AND part_number = %s",
            params=(part_number,)
        )
    
    # Combine and deduplicate
    all_incidents = same_mode_incidents + similar_mode_incidents
    seen_ids = set()
    unique_incidents = []
    for incident in all_incidents:
        if incident['id'] not in seen_ids:
            seen_ids.add(incident['id'])
            unique_incidents.append(incident)
        if len(unique_incidents) >= limit:
            break
    
    if not unique_incidents:
        return None
    
    # Calculate suggested scores using design-focused metrics
    # Severity: From historical severity (unchanged)
    severities = [i.get('severity_actual') for i in unique_incidents if i.get('severity_actual')]
    severity_suggested = int(median(severities)) if severities else 5
    
    # Occurrence: From design margin losses (new DFMEA logic)
    # O = min(10, max(1, design_margin_loss / safety_factor × 10))
    # Without safety_factor data, approximate: O ≈ design_margin_loss × 10
    margin_losses = [i.get('design_margin_loss') for i in unique_incidents if i.get('design_margin_loss')]
    if margin_losses:
        median_margin_loss = median(margin_losses)
        occurrence_suggested = int(min(10, max(1, median_margin_loss * 10)))  # Scale 0-1 margin to 1-10 O
    else:
        occurrence_suggested = 5  # Default mid-range if no historical margin data
    
    # Detection: From validation measure effectiveness (new DFMEA logic)
    # Query validation measures effectiveness for this failure mode in historical FMEAs
    validation_effectiveness = fetch_all("""
        SELECT effectiveness_percent FROM process_controls pc
        JOIN pfmea_failure_mode_entries pfme ON pc.fmea_entry_id = pfme.id
        WHERE pfme.failure_mode_id = %s
        LIMIT %s
    """, (failure_mode_id, limit))
    
    if validation_effectiveness:
        max_effectiveness = max([v.get('effectiveness_percent', 0) for v in validation_effectiveness])
        detection_suggested = max(1, 10 - max_effectiveness)  # D = 10 - confidence
    else:
        detection_suggested = 10  # No validation = D=10 (worst case)
    
    suggestions = {
        'severity_suggested': severity_suggested,
        'occurrence_suggested': occurrence_suggested,
        'detection_suggested': detection_suggested,
        'rpn_suggested': severity_suggested * occurrence_suggested * detection_suggested,
        'similar_incident_count': len(unique_incidents),
        'calculation_method': 'DFMEA_design_margin_validation_based',
        'incidents': [
            {
                'id': i['id'],
                'part_number': i.get('part_number'),
                'incident_date': str(i.get('incident_date')),
                'location': i.get('location'),
                'severity_actual': i.get('severity_actual'),
                'design_margin_loss': i.get('design_margin_loss'),
                'impact_hours': i.get('impact_hours'),
                'corrective_action': i.get('corrective_action')
            }
            for i in unique_incidents[:5]
        ]
    }
    
    return suggestions


def extract_part_family(part_number: str) -> str:
    """Extract part family from part number for grouping similar parts"""
    # Example: "14610-KTCA-9000" → "14610"
    # Example: "HORN-COMP-001" → "HORN"
    if '-' in part_number:
        return part_number.split('-')[0]
    return part_number


def calculate_consensus_rpn(
    severity_scores: List[int],
    occurrence_scores: List[int],
    detection_scores: List[int]
) -> Dict[str, Any]:
    """
    When multiple team members score a failure mode independently,
    calculate consensus RPN with distribution analysis
    
    Returns: Consensus S/O/D/RPN plus distribution statistics
    """
    
    if not severity_scores or not occurrence_scores or not detection_scores:
        return None
    
    consensus_s = int(round(mean(severity_scores)))
    consensus_o = int(round(mean(occurrence_scores)))
    consensus_d = int(round(mean(detection_scores)))
    consensus_rpn = consensus_s * consensus_o * consensus_d
    
    return {
        'severity': consensus_s,
        'occurrence': consensus_o,
        'detection': consensus_d,
        'rpn': consensus_rpn,
        'distribution': {
            'severity': {
                'votes': severity_scores,
                'min': min(severity_scores),
                'max': max(severity_scores),
                'std_dev': max(severity_scores) - min(severity_scores) if len(set(severity_scores)) > 1 else 0
            },
            'occurrence': {
                'votes': occurrence_scores,
                'min': min(occurrence_scores),
                'max': max(occurrence_scores),
                'std_dev': max(occurrence_scores) - min(occurrence_scores) if len(set(occurrence_scores)) > 1 else 0
            },
            'detection': {
                'votes': detection_scores,
                'min': min(detection_scores),
                'max': max(detection_scores),
                'std_dev': max(detection_scores) - min(detection_scores) if len(set(detection_scores)) > 1 else 0
            }
        }
    }


def classify_rpn_risk(rpn: int) -> str:
    """Classify RPN into risk categories"""
    if rpn > 70:
        return "HIGH"
    elif rpn >= 40:
        return "MED"
    else:
        return "LOW"


def get_rpn_summary(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate overall FMEA component RPN summary
    
    Args:
        entries: List of failure mode entries with scores
    
    Returns:
        Summary with max, average, and risk distribution
    """
    rpns = [e.get('rpn_user_calculated') or e.get('rpn_suggested') or 0 for e in entries]
    
    if not rpns:
        rpns = [0]
    
    return {
        'max': max(rpns),
        'average': round(sum(rpns) / len(rpns), 2),
        'total_failure_modes': len(entries),
        'high_count': len([r for r in rpns if r > 70]),
        'med_count': len([r for r in rpns if 40 <= r <= 70]),
        'low_count': len([r for r in rpns if r < 40]),
        'rpn_distribution': {
            'high': [r for r in rpns if r > 70],
            'med': [r for r in rpns if 40 <= r <= 70],
            'low': [r for r in rpns if r < 40]
        }
    }


def find_similar_parts(part_name: str, limit: int = 3) -> List[Dict]:
    """
    Find similar existing parts using pgvector semantic search on embeddings.
    Falls back to fuzzy word matching if embeddings unavailable.
    
    Args:
        part_name: Name of the new part to match
        limit: Maximum number of similar parts to return
    
    Returns:
        List of similar parts ranked by embedding similarity score
    """
    all_parts = fetch_all("""
        SELECT id, part_number, part_name, model_year FROM pfmea_records
        ORDER BY created_at DESC
    """)
    
    if not all_parts:
        return []
    
    # Try vector search first if embeddings are available
    try:
        from app.embeddings import generate_embedding
        
        # Generate embedding for search query
        query_embedding = generate_embedding(part_name)
        
        # Use pgvector cosine distance search
        similar_parts = fetch_all("""
            SELECT 
                id, part_number, part_name, model_year,
                1 - (embedding <=> %s::vector) as match_score
            FROM pfmea_records
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (str(query_embedding), str(query_embedding), limit))
        
        if similar_parts:
            return [dict(p) for p in similar_parts]
    except Exception:
        pass  # Fall through to fuzzy matching
    
    # Fallback: Fuzzy word matching
    search_words = part_name.lower().split()
    scored_parts = []
    
    for p in all_parts:
        part_words = p['part_name'].lower().split()
        # Count matching words (case-insensitive, substring matching)
        match_score = sum(1 for w in search_words if any(w in pw or pw in w for pw in part_words))
        
        if match_score > 0:
            scored_parts.append({**p, 'match_score': match_score})
    
    # If we found matching parts, return them sorted by score
    if scored_parts:
        scored_parts.sort(key=lambda x: x['match_score'], reverse=True)
        return scored_parts[:limit]
    
    # Ultimate fallback: return most recent parts
    fallback_parts = []
    for p in all_parts[:limit]:
        fallback_parts.append({**p, 'match_score': 0})
    return fallback_parts


def get_part_failures(part_id: int) -> List[Dict]:
    """
    Get all failure modes from an existing part for cloning
    
    Args:
        part_id: ID of the part to clone failures from
    
    Returns:
        List of failure mode entries with scores and process step info
    """
    failures = fetch_all("""
        SELECT 
            pfme.id,
            pfme.failure_mode_id,
            pfme.process_step_number,
            pfme.potential_effect,
            pfme.severity_user_input as severity,
            pfme.occurrence_user_input as occurrence,
            pfme.detection_user_input as detection,
            fm.canonical_name as failure_mode_name
        FROM pfmea_failure_mode_entries pfme
        JOIN failure_mode_taxonomy fm ON pfme.failure_mode_id = fm.id
        WHERE pfme.pfmea_record_id = %s
        ORDER BY pfme.process_step_number
    """, (part_id,))
    
    return [dict(f) for f in failures] if failures else []


def find_relevant_failure_modes(part_name: str, part_number: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Use pgvector semantic search to find relevant failure modes for a new part
    based on part name and description. Falls back to taxonomy if embeddings unavailable.
    
    Args:
        part_name: Name of the new part (e.g., "Horn Comp Assembly")
        part_number: Part number (e.g., "HORN-COMP-001")
        limit: Number of failure modes to return (default 5)
    
    Returns:
        List of relevant failure modes from taxonomy with IDs and details
    """
    # First, try to get ANY failure modes from taxonomy
    all_failure_modes = fetch_all("""
        SELECT 
            id,
            canonical_name,
            category,
            version,
            typical_severity_range,
            aliases
        FROM failure_mode_taxonomy
        ORDER BY id
        LIMIT 100
    """)
    
    if not all_failure_modes:
        return []
    
    # If we have fewer modes than requested, just return all
    if len(all_failure_modes) <= limit:
        return all_failure_modes
    
    # Try to use embeddings for smarter selection
    try:
        from app.embeddings import embed_text
        
        # Create a search query from part name and number
        search_query = f"{part_name} {part_number}".lower()
        query_embedding = embed_text(search_query)
        
        # Score each failure mode by semantic similarity
        scored_modes = []
        for mode in all_failure_modes:
            if mode.get('embedding'):
                # Calculate cosine similarity (dot product)
                similarity_score = sum(
                    a * b for a, b in zip(query_embedding, mode.get('embedding', []))
                )
                scored_modes.append({**mode, 'similarity_score': similarity_score})
            else:
                scored_modes.append({**mode, 'similarity_score': 0})
        
        # Sort by similarity and return top N
        scored_modes.sort(key=lambda x: x['similarity_score'], reverse=True)
        return scored_modes[:limit]
    except Exception:
        # Fallback: return first N modes if embeddings fail
        return all_failure_modes[:limit]
