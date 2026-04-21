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
# DFMEA (Design Failure Mode & Effects Analysis) Models
# ============================================================================

# Failure Mode Taxonomy
class FailureModeTaxonomy(BaseModel):
    id: int
    canonical_name: str
    category: str  # ELECTRICAL, MECHANICAL, MATERIAL, DESIGN_INTERFACE, ENVIRONMENTAL, etc.
    description: Optional[str] = None
    typical_severity_range: Optional[List[int]] = None
    aliases: List[str] = []
    version: int = 1
    approved_by: Optional[str] = None

# Design Function (component/subsystem in the product hierarchy)
class DesignFunction(BaseModel):
    """Represents a functional component in the design hierarchy"""
    id: int
    step_number: int
    step_name: str
    function_hierarchy: Optional[str] = None
    design_intent: Optional[str] = None
    critical_parameters: List[str] = []

# Backward compatibility alias
ProcessStep = DesignFunction

# Failure Mode Cause (with design margin analysis)
class FailureModeCause(BaseModel):
    id: Optional[int] = None
    cause_sequence: int = 1
    canonical_cause: str
    cause_category: Literal["MATERIAL", "GEOMETRY", "SPECIFICATION", "TOLERANCE", "DESIGN_INTERFACE", "ENVIRONMENTAL"]
    description: Optional[str] = None
    design_margin_loss: Optional[float] = None
    safety_factor_assumed: Optional[float] = None

# Design Validation Measure (testing, simulation, analysis)
class ValidationMeasure(BaseModel):
    id: Optional[int] = None
    control_type: Literal["ANALYSIS", "TESTING", "PROTOTYPE", "SIMULATION"]
    control_description: str
    test_method: Optional[str] = None
    effectiveness_percent: int = 90
    test_results_json: Optional[dict] = None

# Backward compatibility alias
ProcessControl = ValidationMeasure

# DFMEA Failure Mode Entry
class PFMEAFailureModeEntry(BaseModel):
    id: Optional[int] = None
    pfmea_record_id: int
    process_step_number: int
    process_step_name: Optional[str] = None
    failure_mode_id: int
    failure_mode_name: Optional[str] = None
    
    # User Input Scores (Design-focused semantics)
    # S = Functional consequence, O = Design margin probability, D = Validation test effectiveness
    severity_user_input: Optional[int] = Field(None, ge=1, le=10)
    occurrence_user_input: Optional[int] = Field(None, ge=1, le=10)
    detection_user_input: Optional[int] = Field(None, ge=1, le=10)
    rpn_user_calculated: Optional[int] = None
    
    # Suggested Scores from Historical Design Data
    severity_suggested: Optional[int] = None
    occurrence_suggested: Optional[int] = None
    detection_suggested: Optional[int] = None
    rpn_suggested: Optional[int] = None
    similar_incidents_count: int = 0
    
    # Context
    potential_effect: Optional[str] = None
    justification: Optional[str] = None
    rpn_risk_class: Optional[str] = None
    
    # Design Validation Test Results
    design_validation_test_results: Optional[dict] = None
    
    # Causes and Validation Measures
    causes: List[FailureModeCause] = []
    controls: List[ValidationMeasure] = []
    
    # Canvas Notes
    canvas_notes: Optional[str] = None

# DFMEA Record (Design FMEA)
class PFMEARecord(BaseModel):
    id: Optional[int] = None
    part_number: str
    part_name: str
    model_year: Optional[str] = None
    customer_name: Optional[str] = None
    process_responsibility: Optional[str] = None
    core_team: List[str] = []
    domain: Optional[str] = None  # ELECTRICAL, MECHANICAL, THERMAL, INTERFACE
    status: Literal["DRAFT", "REVIEW", "APPROVED", "IMPLEMENTATION", "CLOSED"] = "DRAFT"
    format_number: Optional[str] = None
    fmea_date_original: Optional[datetime] = None
    
    # Design Phase & Standards
    design_phase: Literal["CONCEPT", "PRELIMINARY", "DETAILED", "PRODUCTION_DESIGN"] = "DETAILED"
    design_standards: List[str] = []
    
    # Summary Scores
    overall_rpn: Optional[int] = None
    overall_rpn_average: Optional[float] = None
    
    # Design Functions and Failure Mode Entries
    process_steps: List[DesignFunction] = []
    entries: List[PFMEAFailureModeEntry] = []


# Design Validation Historical Data
class HistoricalIncident(BaseModel):
    id: int
    part_number: str
    failure_mode_id: int
    failure_mode_name: Optional[str] = None
    incident_date: datetime
    location: Optional[str] = None
    description: Optional[str] = None
    design_margin_loss: Optional[float] = None
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