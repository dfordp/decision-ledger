"""
Core reasoning engine for DecisionLedger.
Performs vector similarity search, applies deterministic policy rules,
and uses Groq for natural language explanations.
"""

from typing import List, Dict, Any, Tuple
from decimal import Decimal
import os
from groq import Groq

from app.database import (
    fetch_one, fetch_all, vector_search, 
    get_dimension_id, get_vendor_id
)
from app.models import (
    ReasoningResult, TenderRequirement, VendorPolicy,
    EvidenceItem, Literal
)
from app.embeddings import generate_requirement_embedding

# Initialize Groq client
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def get_tender_requirement(tender_id: int, dimension_key: str) -> TenderRequirement:
    """Fetch tender requirement for specific dimension"""
    dimension_id = get_dimension_id(dimension_key)
    
    query = """
        SELECT 
            tr.*,
            ed.key as dimension_key,
            ed.display_name as dimension_name,
            ed.unit as dimension_unit
        FROM tender_requirements tr
        JOIN evaluation_dimension ed ON tr.dimension_id = ed.id
        WHERE tr.tender_id = %s AND tr.dimension_id = %s
    """
    
    result = fetch_one(query, (tender_id, dimension_id))
    
    if not result:
        raise ValueError(f"No requirement found for tender {tender_id}, dimension {dimension_key}")
    
    return TenderRequirement(**result)

def get_vendor_policy(dimension_key: str, domain: str) -> VendorPolicy:
    """
    Get vendor policy for dimension and domain.
    Falls back to GLOBAL if domain-specific policy not found.
    """
    vendor_id = get_vendor_id()
    dimension_id = get_dimension_id(dimension_key)
    
    # Try domain-specific policy first
    query = """
        SELECT 
            vp.*,
            ed.key as dimension_key,
            ed.display_name as dimension_name
        FROM vendor_policy vp
        JOIN evaluation_dimension ed ON vp.dimension_id = ed.id
        WHERE vp.vendor_id = %s 
        AND vp.dimension_id = %s 
        AND vp.domain = %s
    """
    
    policy = fetch_one(query, (vendor_id, dimension_id, domain))
    
    # Fallback to GLOBAL
    if not policy:
        policy = fetch_one(query, (vendor_id, dimension_id, 'GLOBAL'))
    
    if not policy:
        raise ValueError(f"No policy found for dimension {dimension_key}")
    
    return VendorPolicy(**policy)

def find_similar_decisions(
    requirement: TenderRequirement,
    domain: str,
    limit: int = 5
) -> List[EvidenceItem]:
    """
    Find similar past decisions using vector similarity search.
    Returns most similar decisions with context.
    """
    # Generate embedding for the requirement
    requirement_embedding = generate_requirement_embedding(
        dimension_name=requirement.dimension_name,
        required_value=float(requirement.required_value),
        strictness=requirement.strictness,
        domain=domain,
        description=requirement.description or ""
    )
    
    # Vector search on proposal_decisions table
    similar_decisions = vector_search(
        table="v_proposal_decisions_detail",
        embedding_column="embedding",
        query_embedding=requirement_embedding,
        limit=limit,
        additional_conditions="AND dimension_id = %s",
        params=(requirement.dimension_id,)
    )
    
    # Convert to EvidenceItem models
    evidence = []
    for decision in similar_decisions:
        evidence.append(EvidenceItem(
            proposal_id=decision['proposal_id'],
            tender_name=decision['tender_name'],
            domain=decision['domain'],
            outcome=decision['outcome'],
            submitted_at=decision['submitted_at'],
            offered_value=decision['offered_value'],
            justification=decision['justification'],
            source_excerpt=decision['source_excerpt'],
            similarity=float(decision['similarity'])
        ))
    
    return evidence

def apply_deterministic_rules(
    requirement: TenderRequirement,
    policy: VendorPolicy,
    evidence: List[EvidenceItem]
) -> Tuple[str, float, Decimal]:
    """
    Apply deterministic rules to determine status and recommended value.
    
    Returns:
        (status, confidence, recommended_value)
    
    Rules:
    1. If required_value > policy.max_value AND strictness=mandatory AND flexibility=fixed → BLOCK
    2. If required_value < policy.min_value AND strictness=mandatory AND flexibility=fixed → BLOCK
    3. If required_value outside bounds AND strictness=mandatory AND flexibility=negotiable → WARN
    4. If similar past decisions were REJECTED → WARN (lower confidence)
    5. If requirement within bounds → SAFE
    """
    
    required_val = float(requirement.required_value)
    min_val = float(policy.min_value)
    max_val = float(policy.max_value)
    default_val = float(policy.default_value) if policy.default_value else (min_val + max_val) / 2
    
    status = "SAFE"
    confidence = 0.8
    recommended_value = Decimal(str(default_val))
    
    # Rule 1 & 2: Hard policy violations with no flexibility
    if policy.flexibility == "fixed":
        if requirement.strictness == "mandatory":
            if required_val > max_val or required_val < min_val:
                status = "BLOCK"
                confidence = 0.95
                recommended_value = policy.max_value if required_val > max_val else policy.min_value
                return (status, confidence, recommended_value)
    
    # Rule 3: Outside bounds but negotiable
    if required_val > max_val or required_val < min_val:
        if requirement.strictness == "mandatory":
            if policy.flexibility == "negotiable":
                status = "WARN"
                confidence = 0.5
                # Try to meet requirement but flag as risky
                if required_val > max_val:
                    recommended_value = Decimal(str(max_val * 1.1))  # Stretch 10%
                else:
                    recommended_value = Decimal(str(min_val * 0.9))  # Stretch 10%
            elif policy.flexibility == "flexible":
                status = "SAFE"
                confidence = 0.6
                recommended_value = requirement.required_value
        else:  # preferred requirement
            status = "SAFE"
            confidence = 0.7
            # Use policy default for preferred requirements
            recommended_value = policy.default_value or policy.max_value
    else:
        # Within bounds
        status = "SAFE"
        confidence = 0.85
        
        # Try to match requirement if within bounds
        if min_val <= required_val <= max_val:
            recommended_value = requirement.required_value
        else:
            recommended_value = policy.default_value or Decimal(str(default_val))
    
    # Rule 4: Adjust based on historical evidence
    if evidence:
        rejected_count = sum(1 for e in evidence if e.outcome == "REJECTED")
        lost_count = sum(1 for e in evidence if e.outcome == "LOST")
        won_count = sum(1 for e in evidence if e.outcome == "WON")
        
        # REJECTED means WE declined - strong negative signal
        if rejected_count > 0:
            if status == "SAFE":
                status = "WARN"
            confidence *= 0.7  # Reduce confidence
        
        # LOST means client rejected us - moderate negative signal
        if lost_count > won_count and lost_count > 0:
            confidence *= 0.85
        
        # Multiple WON increases confidence
        if won_count >= 2:
            confidence = min(0.95, confidence * 1.1)
        
        # If similar past decisions offered similar values, use that pattern
        if won_count > 0:
            similar_won_decisions = [e for e in evidence if e.outcome == "WON"]
            if similar_won_decisions:
                avg_won_value = sum(float(e.offered_value) for e in similar_won_decisions) / len(similar_won_decisions)
                # If requirement is close to what we won with before, recommend that
                if abs(required_val - avg_won_value) / avg_won_value < 0.15:  # Within 15%
                    recommended_value = Decimal(str(avg_won_value))
    
    return (status, confidence, recommended_value)

def generate_reasoning_explanation(
    requirement: TenderRequirement,
    policy: VendorPolicy,
    evidence: List[EvidenceItem],
    status: str,
    recommended_value: Decimal,
    confidence: float
) -> List[str]:
    """
    Use Groq to generate natural language reasoning bullets.
    This is the ONLY place we use LLM - for explanation, not decision-making.
    """
    
    # Build context for LLM
    evidence_summary = []
    for e in evidence[:3]:  # Top 3 most similar
        evidence_summary.append(
            f"- {e.outcome}: {e.tender_name} ({e.domain}) offered {e.offered_value} {requirement.dimension_unit}"
        )
    
    evidence_text = "\n".join(evidence_summary) if evidence_summary else "No similar past decisions found."
    
    prompt = f"""You are explaining a tender evaluation decision to a business user.

Dimension: {requirement.dimension_name}
Requirement: {requirement.required_value} {requirement.dimension_unit} ({requirement.strictness})
Our Policy: {policy.min_value}-{policy.max_value} {requirement.dimension_unit} (flexibility: {policy.flexibility})
Domain: {policy.domain}

Recommendation: {recommended_value} {requirement.dimension_unit}
Status: {status}
Confidence: {confidence:.0%}

Similar Past Decisions:
{evidence_text}

Provide exactly 3 short bullet points explaining WHY this recommendation makes sense.
Focus on:
1. How requirement compares to policy
2. What past experience shows
3. Key risk or opportunity

Keep bullets concise and business-focused. Do not repeat the numbers already shown.
Format as simple bullets without markdown."""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are a business analyst explaining tender decisions. Be concise and factual."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=300
        )
        
        explanation = response.choices[0].message.content.strip()
        
        # Parse bullets (remove markdown if present)
        bullets = []
        for line in explanation.split('\n'):
            line = line.strip()
            if line and (line.startswith('-') or line.startswith('•') or line.startswith('*')):
                bullets.append(line.lstrip('-•* ').strip())
            elif line and len(bullets) < 3:
                bullets.append(line)
        
        # Ensure we have 3 bullets
        while len(bullets) < 3:
            bullets.append("No additional insights available.")
        
        return bullets[:3]
        
    except Exception as e:
        # Fallback to simple rules-based explanation if Groq fails
        print(f"Groq API failed: {e}")
        return generate_fallback_explanation(requirement, policy, evidence, status, recommended_value)

def generate_fallback_explanation(
    requirement: TenderRequirement,
    policy: VendorPolicy,
    evidence: List[EvidenceItem],
    status: str,
    recommended_value: Decimal
) -> List[str]:
    """Fallback explanation if Groq API is unavailable"""
    
    bullets = []
    
    # Bullet 1: Policy comparison
    required_val = float(requirement.required_value)
    min_val = float(policy.min_value)
    max_val = float(policy.max_value)
    
    if min_val <= required_val <= max_val:
        bullets.append(f"Requirement falls within our policy range ({min_val}-{max_val} {requirement.dimension_unit})")
    elif required_val > max_val:
        bullets.append(f"Requirement exceeds our maximum policy of {max_val} {requirement.dimension_unit}")
    else:
        bullets.append(f"Requirement is below our minimum policy of {min_val} {requirement.dimension_unit}")
    
    # Bullet 2: Historical evidence
    if evidence:
        won = sum(1 for e in evidence if e.outcome == "WON")
        lost = sum(1 for e in evidence if e.outcome == "LOST")
        rejected = sum(1 for e in evidence if e.outcome == "REJECTED")
        
        if won > 0:
            bullets.append(f"Historical data shows {won} similar winning proposal(s)")
        elif rejected > 0:
            bullets.append(f"We previously rejected {rejected} similar proposal(s) - high risk")
        elif lost > 0:
            bullets.append(f"We lost {lost} similar proposal(s) - challenging requirement")
        else:
            bullets.append("Limited historical data for this scenario")
    else:
        bullets.append("No similar historical decisions found")
    
    # Bullet 3: Flexibility note
    if policy.flexibility == "fixed":
        bullets.append("Policy has limited flexibility - adherence required")
    elif policy.flexibility == "flexible":
        bullets.append("Policy allows flexibility - can accommodate variations")
    else:
        bullets.append("Policy is negotiable - some adjustment possible")
    
    return bullets

def reason_about_requirement(tender_id: int, dimension_key: str) -> ReasoningResult:
    """
    Main reasoning function - orchestrates the entire decision process.
    
    Steps:
    1. Fetch requirement and policy
    2. Find similar past decisions (vector search)
    3. Apply deterministic rules
    4. Generate explanation (Groq)
    5. Return complete reasoning result
    """
    
    # Step 1: Get requirement
    requirement = get_tender_requirement(tender_id, dimension_key)
    
    # Get tender domain for policy lookup
    tender = fetch_one("SELECT domain FROM tenders WHERE id = %s", (tender_id,))
    domain = tender['domain'] if tender else 'GLOBAL'
    
    # Step 2: Get policy (with domain fallback)
    policy = get_vendor_policy(dimension_key, domain)
    
    # Step 3: Find similar past decisions
    evidence = find_similar_decisions(requirement, domain, limit=5)
    
    # Step 4: Apply deterministic rules
    status, confidence, recommended_value = apply_deterministic_rules(
        requirement, policy, evidence
    )
    
    # Step 5: Generate natural language explanation
    reasoning = generate_reasoning_explanation(
        requirement, policy, evidence, status, recommended_value, confidence
    )
    
    # Step 6: Build result
    result = ReasoningResult(
        dimension_key=dimension_key,
        dimension_name=requirement.dimension_name,
        dimension_unit=requirement.dimension_unit,
        requirement=requirement,
        policy=policy,
        recommended_value=recommended_value,
        status=status,
        confidence=confidence,
        reasoning=reasoning,
        evidence=evidence
    )
    
    return result