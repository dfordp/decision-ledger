"""
Core reasoning engine for FMEA application.
Performs vector similarity search, risk assessment, expert matching,
and uses Groq for natural language analysis and lessons learned.
Based on AIAG-VDA FMEA 4.0 Harmonized Standard.
"""

from typing import List, Dict, Any, Optional, Tuple
import os
from groq import Groq

from app.database import (
    get_failure_mode, get_failure_cause, get_current_controls,
    get_risk_score, get_mitigation_actions,
    search_similar_failure_modes, search_similar_mitigation_actions,
    search_experts_by_skills, search_similar_historical_fmeas,
    get_organizational_standards, get_historical_fmeas,
    get_product_system
)
from app.models import (
    ReasoningResult, FailureMode, FailureCause, CurrentControl,
    RiskScore, MitigationAction, SimilarFailureMode,
    SuggestedMitigationAction, ExpertProfile
)
from app.embeddings import (
    generate_failure_mode_embedding, generate_failure_cause_embedding,
    generate_mitigation_action_embedding, generate_expert_skills_embedding,
    generate_historical_fmea_embedding
)

# Initialize Groq client
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ============================================================================
# FAILURE MODE SUGGESTIONS
# ============================================================================

def suggest_failure_modes(
    system_function: str,
    domain: str,
    product_system_id: int,
    limit: int = 10
) -> List[SimilarFailureMode]:
    """
    Suggest failure modes based on similar systems and historical data.
    Uses vector search to find failure modes from similar products.
    
    Args:
        system_function: What the system does
        domain: Domain (automotive, medical, manufacturing, etc.)
        product_system_id: Product system being analyzed
        limit: Number of suggestions to return
    
    Returns:
        List of similar failure modes with similarity scores
    """
    try:
        # Generate embedding for system function
        embedding = generate_failure_mode_embedding(
            description=system_function,
            mode_type="no_function",  # Get all modes
            system_function=system_function
        )
        
        # Search similar failure modes
        similar = search_similar_failure_modes(embedding, domain=domain, limit=limit)
        
        # Convert to model
        results = []
        for item in similar:
            results.append(SimilarFailureMode(
                failure_mode_id=item['id'],
                description=item['description'],
                domain=domain,
                system_function=system_function,
                severity_score=item.get('severity_score', 5),
                similarity_score=float(item.get('similarity', 0))
            ))
        
        return results
    
    except Exception as e:
        print(f"Error suggesting failure modes: {e}")
        return []

# ============================================================================
# EXPERT TEAM MATCHING
# ============================================================================

def suggest_team_experts(
    system_function: str,
    domain: str,
    required_skills: List[str],
    limit: int = 5
) -> List[ExpertProfile]:
    """
    Suggest expert team members based on required skills.
    Uses skill embedding similarity to match experts.
    
    Args:
        system_function: What the system does
        domain: Domain of analysis
        required_skills: List of required skill tags
        limit: Number of experts to suggest
    
    Returns:
        List of expert profiles with skill matching
    """
    try:
        # Generate embedding for required skills
        skills_text = ", ".join(required_skills)
        embedding = generate_expert_skills_embedding(
            skills=required_skills,
            expertise_summary=f"Expertise in {system_function} for {domain} domain"
        )
        
        # Search experts by skill similarity
        experts = search_experts_by_skills(embedding, limit=limit)
        
        # Convert to model
        results = []
        for expert in experts:
            results.append(ExpertProfile(
                id=expert['id'],
                name=expert['name'],
                email=expert.get('email'),
                department=expert.get('department'),
                expertise=expert.get('expertise'),
                contact_info=expert.get('contact_info')
            ))
        
        return results
    
    except Exception as e:
        print(f"Error suggesting experts: {e}")
        return []

def get_expert_role_recommendations(domain: str) -> Dict[str, List[str]]:
    """
    Get recommended expert roles for FMEA based on domain.
    
    Returns typical team composition for the domain.
    """
    domain_team_roles = {
        'automotive': [
            'design_engineer',
            'quality_engineer',
            'manufacturing_engineer',
            'supplier_quality',
            'system_engineer'
        ],
        'medical': [
            'design_engineer',
            'quality_engineer',
            'regulatory_specialist',
            'clinical_specialist',
            'manufacturing_engineer'
        ],
        'manufacturing': [
            'process_engineer',
            'quality_engineer',
            'maintenance_engineer',
            'operator_representative',
            'system_engineer'
        ]
    }
    
    return domain_team_roles.get(domain, [
        'design_engineer',
        'quality_engineer',
        'system_engineer'
    ])

# ============================================================================
# MITIGATION ACTION SUGGESTIONS
# ============================================================================

def suggest_mitigation_actions(
    failure_cause: FailureCause,
    domain: str,
    limit: int = 5
) -> List[SuggestedMitigationAction]:
    """
    Suggest mitigation actions based on similar historical causes.
    Finds actions that worked in similar situations.
    
    Args:
        failure_cause: The failure cause to mitigate
        domain: Domain of analysis
        limit: Number of suggestions to return
    
    Returns:
        List of suggested actions with effectiveness ratings
    """
    try:
        # Generate embedding for the cause
        embedding = generate_failure_cause_embedding(
            cause_description=failure_cause.cause_description,
            ishikawa_category=failure_cause.ishikawa_category
        )
        
        # Search similar mitigation actions
        similar_actions = search_similar_mitigation_actions(embedding, domain=domain, limit=limit)
        
        # Convert to model
        results = []
        for action in similar_actions:
            results.append(SuggestedMitigationAction(
                action_description=action['action_description'],
                action_type=action.get('action_type'),
                source_system=domain,
                effectiveness_rating=action.get('effectiveness_rating'),
                similarity_score=float(action.get('similarity', 0))
            ))
        
        return results
    
    except Exception as e:
        print(f"Error suggesting mitigation actions: {e}")
        return []

# ============================================================================
# RISK ASSESSMENT
# ============================================================================

def assess_risk_against_standards(
    severity: int,
    occurrence: int,
    detection: int,
    domain: str
) -> Tuple[int, str, str]:
    """
    Assess risk score against organizational standards.
    
    Args:
        severity: Severity score (1-10)
        occurrence: Occurrence score (1-10)
        detection: Detection score (1-10)
        domain: Domain for standard lookup
    
    Returns:
        (rpn: int, action_priority: str, recommendation: str)
    """
    rpn = severity * occurrence * detection
    
    # Get organizational standards for domain
    standards = get_organizational_standards(domain)
    
    # Simple AP classification (AIAG-VDA uses more complex rules)
    # High priority: RPN > 100 or any critical factor
    if rpn >= 100 or severity >= 9:
        action_priority = "high"
        recommendation = "Requires immediate action to reduce risk"
    elif rpn >= 50:
        action_priority = "medium"
        recommendation = "Action recommended to reduce risk"
    else:
        action_priority = "low"
        recommendation = "Continue monitoring; action not required"
    
    return (rpn, action_priority, recommendation)

def check_action_effectiveness(
    current_severity: int,
    current_occurrence: int,
    current_detection: int,
    post_severity: int,
    post_occurrence: int,
    post_detection: int
) -> Dict[str, Any]:
    """
    Evaluate effectiveness of mitigation action.
    
    Returns:
        Dict with before/after RPN and effectiveness metrics
    """
    current_rpn = current_severity * current_occurrence * current_detection
    post_rpn = post_severity * post_occurrence * post_detection
    
    rpn_reduction = current_rpn - post_rpn
    reduction_percent = (rpn_reduction / current_rpn * 100) if current_rpn > 0 else 0
    
    effectiveness = {
        'current_rpn': current_rpn,
        'post_rpn': post_rpn,
        'rpn_reduction': rpn_reduction,
        'reduction_percent': round(reduction_percent, 1),
        'effective': rpn_reduction > 0,
        'highly_effective': reduction_percent >= 50
    }
    
    return effectiveness

# ============================================================================
# ISHIKAWA DIAGRAM ANALYSIS
# ============================================================================

def generate_ishikawa_analysis(
    failure_mode: FailureMode,
    failure_causes: List[FailureCause]
) -> Dict[str, List[str]]:
    """
    Organize failure causes by Ishikawa (Fishbone) categories.
    
    Returns:
        Dict mapping Ishikawa categories to lists of causes
    """
    categories = {
        'materials': [],
        'methods': [],
        'machines': [],
        'maintenance': [],
        'measurements': [],
        'environment': [],
        'management': []
    }
    
    for cause in failure_causes:
        if cause.ishikawa_category and cause.ishikawa_category in categories:
            categories[cause.ishikawa_category].append(cause.cause_description)
        else:
            # Default uncategorized to methods
            categories['methods'].append(cause.cause_description)
    
    # Remove empty categories
    return {k: v for k, v in categories.items() if v}

def generate_ishikawa_prompt(
    failure_mode_description: str,
    ishikawa_analysis: Dict[str, List[str]],
    domain: str
) -> str:
    """
    Generate Ishikawa diagram context for Groq analysis.
    """
    categories_text = []
    for category, causes in ishikawa_analysis.items():
        causes_list = "\n        ".join(causes)
        categories_text.append(f"{category.upper()}:\n        {causes_list}")
    
    return f"""
Failure Mode: {failure_mode_description}
Domain: {domain}

Root Causes by Ishikawa Category:
{chr(10).join(categories_text)}
"""

# ============================================================================
# LESSONS LEARNED EXTRACTION
# ============================================================================

def extract_lessons_learned(
    domain: str,
    top_failures: List[Dict[str, Any]],
    historical_fmeas: List[Dict[str, Any]] = None
) -> str:
    """
    Use Groq to extract insights and lessons learned from historical FMEAs.
    
    Args:
        domain: Domain for context
        top_failures: High-priority failures to learn from
        historical_fmeas: Historical FMEA records for pattern analysis
    
    Returns:
        AI-generated lessons learned summary
    """
    
    if historical_fmeas is None:
        historical_fmeas = get_historical_fmeas(domain)
    
    # Prepare context for Groq
    failure_context = "\n".join([
        f"- {f.get('description', 'Unknown')}: S={f.get('severity', 5)}, "
        f"O={f.get('occurrence', 5)}, D={f.get('detection', 5)}"
        for f in top_failures[:5]
    ])
    
    historical_context = ""
    if historical_fmeas:
        historical_context = "\n".join([
            f"- {h.get('product_name', 'Product')}: {h.get('lessons_learned', 'No lessons recorded')[:100]}"
            for h in historical_fmeas[:3]
        ])
    
    prompt = f"""Based on FMEA analysis in the {domain} domain, extract key lessons learned.

Current High-Priority Failure Modes:
{failure_context}

Historical Patterns from Similar FMEAs:
{historical_context if historical_context else 'No historical data available'}

Generate 3-4 key insights about:
1. Recurring patterns or common failure modes in this domain
2. Most effective mitigation strategies
3. Critical success factors for FMEA in this domain
4. Recommendations for future projects

Be specific, actionable, and based on the data shown."""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are a quality engineering expert analyzing FMEA patterns. Provide practical, data-driven insights."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=500
        )
        
        return response.choices[0].message.content.strip()
    
    except Exception as e:
        print(f"Error extracting lessons learned: {e}")
        return "Unable to generate lessons learned at this time."

# ============================================================================
# RISK ASSESSMENT EXPLANATION
# ============================================================================

def generate_risk_assessment_explanation(
    failure_mode: FailureMode,
    failure_cause: FailureCause,
    current_controls: List[CurrentControl],
    risk_score: RiskScore,
    similar_failures: List[SimilarFailureMode],
    domain: str
) -> List[str]:
    """
    Use Groq to generate natural language explanation of risk assessment.
    
    Returns:
        List of 3-4 bullet points explaining the risk
    """
    
    controls_text = "\n".join([
        f"- {c.control_description} ({c.control_type})"
        for c in current_controls
    ]) if current_controls else "No controls identified"
    
    similar_text = ""
    if similar_failures:
        similar_text = "\n".join([
            f"- {s.description} (Domain: {s.domain}, Severity: {s.severity_score})"
            for s in similar_failures[:3]
        ])
    
    prompt = f"""You are a quality engineer explaining an FMEA risk assessment.

Failure Mode: {failure_mode.description}
Root Cause: {failure_cause.cause_description}
Risk Scores: Severity={risk_score.severity}, Occurrence={risk_score.occurrence}, Detection={risk_score.detection}, RPN={risk_score.rpn}
Domain: {domain}

Current Controls:
{controls_text}

Similar Failures in History:
{similar_text if similar_text else "No similar historical failures"}

Generate exactly 3 concise bullet points explaining:
1. Why this failure mode is risky (severity × likelihood)
2. How effective current controls are
3. What could be done to improve

Format: Short, clear bullets. No markdown. No numbers repetition."""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are a quality engineer explaining technical FMEA assessments to business stakeholders. Be clear and concise."
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
        
        # Parse bullets
        bullets = []
        for line in explanation.split('\n'):
            line = line.strip()
            if line and (line.startswith('-') or line.startswith('•') or line.startswith('*')):
                bullets.append(line.lstrip('-•* ').strip())
            elif line and len(bullets) < 4 and line[0].isdigit() and '.' in line[:3]:
                # Handle numbered bullets
                bullets.append(line.split('.', 1)[1].strip() if '.' in line else line)
        
        # Ensure we have at least 3 bullets
        while len(bullets) < 3:
            bullets.append("Additional assessment needed.")
        
        return bullets[:4]
    
    except Exception as e:
        print(f"Error generating risk explanation: {e}")
        return generate_fallback_risk_explanation(failure_mode, failure_cause, risk_score)

def generate_fallback_risk_explanation(
    failure_mode: FailureMode,
    failure_cause: FailureCause,
    risk_score: RiskScore
) -> List[str]:
    """Fallback explanation if Groq is unavailable"""
    
    bullets = []
    
    # Severity assessment
    if risk_score.severity >= 8:
        bullets.append("This failure has critical impact if it reaches customer")
    elif risk_score.severity >= 5:
        bullets.append("This failure would cause significant problems if not caught")
    else:
        bullets.append("This failure has limited customer impact")
    
    # Occurrence assessment
    if risk_score.occurrence >= 7:
        bullets.append("This failure is likely to occur given current design/process")
    elif risk_score.occurrence >= 4:
        bullets.append("This failure could occur under certain conditions")
    else:
        bullets.append("This failure is unlikely under normal conditions")
    
    # Detection assessment
    if risk_score.detection >= 8:
        bullets.append("Current controls may not catch this failure before customer sees it")
    elif risk_score.detection >= 4:
        bullets.append("Current controls have moderate ability to detect this failure")
    else:
        bullets.append("Current controls are effective at detecting this failure")
    
    return bullets

# ============================================================================
# MAIN REASONING FUNCTION
# ============================================================================

def reason_about_failure_mode(
    failure_mode_id: int,
    fmea_id: int,
    domain: str
) -> ReasoningResult:
    """
    Main reasoning function for FMEA failure mode assessment.
    Orchestrates complete risk analysis and recommendations.
    
    Args:
        failure_mode_id: ID of failure mode to analyze
        fmea_id: ID of parent FMEA record
        domain: Domain for context
    
    Returns:
        Complete reasoning result with risk assessment and suggestions
    """
    
    # Fetch failure mode details
    failure_mode = get_failure_mode(failure_mode_id)
    if not failure_mode:
        raise ValueError(f"Failure mode {failure_mode_id} not found")
    
    failure_mode = FailureMode(**failure_mode)
    
    # Get all causes for this failure mode
    causes = get_failure_cause(failure_mode_id)  # This returns single cause
    failure_cause = FailureCause(**causes) if causes else None
    
    if not failure_cause:
        raise ValueError(f"No cause found for failure mode {failure_mode_id}")
    
    # Get current controls
    controls_list = get_current_controls(failure_cause.id)
    current_controls = [CurrentControl(**c) for c in controls_list]
    
    # Get risk score
    risk_data = get_risk_score(failure_cause.id, is_current=True)
    risk_score = RiskScore(**risk_data) if risk_data else None
    
    if not risk_score:
        raise ValueError(f"No risk score found for cause {failure_cause.id}")
    
    # Find similar historical failures
    similar_failures = suggest_failure_modes(
        failure_mode.description,
        domain,
        failure_mode.product_system_id,
        limit=3
    )
    
    # Suggest mitigation actions
    suggested_actions = suggest_mitigation_actions(failure_cause, domain, limit=5)
    
    # Generate risk explanation
    reasoning = generate_risk_assessment_explanation(
        failure_mode,
        failure_cause,
        current_controls,
        risk_score,
        similar_failures,
        domain
    )
    
    # Check if action is required
    status = "REQUIRES_ACTION" if risk_score.rpn >= 100 else \
             "MONITOR" if risk_score.rpn >= 50 else \
             "ACCEPTABLE"
    
    # Build result
    result = ReasoningResult(
        failure_mode=failure_mode,
        failure_cause=failure_cause,
        current_controls=current_controls,
        current_risk_score=risk_score,
        action_priority=risk_score.action_priority or "medium",
        status=status,
        similar_failure_modes=similar_failures,
        suggested_mitigation_actions=suggested_actions,
        reasoning=reasoning,
        confidence=0.85 if len(similar_failures) > 0 else 0.6
    )
    
    return result