"""
RPN Suggestion Engine
Queries historical incidents for similar failure modes
Returns suggested S/O/D/RPN scores based on past data
"""

from typing import List, Optional, Dict, Any
from statistics import median, mean
from app.database import fetch_one, fetch_all, vector_search


def get_rpn_suggestions(failure_mode_id: int, part_number: str, limit: int = 5) -> Optional[Dict[str, Any]]:
    """
    Find similar historical incidents for a failure mode
    Return suggested S/O/D/RPN scores based on historical data
    
    Args:
        failure_mode_id: ID of the failure mode to find suggestions for
        part_number: Part number for part family grouping
        limit: Number of historical incidents to consider
    
    Returns:
        Dictionary with suggested S/O/D/RPN scores, or None if no history found
    """
    
    # Query 1: Find historical incidents for same failure mode
    same_mode_incidents = fetch_all("""
        SELECT 
            hi.id,
            hi.part_number,
            hi.incident_date,
            hi.severity_actual,
            hi.location,
            hi.impact_hours,
            hi.corrective_action
        FROM historical_incidents hi
        WHERE hi.failure_mode_id = %s
        ORDER BY hi.incident_date DESC
        LIMIT %s
    """, (failure_mode_id, limit))
    
    # Query 2: Find similar historical incidents by failure mode similarity
    failure_mode = fetch_one("""
        SELECT * FROM failure_mode_taxonomy WHERE id = %s
    """, (failure_mode_id,))
    
    if not failure_mode:
        return None
    
    similar_mode_incidents = []
    if failure_mode.get('embedding'):
        similar_mode_incidents = vector_search(
            table="historical_incidents",
            embedding_column="embedding",
            query_embedding=failure_mode['embedding'],
            limit=limit,
        )
    
    # Combine both queries
    all_incidents = same_mode_incidents + similar_mode_incidents
    
    # Deduplicate by incident ID
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
    
    # Calculate suggested scores from historical data
    severities = [i.get('severity_actual') for i in unique_incidents if i.get('severity_actual')]
    
    # Set suggested severity from historical data or default to median
    severity_suggested = int(median(severities)) if severities else 5
    occurrence_suggested = min(5, max(1, len(unique_incidents) // 2))  # Based on frequency
    detection_suggested = 3  # Default moderate detection difficulty
    
    suggestions = {
        'severity_suggested': severity_suggested,
        'occurrence_suggested': occurrence_suggested,
        'detection_suggested': detection_suggested,
        'rpn_suggested': severity_suggested * occurrence_suggested * detection_suggested,  # Always calculate
        'similar_incident_count': len(unique_incidents),
        'incidents': [
            {
                'id': i['id'],
                'part_number': i.get('part_number'),
                'incident_date': str(i.get('incident_date')),
                'location': i.get('location'),
                'severity_actual': i.get('severity_actual'),
                'impact_hours': i.get('impact_hours'),
                'corrective_action': i.get('corrective_action')
            }
            for i in unique_incidents[:5]  # Top 5 incidents
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
    Find similar existing parts using fuzzy word matching
    
    Args:
        part_name: Name of the new part to match
        limit: Maximum number of similar parts to return
    
    Returns:
        List of similar parts ranked by match score
    """
    all_parts = fetch_all("""
        SELECT id, part_number, part_name, model_year FROM pfmea_records
        ORDER BY part_number
    """)
    
    if not all_parts:
        return []
    
    # Split part name into words and score matches
    search_words = part_name.lower().split()
    scored_parts = []
    
    for p in all_parts:
        part_words = p['part_name'].lower().split()
        # Count matching words
        match_score = sum(1 for w in search_words if any(w in pw or pw in w for pw in part_words))
        
        if match_score > 0:
            scored_parts.append({**p, 'match_score': match_score})
    
    # Sort by match score descending
    scored_parts.sort(key=lambda x: x['match_score'], reverse=True)
    return scored_parts[:limit]


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
    based on part name and description
    
    Args:
        part_name: Name of the new part (e.g., "Horn Comp Assembly")
        part_number: Part number (e.g., "HORN-COMP-001")
        limit: Number of failure modes to return (default 5)
    
    Returns:
        List of relevant failure modes from taxonomy with IDs and details
    """
    try:
        from app.embeddings import embed_text
    except ImportError:
        # Fallback if embeddings not available
        all_modes = fetch_all("""
            SELECT id, canonical_name, category, version 
            FROM failure_mode_taxonomy 
            LIMIT %s
        """, (limit,))
        return all_modes if all_modes else []
    
    # Create a search query from part name and number
    search_query = f"{part_name} {part_number}".lower()
    
    # Get all failure modes from taxonomy
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
    
    # Score each failure mode by semantic similarity
    scored_modes = []
    try:
        query_embedding = embed_text(search_query)
        
        for mode in all_failure_modes:
            if mode.get('embedding'):
                # Calculate cosine similarity (dot product approximation)
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
        # Fallback: return first N modes
        return all_failure_modes[:limit]
