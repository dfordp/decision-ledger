"""
Database connection and query helpers for FMEA application.
Uses psycopg2 with connection pooling for PostgreSQL + pgvector.
"""

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
import os
from dotenv import load_dotenv

load_dotenv()

# Connection pool (singleton pattern)
_pool = None

def get_connection_pool():
    """Get or create connection pool"""
    global _pool
    if _pool is None:
        database_url = os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/decisionledger"
        )
        _pool = SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=database_url
        )
    return _pool

@contextmanager
def get_connection():
    """Context manager for database connections"""
    pool = get_connection_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        pool.putconn(conn)

# ============================================================================
# BASIC QUERY HELPERS
# ============================================================================

def execute_query(query: str, params: tuple = None) -> None:
    """Execute a query without returning results (INSERT, UPDATE, DELETE)"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        cursor.close()

def fetch_one(query: str, params: tuple = None) -> Optional[Dict[str, Any]]:
    """Fetch a single row as a dictionary"""
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(query, params)
        result = cursor.fetchone()
        cursor.close()
        return dict(result) if result else None

def fetch_all(query: str, params: tuple = None) -> List[Dict[str, Any]]:
    """Fetch all rows as a list of dictionaries"""
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(query, params)
        results = cursor.fetchall()
        cursor.close()
        return [dict(row) for row in results]

def fetch_one_value(query: str, params: tuple = None) -> Any:
    """Fetch a single value from a query"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        result = cursor.fetchone()
        cursor.close()
        return result[0] if result else None

def insert_and_return_id(query: str, params: tuple = None) -> int:
    """Execute INSERT and return the generated ID"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query + " RETURNING id", params)
        result_id = cursor.fetchone()[0]
        cursor.close()
        return result_id

# ============================================================================
# VECTOR SEARCH HELPERS
# ============================================================================

def vector_search(
    table: str,
    embedding_column: str,
    query_embedding: List[float],
    limit: int = 5,
    additional_conditions: str = "",
    params: tuple = None
) -> List[Dict[str, Any]]:
    """
    Perform vector similarity search using cosine distance.
    
    Args:
        table: Table name to search
        embedding_column: Column name containing embeddings
        query_embedding: Vector to search for
        limit: Number of results to return
        additional_conditions: Additional WHERE clauses (e.g., "AND domain = %s")
        params: Parameters for additional conditions
    
    Returns:
        List of rows with similarity scores
    """
    # Convert embedding list to pgvector format
    embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"
    
    query = f"""
        SELECT *,
               1 - ({embedding_column} <=> %s::vector) as similarity
        FROM {table}
        WHERE {embedding_column} IS NOT NULL
        {additional_conditions}
        ORDER BY {embedding_column} <=> %s::vector
        LIMIT %s
    """
    
    # Build parameter tuple
    if params:
        query_params = [embedding_str] + list(params) + [embedding_str, limit]
    else:
        query_params = [embedding_str, embedding_str, limit]
    
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(query, tuple(query_params))
        results = cursor.fetchall()
        cursor.close()
        return [dict(row) for row in results]

# ============================================================================
# PRODUCT SYSTEM QUERIES
# ============================================================================

def get_product_system(system_id: int) -> Optional[Dict[str, Any]]:
    """Fetch product system by ID"""
    query = "SELECT * FROM product_system WHERE id = %s"
    return fetch_one(query, (system_id,))

def get_product_systems(domain: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch all product systems, optionally filtered by domain"""
    if domain:
        query = "SELECT * FROM product_system WHERE domain = %s ORDER BY name"
        return fetch_all(query, (domain,))
    else:
        query = "SELECT * FROM product_system ORDER BY name"
        return fetch_all(query)

def create_product_system(
    name: str,
    domain: str,
    system_level: str,
    system_function: str,
    description: Optional[str] = None,
    scope: Optional[str] = None
) -> int:
    """Create new product system, return ID"""
    query = """
        INSERT INTO product_system (name, domain, system_level, description, system_function, scope)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    return insert_and_return_id(query, (name, domain, system_level, description, system_function, scope))

# ============================================================================
# FMEA RECORD QUERIES
# ============================================================================

def get_fmea_record(fmea_id: int) -> Optional[Dict[str, Any]]:
    """Fetch FMEA record by ID"""
    query = "SELECT * FROM fmea_record WHERE id = %s"
    return fetch_one(query, (fmea_id,))

def get_fmea_records(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch all FMEA records, optionally filtered by status"""
    if status:
        query = "SELECT * FROM fmea_record WHERE status = %s ORDER BY created_at DESC"
        return fetch_all(query, (status,))
    else:
        query = "SELECT * FROM fmea_record ORDER BY created_at DESC"
        return fetch_all(query)

def get_fmea_by_project_name(project_name: str) -> Optional[Dict[str, Any]]:
    """Fetch FMEA record by project name"""
    query = "SELECT * FROM fmea_record WHERE project_name = %s"
    return fetch_one(query, (project_name,))

def create_fmea_record(
    product_system_id: int,
    project_name: str,
    description: Optional[str] = None,
    created_by: Optional[str] = None
) -> int:
    """Create new FMEA record, return ID"""
    query = """
        INSERT INTO fmea_record (product_system_id, project_name, description, created_by)
        VALUES (%s, %s, %s, %s)
    """
    return insert_and_return_id(query, (product_system_id, project_name, description, created_by))

def update_fmea_record(
    fmea_id: int,
    current_phase: Optional[str] = None,
    status: Optional[str] = None,
    team_leads: Optional[str] = None,
    team_members: Optional[str] = None
) -> None:
    """Update FMEA record"""
    updates = []
    params = []
    
    if current_phase is not None:
        updates.append("current_phase = %s")
        params.append(current_phase)
    if status is not None:
        updates.append("status = %s")
        params.append(status)
    if team_leads is not None:
        updates.append("team_leads = %s")
        params.append(team_leads)
    if team_members is not None:
        updates.append("team_members = %s")
        params.append(team_members)
    
    if not updates:
        return
    
    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(fmea_id)
    
    query = f"UPDATE fmea_record SET {', '.join(updates)} WHERE id = %s"
    execute_query(query, tuple(params))

def mark_fmea_phase_complete(fmea_id: int, phase: str, notes: Optional[str] = None) -> None:
    """Mark a FMEA phase as complete"""
    query = """
        INSERT INTO fmea_phase_checklist (fmea_record_id, phase, is_complete, completed_at, notes)
        VALUES (%s, %s, TRUE, CURRENT_TIMESTAMP, %s)
        ON CONFLICT (fmea_record_id, phase) DO UPDATE
        SET is_complete = TRUE, completed_at = CURRENT_TIMESTAMP, notes = %s
    """
    execute_query(query, (fmea_id, phase, notes, notes))

# ============================================================================
# FAILURE MODE QUERIES
# ============================================================================

def get_failure_mode(failure_mode_id: int) -> Optional[Dict[str, Any]]:
    """Fetch failure mode by ID"""
    query = "SELECT * FROM failure_mode WHERE id = %s"
    return fetch_one(query, (failure_mode_id,))

def get_failure_modes(fmea_id: int) -> List[Dict[str, Any]]:
    """Fetch all failure modes for an FMEA"""
    query = """
        SELECT * FROM failure_mode 
        WHERE fmea_record_id = %s 
        ORDER BY created_at DESC
    """
    return fetch_all(query, (fmea_id,))

def create_failure_mode(
    fmea_id: int,
    product_system_id: int,
    mode_type: str,
    description: str,
    potential_effects: Optional[str] = None,
    severity_score: int = 5,
    source: Optional[str] = None,
    embedding: Optional[List[float]] = None
) -> int:
    """Create new failure mode, return ID"""
    query = """
        INSERT INTO failure_mode 
        (fmea_record_id, product_system_id, mode_type, description, potential_effects, 
         severity_score, source, description_embedding)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    
    # Convert embedding to pgvector format if provided
    embedding_param = None
    if embedding:
        embedding_param = "[" + ",".join(map(str, embedding)) + "]"
    
    return insert_and_return_id(query, 
        (fmea_id, product_system_id, mode_type, description, potential_effects, 
         severity_score, source, embedding_param))

def update_failure_mode(
    failure_mode_id: int,
    description: Optional[str] = None,
    potential_effects: Optional[str] = None,
    severity_score: Optional[int] = None
) -> None:
    """Update failure mode"""
    updates = []
    params = []
    
    if description is not None:
        updates.append("description = %s")
        params.append(description)
    if potential_effects is not None:
        updates.append("potential_effects = %s")
        params.append(potential_effects)
    if severity_score is not None:
        updates.append("severity_score = %s")
        params.append(severity_score)
    
    if not updates:
        return
    
    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(failure_mode_id)
    
    query = f"UPDATE failure_mode SET {', '.join(updates)} WHERE id = %s"
    execute_query(query, tuple(params))

def search_similar_failure_modes(
    embedding: List[float],
    domain: Optional[str] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """Search for similar failure modes by embedding"""
    additional = ""
    params = None
    
    if domain:
        additional = "AND ps.domain = %s"
        params = (domain,)
    
    embedding_str = "[" + ",".join(map(str, embedding)) + "]"
    
    query = f"""
        SELECT fm.*, ps.domain, ps.system_function,
               1 - (fm.description_embedding <=> %s::vector) as similarity
        FROM failure_mode fm
        JOIN product_system ps ON fm.product_system_id = ps.id
        WHERE fm.description_embedding IS NOT NULL
        {additional}
        ORDER BY fm.description_embedding <=> %s::vector
        LIMIT %s
    """
    
    if params:
        query_params = [embedding_str] + list(params) + [embedding_str, limit]
    else:
        query_params = [embedding_str, embedding_str, limit]
    
    return fetch_all(query, tuple(query_params) if query_params else ())

# ============================================================================
# FAILURE CAUSE QUERIES
# ============================================================================

def get_failure_cause(cause_id: int) -> Optional[Dict[str, Any]]:
    """Fetch failure cause by ID"""
    query = "SELECT * FROM failure_cause WHERE id = %s"
    return fetch_one(query, (cause_id,))

def get_failure_causes(failure_mode_id: int) -> List[Dict[str, Any]]:
    """Fetch all causes for a failure mode"""
    query = """
        SELECT * FROM failure_cause 
        WHERE failure_mode_id = %s 
        ORDER BY created_at DESC
    """
    return fetch_all(query, (failure_mode_id,))

def create_failure_cause(
    failure_mode_id: int,
    cause_description: str,
    ishikawa_category: Optional[str] = None,
    occurrence_score: int = 5,
    embedding: Optional[List[float]] = None
) -> int:
    """Create new failure cause, return ID"""
    embedding_param = None
    if embedding:
        embedding_param = "[" + ",".join(map(str, embedding)) + "]"
    
    query = """
        INSERT INTO failure_cause 
        (failure_mode_id, cause_description, ishikawa_category, occurrence_score, cause_embedding)
        VALUES (%s, %s, %s, %s, %s)
    """
    return insert_and_return_id(query, 
        (failure_mode_id, cause_description, ishikawa_category, occurrence_score, embedding_param))

def update_failure_cause(
    cause_id: int,
    cause_description: Optional[str] = None,
    occurrence_score: Optional[int] = None,
    ishikawa_category: Optional[str] = None
) -> None:
    """Update failure cause"""
    updates = []
    params = []
    
    if cause_description is not None:
        updates.append("cause_description = %s")
        params.append(cause_description)
    if occurrence_score is not None:
        updates.append("occurrence_score = %s")
        params.append(occurrence_score)
    if ishikawa_category is not None:
        updates.append("ishikawa_category = %s")
        params.append(ishikawa_category)
    
    if not updates:
        return
    
    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(cause_id)
    
    query = f"UPDATE failure_cause SET {', '.join(updates)} WHERE id = %s"
    execute_query(query, tuple(params))

# ============================================================================
# CURRENT CONTROL QUERIES
# ============================================================================

def get_current_control(control_id: int) -> Optional[Dict[str, Any]]:
    """Fetch current control by ID"""
    query = "SELECT * FROM current_control WHERE id = %s"
    return fetch_one(query, (control_id,))

def get_current_controls(cause_id: int) -> List[Dict[str, Any]]:
    """Fetch all controls for a cause"""
    query = """
        SELECT * FROM current_control 
        WHERE failure_cause_id = %s 
        ORDER BY created_at DESC
    """
    return fetch_all(query, (cause_id,))

def create_current_control(
    cause_id: int,
    control_description: str,
    control_type: str,
    detection_score: int = 5
) -> int:
    """Create new control, return ID"""
    query = """
        INSERT INTO current_control (failure_cause_id, control_description, control_type, detection_score)
        VALUES (%s, %s, %s, %s)
    """
    return insert_and_return_id(query, (cause_id, control_description, control_type, detection_score))

# ============================================================================
# RISK SCORE QUERIES
# ============================================================================

def get_risk_score(cause_id: int, is_current: bool = True) -> Optional[Dict[str, Any]]:
    """Fetch risk score for a cause"""
    query = """
        SELECT * FROM risk_score 
        WHERE failure_cause_id = %s AND is_current_state = %s
    """
    return fetch_one(query, (cause_id, is_current))

def create_risk_score(
    cause_id: int,
    severity: int,
    occurrence: int,
    detection: int,
    action_priority: Optional[str] = None
) -> int:
    """Create risk score, return ID"""
    query = """
        INSERT INTO risk_score (failure_cause_id, severity, occurrence, detection, action_priority)
        VALUES (%s, %s, %s, %s, %s)
    """
    return insert_and_return_id(query, (cause_id, severity, occurrence, detection, action_priority))

def calculate_rpn(severity: int, occurrence: int, detection: int) -> int:
    """Calculate RPN = S × O × D"""
    return severity * occurrence * detection

def get_high_priority_failures(fmea_id: int, rpn_threshold: int = 100) -> List[Dict[str, Any]]:
    """Get all failure causes above RPN threshold"""
    query = """
        SELECT fm.description, fc.cause_description, rs.severity, rs.occurrence, 
               rs.detection, rs.rpn, rs.action_priority
        FROM risk_score rs
        JOIN failure_cause fc ON rs.failure_cause_id = fc.id
        JOIN failure_mode fm ON fc.failure_mode_id = fm.id
        WHERE fm.fmea_record_id = %s AND rs.rpn >= %s AND rs.is_current_state = TRUE
        ORDER BY rs.rpn DESC
    """
    return fetch_all(query, (fmea_id, rpn_threshold))

# ============================================================================
# MITIGATION ACTION QUERIES
# ============================================================================

def get_mitigation_action(action_id: int) -> Optional[Dict[str, Any]]:
    """Fetch mitigation action by ID"""
    query = "SELECT * FROM mitigation_action WHERE id = %s"
    return fetch_one(query, (action_id,))

def get_mitigation_actions(cause_id: int) -> List[Dict[str, Any]]:
    """Fetch all actions for a cause"""
    query = """
        SELECT * FROM mitigation_action 
        WHERE failure_cause_id = %s 
        ORDER BY status, target_date
    """
    return fetch_all(query, (cause_id,))

def get_fmea_actions(fmea_id: int) -> List[Dict[str, Any]]:
    """Fetch all actions for an FMEA"""
    query = """
        SELECT ma.* FROM mitigation_action ma
        JOIN failure_cause fc ON ma.failure_cause_id = fc.id
        JOIN failure_mode fm ON fc.failure_mode_id = fm.id
        WHERE fm.fmea_record_id = %s
        ORDER BY ma.status, ma.target_date
    """
    return fetch_all(query, (fmea_id,))

def create_mitigation_action(
    cause_id: int,
    action_description: str,
    action_type: Optional[str] = None,
    responsibility: Optional[str] = None,
    target_date: Optional[str] = None,
    embedding: Optional[List[float]] = None
) -> int:
    """Create mitigation action, return ID"""
    embedding_param = None
    if embedding:
        embedding_param = "[" + ",".join(map(str, embedding)) + "]"
    
    query = """
        INSERT INTO mitigation_action 
        (failure_cause_id, action_description, action_type, responsibility, target_date, action_embedding)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    return insert_and_return_id(query, 
        (cause_id, action_description, action_type, responsibility, target_date, embedding_param))

def update_mitigation_action(
    action_id: int,
    action_description: Optional[str] = None,
    status: Optional[str] = None,
    responsibility: Optional[str] = None
) -> None:
    """Update mitigation action"""
    updates = []
    params = []
    
    if action_description is not None:
        updates.append("action_description = %s")
        params.append(action_description)
    if status is not None:
        updates.append("status = %s")
        params.append(status)
    if responsibility is not None:
        updates.append("responsibility = %s")
        params.append(responsibility)
    
    if not updates:
        return
    
    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(action_id)
    
    query = f"UPDATE mitigation_action SET {', '.join(updates)} WHERE id = %s"
    execute_query(query, tuple(params))

def search_similar_mitigation_actions(
    embedding: List[float],
    domain: Optional[str] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """Search for similar mitigation actions by embedding"""
    additional = ""
    params = None
    
    embedding_str = "[" + ",".join(map(str, embedding)) + "]"
    
    query = f"""
        SELECT DISTINCT ma.action_description, ma.action_type, pars.effectiveness_rating,
               1 - (ma.action_embedding <=> %s::vector) as similarity
        FROM mitigation_action ma
        LEFT JOIN post_action_risk_score pars ON ma.id = pars.mitigation_action_id
        WHERE ma.action_embedding IS NOT NULL
        {additional}
        ORDER BY ma.action_embedding <=> %s::vector
        LIMIT %s
    """
    
    query_params = [embedding_str, embedding_str, limit]
    
    return fetch_all(query, tuple(query_params))

def create_post_action_risk_score(
    action_id: int,
    cause_id: int,
    new_severity: Optional[int] = None,
    new_occurrence: Optional[int] = None,
    new_detection: Optional[int] = None,
    effectiveness_rating: Optional[int] = None
) -> int:
    """Create post-action risk score, return ID"""
    query = """
        INSERT INTO post_action_risk_score 
        (mitigation_action_id, failure_cause_id, new_severity, new_occurrence, new_detection, effectiveness_rating)
        VALUES (%s, %s, %s, %s, %s, %s)
    """
    return insert_and_return_id(query, 
        (action_id, cause_id, new_severity, new_occurrence, new_detection, effectiveness_rating))

# ============================================================================
# EXPERT PROFILE QUERIES
# ============================================================================

def get_expert(expert_id: int) -> Optional[Dict[str, Any]]:
    """Fetch expert profile by ID"""
    query = "SELECT * FROM expert_profile WHERE id = %s"
    return fetch_one(query, (expert_id,))

def get_all_experts() -> List[Dict[str, Any]]:
    """Fetch all expert profiles"""
    query = "SELECT * FROM expert_profile ORDER BY name"
    return fetch_all(query)

def get_experts_by_ids(expert_ids: List[int]) -> List[Dict[str, Any]]:
    """Fetch experts by ID list"""
    if not expert_ids:
        return []
    
    placeholders = ",".join(["%s"] * len(expert_ids))
    query = f"SELECT * FROM expert_profile WHERE id IN ({placeholders}) ORDER BY name"
    return fetch_all(query, tuple(expert_ids))

def create_expert(
    name: str,
    email: Optional[str] = None,
    department: Optional[str] = None,
    expertise: Optional[str] = None,
    skills_embedding: Optional[List[float]] = None
) -> int:
    """Create expert profile, return ID"""
    embedding_param = None
    if skills_embedding:
        embedding_param = "[" + ",".join(map(str, skills_embedding)) + "]"
    
    query = """
        INSERT INTO expert_profile (name, email, department, expertise, skills_embedding)
        VALUES (%s, %s, %s, %s, %s)
    """
    return insert_and_return_id(query, (name, email, department, expertise, embedding_param))

def search_experts_by_skills(
    skills_embedding: List[float],
    limit: int = 5
) -> List[Dict[str, Any]]:
    """Search for experts by skill similarity"""
    embedding_str = "[" + ",".join(map(str, skills_embedding)) + "]"
    
    query = f"""
        SELECT *,
               1 - (skills_embedding <=> %s::vector) as skill_similarity
        FROM expert_profile
        WHERE skills_embedding IS NOT NULL
        ORDER BY skills_embedding <=> %s::vector
        LIMIT %s
    """
    
    return fetch_all(query, (embedding_str, embedding_str, limit))

# ============================================================================
# HISTORICAL FMEA QUERIES
# ============================================================================

def get_historical_fmea(fmea_id: int) -> Optional[Dict[str, Any]]:
    """Fetch historical FMEA record"""
    query = "SELECT * FROM historical_fmea WHERE id = %s"
    return fetch_one(query, (fmea_id,))

def get_historical_fmeas(domain: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch historical FMEAs, optionally filtered by domain"""
    if domain:
        query = "SELECT * FROM historical_fmea WHERE domain = %s ORDER BY created_at DESC"
        return fetch_all(query, (domain,))
    else:
        query = "SELECT * FROM historical_fmea ORDER BY created_at DESC"
        return fetch_all(query)

def create_historical_fmea(
    domain: str,
    system_function: str,
    product_name: Optional[str] = None,
    lessons_learned: Optional[str] = None,
    summary_embedding: Optional[List[float]] = None
) -> int:
    """Create historical FMEA record, return ID"""
    embedding_param = None
    if summary_embedding:
        embedding_param = "[" + ",".join(map(str, summary_embedding)) + "]"
    
    query = """
        INSERT INTO historical_fmea (domain, system_function, product_name, lessons_learned, summary_embedding)
        VALUES (%s, %s, %s, %s, %s)
    """
    return insert_and_return_id(query, 
        (domain, system_function, product_name, lessons_learned, embedding_param))

def search_similar_historical_fmeas(
    embedding: List[float],
    limit: int = 3
) -> List[Dict[str, Any]]:
    """Search for similar historical FMEAs by embedding"""
    embedding_str = "[" + ",".join(map(str, embedding)) + "]"
    
    query = f"""
        SELECT *,
               1 - (summary_embedding <=> %s::vector) as similarity
        FROM historical_fmea
        WHERE summary_embedding IS NOT NULL
        ORDER BY summary_embedding <=> %s::vector
        LIMIT %s
    """
    
    return fetch_all(query, (embedding_str, embedding_str, limit))

# ============================================================================
# RISK FACTOR & STANDARDS QUERIES
# ============================================================================

def get_risk_factors() -> List[Dict[str, Any]]:
    """Fetch all risk factors"""
    query = "SELECT * FROM risk_factor ORDER BY factor_type, name"
    return fetch_all(query)

def get_risk_factor_by_type(factor_type: str) -> Optional[Dict[str, Any]]:
    """Fetch risk factor by type"""
    query = "SELECT * FROM risk_factor WHERE factor_type = %s"
    return fetch_one(query, (factor_type,))

def get_organizational_standards(domain: str) -> List[Dict[str, Any]]:
    """Fetch organizational standards for a domain"""
    query = """
        SELECT * FROM organizational_standard 
        WHERE domain = %s 
        ORDER BY risk_factor_id
    """
    return fetch_all(query, (domain,))