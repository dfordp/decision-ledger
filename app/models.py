"""
Pydantic models for DecisionLedger API contracts.
These define the shape of data flowing through the system.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime
from decimal import Decimal

# Evaluation Dimension
class EvaluationDimension(BaseModel):
    id: int
    key: str
    display_name: str
    unit: str

# Vendor Policy
class VendorPolicy(BaseModel):
    id: int
    vendor_id: int
    dimension_id: int
    dimension_key: Optional[str] = None
    dimension_name: Optional[str] = None
    domain: str
    min_value: Decimal
    max_value: Decimal
    default_value: Optional[Decimal] = None
    flexibility: Literal["fixed", "negotiable", "flexible"]
    notes: Optional[str] = None

# Proposal
class Proposal(BaseModel):
    id: int
    vendor_id: int
    tender_name: str
    domain: str
    outcome: Literal["WON", "LOST", "REJECTED"]
    outcome_reason: Optional[str] = None
    submitted_at: datetime

# Proposal Decision (historical decision for one dimension)
class ProposalDecision(BaseModel):
    id: int
    proposal_id: int
    dimension_id: int
    dimension_key: Optional[str] = None
    dimension_name: Optional[str] = None
    offered_value: Decimal
    justification: str
    source_excerpt: Optional[str] = None
    created_at: datetime

# Tender
class Tender(BaseModel):
    id: int
    name: str
    domain: str
    year: int
    status: Literal["OPEN", "EVALUATING", "DECIDED", "CLOSED"]

# Tender Requirement
class TenderRequirement(BaseModel):
    id: int
    tender_id: int
    dimension_id: int
    dimension_key: Optional[str] = None
    dimension_name: Optional[str] = None
    dimension_unit: Optional[str] = None
    required_value: Decimal
    strictness: Literal["mandatory", "preferred"]
    description: Optional[str] = None

# Evidence item (similar past decision)
class EvidenceItem(BaseModel):
    proposal_id: int
    tender_name: str
    domain: str
    outcome: Literal["WON", "LOST", "REJECTED"]
    submitted_at: datetime
    offered_value: Decimal
    justification: str
    source_excerpt: Optional[str] = None
    similarity: float = Field(description="Similarity score 0-1")

# Reasoning Result (output of reasoning engine)
class ReasoningResult(BaseModel):
    dimension_key: str
    dimension_name: str
    dimension_unit: str
    
    # Requirement
    requirement: TenderRequirement
    
    # Policy
    policy: VendorPolicy
    
    # Recommendation
    recommended_value: Decimal
    status: Literal["BLOCK", "WARN", "SAFE"]
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence 0-1")
    
    # Reasoning
    reasoning: List[str] = Field(description="Bullet points explaining recommendation")
    
    # Evidence
    evidence: List[EvidenceItem] = Field(description="Similar past decisions")

# Decision Update (user override)
class DecisionUpdate(BaseModel):
    tender_id: int
    dimension_key: str
    final_value: Decimal
    user_notes: str = Field(default="", description="User's rationale for override")

# Response after saving decision
class DecisionUpdateResponse(BaseModel):
    success: bool
    message: str
    proposal_decision_id: Optional[int] = None


# ============================================================================
# PFMEA (Process Failure Mode & Effects Analysis) Models
# ============================================================================

# Failure Mode Taxonomy
class FailureModeTaxonomy(BaseModel):
    id: int
    canonical_name: str
    category: str
    description: Optional[str] = None
    typical_severity_range: Optional[List[int]] = None
    aliases: List[str] = []
    version: int = 1
    approved_by: Optional[str] = None

# Process Step
class ProcessStep(BaseModel):
    id: int
    step_number: int
    step_name: str
    process_function: Optional[str] = None

# Failure Mode Cause
class FailureModeCause(BaseModel):
    id: Optional[int] = None
    cause_sequence: int = 1
    canonical_cause: str
    cause_category: str
    description: Optional[str] = None
    occurrence_score: Optional[int] = None

# Process Control
class ProcessControl(BaseModel):
    id: Optional[int] = None
    control_type: Literal["PREVENTION", "DETECTION"]
    control_description: str
    method: Optional[str] = None
    frequency: Optional[str] = None
    effectiveness_percent: int = 90

# PFMEA Failure Mode Entry
class PFMEAFailureModeEntry(BaseModel):
    id: Optional[int] = None
    pfmea_record_id: int
    process_step_number: int
    process_step_name: Optional[str] = None
    failure_mode_id: int
    failure_mode_name: Optional[str] = None
    
    # User Input Scores
    severity_user_input: Optional[int] = Field(None, ge=1, le=10)
    occurrence_user_input: Optional[int] = Field(None, ge=1, le=10)
    detection_user_input: Optional[int] = Field(None, ge=1, le=10)
    rpn_user_calculated: Optional[int] = None
    
    # Suggested Scores from History
    severity_suggested: Optional[int] = None
    occurrence_suggested: Optional[int] = None
    detection_suggested: Optional[int] = None
    rpn_suggested: Optional[int] = None
    similar_incidents_count: int = 0
    
    # Context
    potential_effect: Optional[str] = None
    justification: Optional[str] = None
    rpn_risk_class: Optional[str] = None
    
    # Causes and Controls
    causes: List[FailureModeCause] = []
    controls: List[ProcessControl] = []
    
    # Canvas Notes
    canvas_notes: Optional[str] = None

# PFMEA Record
class PFMEARecord(BaseModel):
    id: Optional[int] = None
    part_number: str
    part_name: str
    model_year: Optional[str] = None
    customer_name: Optional[str] = None
    process_responsibility: Optional[str] = None
    core_team: List[str] = []
    domain: Optional[str] = None
    status: Literal["DRAFT", "REVIEW", "APPROVED", "IMPLEMENTATION", "CLOSED"] = "DRAFT"
    format_number: Optional[str] = None
    fmea_date_original: Optional[datetime] = None
    
    # Summary Scores
    overall_rpn: Optional[int] = None
    overall_rpn_average: Optional[float] = None
    
    # Entries
    process_steps: List[ProcessStep] = []
    entries: List[PFMEAFailureModeEntry] = []

# Historical Incident
class HistoricalIncident(BaseModel):
    id: int
    part_number: str
    failure_mode_id: int
    failure_mode_name: Optional[str] = None
    incident_date: datetime
    location: Optional[str] = None
    description: Optional[str] = None
    severity_actual: Optional[int] = None
    impact_hours: Optional[int] = None
    corrective_action: Optional[str] = None
    rpn: Optional[int] = None

# Canvas Save Request
class CanvasSaveRequest(BaseModel):
    part_id: int
    entries: List[PFMEAFailureModeEntry]
    overall_rpn: dict = {
        "max": 0,
        "average": 0.0,
        "highCount": 0,
        "medCount": 0,
        "lowCount": 0
    }

# RPN Suggestions Response
class RPNSuggestion(BaseModel):
    severity_suggested: Optional[int] = None
    occurrence_suggested: Optional[int] = None
    detection_suggested: Optional[int] = None
    rpn_suggested: Optional[int] = None
    similar_incident_count: int = 0
    incidents: List[HistoricalIncident] = []