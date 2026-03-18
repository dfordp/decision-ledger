"""
Embedding service using OpenAI text-embedding-3-small for FMEA.
Generates 1536-dimensional vectors for semantic similarity search.
"""

import os
from typing import List, Optional
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536

# ============================================================================
# CORE EMBEDDING FUNCTION
# ============================================================================

def generate_embedding(text: str) -> List[float]:
    """
    Generate embedding vector for given text.
    
    Args:
        text: Text to embed (should be meaningful context, not just numbers)
    
    Returns:
        1536-dimensional vector as list of floats
    
    Raises:
        ValueError: If text is empty
    """
    if not text or not text.strip():
        raise ValueError("Cannot generate embedding for empty text")
    
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text.strip()
    )
    
    return response.data[0].embedding

# ============================================================================
# FAILURE MODE EMBEDDINGS
# ============================================================================

def generate_failure_mode_embedding(
    description: str,
    mode_type: str,
    potential_effects: Optional[str] = None,
    system_function: Optional[str] = None
) -> List[float]:
    """
    Generate embedding for failure mode.
    Captures what can go wrong and its consequences.
    
    Args:
        description: Description of the failure mode
        mode_type: Type of failure (no_function, partial_function, intermittent, unintended)
        potential_effects: What happens if failure occurs
        system_function: What the system is supposed to do
    
    Returns:
        1536-dimensional embedding vector
    """
    text = f"""
    Failure mode: {description}
    Type: {mode_type}
    """
    
    if system_function:
        text += f"\nSystem function: {system_function}"
    
    if potential_effects:
        text += f"\nPotential effects: {potential_effects}"
    
    return generate_embedding(text)

# ============================================================================
# FAILURE CAUSE EMBEDDINGS
# ============================================================================

def generate_failure_cause_embedding(
    cause_description: str,
    ishikawa_category: Optional[str] = None,
    failure_mode: Optional[str] = None
) -> List[float]:
    """
    Generate embedding for failure cause.
    Captures root cause and failure mode context.
    
    Args:
        cause_description: Description of the root cause
        ishikawa_category: Category from Ishikawa diagram (materials, methods, machines, etc.)
        failure_mode: The failure mode this causes
    
    Returns:
        1536-dimensional embedding vector
    """
    text = f"Root cause: {cause_description}"
    
    if ishikawa_category:
        text += f"\nCategory: {ishikawa_category}"
    
    if failure_mode:
        text += f"\nCaused by: {failure_mode}"
    
    return generate_embedding(text)

# ============================================================================
# MITIGATION ACTION EMBEDDINGS
# ============================================================================

def generate_mitigation_action_embedding(
    action_description: str,
    action_type: Optional[str] = None,
    failure_mode: Optional[str] = None,
    root_cause: Optional[str] = None
) -> List[float]:
    """
    Generate embedding for mitigation action.
    Captures the remedy and what it addresses.
    
    Args:
        action_description: Description of the mitigation action
        action_type: Type of action (prevention, detection, both)
        failure_mode: The failure mode being addressed
        root_cause: The root cause being addressed
    
    Returns:
        1536-dimensional embedding vector
    """
    text = f"Mitigation action: {action_description}"
    
    if action_type:
        text += f"\nAction type: {action_type}"
    
    if failure_mode:
        text += f"\nAddresses failure: {failure_mode}"
    
    if root_cause:
        text += f"\nAddresses cause: {root_cause}"
    
    return generate_embedding(text)

# ============================================================================
# SYSTEM & FUNCTION EMBEDDINGS
# ============================================================================

def generate_system_function_embedding(
    system_name: str,
    system_function: str,
    domain: Optional[str] = None,
    scope: Optional[str] = None
) -> List[float]:
    """
    Generate embedding for product system function.
    Captures what the system does and its context.
    
    Args:
        system_name: Name of the product/system
        system_function: Primary function of the system
        domain: Domain (automotive, medical, manufacturing, etc.)
        scope: What's included/excluded from analysis
    
    Returns:
        1536-dimensional embedding vector
    """
    text = f"""
    System: {system_name}
    Function: {system_function}
    """
    
    if domain:
        text += f"\nDomain: {domain}"
    
    if scope:
        text += f"\nScope: {scope}"
    
    return generate_embedding(text)

# ============================================================================
# EXPERT SKILL EMBEDDINGS
# ============================================================================

def generate_expert_skills_embedding(
    skills: List[str],
    department: Optional[str] = None,
    expertise_summary: Optional[str] = None
) -> List[float]:
    """
    Generate embedding for expert profile skills.
    Used for matching experts to FMEA needs.
    
    Args:
        skills: List of skill tags (e.g., ["design", "testing", "hydraulics"])
        department: Department/function of the expert
        expertise_summary: Brief text summary of expertise
    
    Returns:
        1536-dimensional embedding vector
    """
    skills_text = ", ".join(skills) if skills else "no skills listed"
    
    text = f"Expert skills: {skills_text}"
    
    if department:
        text += f"\nDepartment: {department}"
    
    if expertise_summary:
        text += f"\nExpertise: {expertise_summary}"
    
    return generate_embedding(text)

# ============================================================================
# RISK & RPN CONTEXT EMBEDDINGS
# ============================================================================

def generate_risk_context_embedding(
    failure_mode: str,
    root_cause: str,
    severity: int = 5,
    occurrence: int = 5,
    detection: int = 5,
    domain: Optional[str] = None
) -> List[float]:
    """
    Generate embedding for risk assessment context.
    Captures failure, cause, and risk scores together.
    
    Args:
        failure_mode: Description of the failure mode
        root_cause: Description of the root cause
        severity: Severity score (1-10)
        occurrence: Occurrence score (1-10)
        detection: Detection score (1-10)
        domain: Domain context
    
    Returns:
        1536-dimensional embedding vector
    """
    rpn = severity * occurrence * detection
    
    text = f"""
    Failure: {failure_mode}
    Cause: {root_cause}
    Risk: Severity={severity}, Occurrence={occurrence}, Detection={detection}, RPN={rpn}
    """
    
    if domain:
        text += f"Domain: {domain}\n"
    
    return generate_embedding(text)

# ============================================================================
# HISTORICAL FMEA EMBEDDINGS
# ============================================================================

def generate_historical_fmea_embedding(
    system_function: str,
    domain: str,
    key_failures: List[str],
    lessons_learned: Optional[str] = None,
    product_name: Optional[str] = None
) -> List[float]:
    """
    Generate embedding for historical FMEA record.
    Used to find similar past analyses.
    
    Args:
        system_function: What the system does
        domain: Domain (automotive, medical, etc.)
        key_failures: List of important failure modes discovered
        lessons_learned: AI-extracted lessons and patterns
        product_name: Name of the product analyzed
    
    Returns:
        1536-dimensional embedding vector
    """
    failures_text = "; ".join(key_failures[:5]) if key_failures else "failure modes"
    
    text = f"""
    Historical FMEA for: {product_name if product_name else 'similar system'}
    Function: {system_function}
    Domain: {domain}
    Key failures: {failures_text}
    """
    
    if lessons_learned:
        text += f"\nLessons learned: {lessons_learned[:500]}"  # First 500 chars
    
    return generate_embedding(text)

# ============================================================================
# HELPER FUNCTIONS FOR BATCH EMBEDDINGS
# ============================================================================

def generate_batch_embeddings(text_list: List[str]) -> List[List[float]]:
    """
    Generate embeddings for multiple texts (more efficient than individual calls).
    
    Args:
        text_list: List of texts to embed
    
    Returns:
        List of embedding vectors
    """
    if not text_list:
        return []
    
    # Filter out empty strings
    valid_texts = [t.strip() for t in text_list if t and t.strip()]
    
    if not valid_texts:
        raise ValueError("No valid text to embed")
    
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=valid_texts
    )
    
    # Map results back to original order
    embeddings_dict = {data.index: data.embedding for data in response.data}
    return [embeddings_dict.get(i, [0.0] * EMBEDDING_DIMENSION) for i in range(len(valid_texts))]

# ============================================================================
# ISHIKAWA DIAGRAM EMBEDDING (for cause categorization)
# ============================================================================

def generate_ishikawa_category_embedding(
    category: str,
    causes: List[str]
) -> List[float]:
    """
    Generate embedding for an Ishikawa diagram category of causes.
    
    Args:
        category: Category name (materials, methods, machines, maintenance, measurements, environment, management)
        causes: List of causes in this category
    
    Returns:
        1536-dimensional embedding vector
    """
    causes_text = "; ".join(causes[:10]) if causes else "no causes identified"
    
    text = f"""
    Ishikawa category: {category}
    Causes: {causes_text}
    """
    
    return generate_embedding(text)

# ============================================================================
# VALIDATION & HEALTH CHECKS
# ============================================================================

def test_embedding_service() -> bool:
    """
    Test that the embedding service is working.
    
    Returns:
        True if service is working, False otherwise
    """
    try:
        embedding = generate_embedding("test")
        return (
            len(embedding) == EMBEDDING_DIMENSION and
            all(isinstance(x, float) for x in embedding)
        )
    except Exception as e:
        print(f"Embedding service error: {e}")
        return False

def get_embedding_dimension() -> int:
    """Get the dimension of embeddings (typically 1536)"""
    return EMBEDDING_DIMENSION

def get_embedding_model() -> str:
    """Get the name of the embedding model"""
    return EMBEDDING_MODEL