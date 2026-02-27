"""
Embedding service using OpenAI text-embedding-3-small.
Generates 1536-dimensional vectors for semantic similarity search.
"""

import os
from typing import List
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536

def generate_embedding(text: str) -> List[float]:
    """
    Generate embedding vector for given text.
    
    Args:
        text: Text to embed (should be meaningful context, not just numbers)
    
    Returns:
        1536-dimensional vector as list of floats
    """
    if not text or not text.strip():
        raise ValueError("Cannot generate embedding for empty text")
    
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text.strip()
    )
    
    return response.data[0].embedding

def generate_policy_embedding(
    dimension_name: str,
    domain: str,
    min_value: float,
    max_value: float,
    flexibility: str,
    notes: str = ""
) -> List[float]:
    """
    Generate embedding for vendor policy.
    Focuses on constraints and context rather than just numbers.
    """
    text = f"""
    Vendor policy for {dimension_name} in {domain} domain.
    Acceptable range: {min_value} to {max_value}.
    Flexibility level: {flexibility}.
    {notes}
    """
    return generate_embedding(text)

def generate_proposal_embedding(
    tender_name: str,
    domain: str,
    outcome: str,
    outcome_reason: str = ""
) -> List[float]:
    """
    Generate embedding for overall proposal.
    Captures tender context and outcome.
    """
    text = f"""
    Proposal for {tender_name} tender in {domain} domain.
    Outcome: {outcome}.
    {outcome_reason}
    """
    return generate_embedding(text)

def generate_decision_embedding(
    dimension_name: str,
    offered_value: float,
    justification: str,
    domain: str,
    outcome: str,
    source_excerpt: str = ""
) -> List[float]:
    """
    Generate embedding for proposal decision.
    This is the MOST IMPORTANT embedding for similarity search.
    
    Includes:
    - What dimension
    - What value was offered
    - Why that value was chosen
    - What domain/context
    - What was the outcome
    - Direct quote from decision process
    """
    text = f"""
    {dimension_name} decision for {domain} tender.
    Offered value: {offered_value}.
    Justification: {justification}
    Outcome: {outcome}.
    {source_excerpt}
    """
    return generate_embedding(text)

def generate_requirement_embedding(
    dimension_name: str,
    required_value: float,
    strictness: str,
    domain: str,
    description: str = ""
) -> List[float]:
    """
    Generate embedding for tender requirement.
    Captures what the client is asking for.
    """
    text = f"""
    Tender requirement for {dimension_name} in {domain} domain.
    Required value: {required_value}.
    Strictness: {strictness}.
    {description}
    """
    return generate_embedding(text)