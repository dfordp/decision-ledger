"""
Pydantic models for DecisionLedger API contracts.
These define the shape of data flowing through the system.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime
from decimal import Decimal
from enum import Enum

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
    
    # AI Evaluation (Groq-powered risk assessment)
    evaluation_status: Optional[Literal["SAFE", "WARN", "BLOCK"]] = None
    ai_justification: Optional[str] = None

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


# ============================================================================
# HIERARCHICAL PLM MODELS (Vehicle → System → Assembly → Part → Revision)
# ============================================================================

# Part Revision (version control for parts)
class PartRevision(BaseModel):
    id: Optional[str] = None
    part_id: str
    revision_number: int
    change_type: Literal["design_change", "material_substitution", "supplier_change", "baseline_migration"] = "design_change"
    previous_specs_json: Optional[dict] = None
    new_specs_json: dict = Field(description="Full spec snapshot")
    change_description: Optional[str] = None
    changed_by: str = "system"
    change_date: Optional[datetime] = None
    approval_status: Literal["draft", "approved", "rejected"] = "draft"
    created_at: Optional[datetime] = None

# Revision Impact Analysis (AI-generated)
class RevisionImpactAnalysis(BaseModel):
    id: Optional[str] = None
    part_revision_id: str
    analysis_json: dict = Field(description="Groq analysis output: {updated_failures, new_risks, mitigations}")
    previous_rpn_median: Optional[float] = None
    new_rpn_estimate: Optional[float] = None
    rpn_delta: Optional[float] = None
    confidence_score: int = Field(default=0, ge=0, le=100)
    analysis_timestamp: Optional[datetime] = None
    created_at: Optional[datetime] = None

# Part (leaf node in hierarchy)
class Part(BaseModel):
    id: Optional[str] = None
    assembly_id: str
    part_name: str
    part_number: Optional[str] = None
    supplier: Optional[str] = None
    material: Optional[str] = None
    cost: Optional[float] = None
    mass: Optional[float] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Related data
    revisions: List[PartRevision] = Field(default_factory=list, description="All revisions of this part")
    revision_count: int = 0
    latest_revision: Optional[PartRevision] = None

# Assembly (groups related parts)
class Assembly(BaseModel):
    id: Optional[str] = None
    system_id: str
    assembly_name: str
    part_number: str = Field(description="Unique assembly identifier")
    description: Optional[str] = None
    part_owner_team: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Related data
    parts: List[Part] = Field(default_factory=list)
    part_count: int = 0

# Vehicle System (e.g., Electrical, Powertrain)
class VehicleSystem(BaseModel):
    id: Optional[str] = None
    vehicle_id: str
    system_name: str
    description: Optional[str] = None
    sequence_order: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Related data
    assemblies: List[Assembly] = Field(default_factory=list)
    assembly_count: int = 0

# Vehicle (top-level container)
class Vehicle(BaseModel):
    id: Optional[str] = None
    name: str
    category: Literal["automotive", "commercial", "industrial", "electronics"]
    model_year: Optional[int] = None
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Related data
    systems: List[VehicleSystem] = Field(default_factory=list)
    system_count: int = 0
    total_assemblies: int = 0
    total_parts: int = 0

# Nested full hierarchy (for tree view)
class VehicleHierarchy(BaseModel):
    id: Optional[str] = None
    name: str
    model_year: Optional[int] = None
    category: str
    systems: List[VehicleSystem] = Field(default_factory=list)
    total_parts: int = 0
    total_revisions: int = 0

# Create Revision Request
class CreateRevisionRequest(BaseModel):
    change_type: Literal["design_change", "material_substitution", "supplier_change"] = "design_change"
    change_description: str = Field(description="Reason for this revision")
    new_specs_json: dict = Field(description="New part specifications")
    changed_by: str = "current_user"

# Revision Comparison Response
class RevisionComparison(BaseModel):
    part_id: str
    part_name: str
    old_revision: PartRevision
    new_revision: PartRevision
    changes: dict = Field(description="Diff of old vs new specs")
    impact_analysis: Optional[RevisionImpactAnalysis] = None


# ============================================================================
# DETERMINISTIC REVISION ANALYSIS & VALIDATION MODELS
# ============================================================================

class ValidationContextState(str, Enum):
    """Explicit validation state tracking - separates completion from success"""
    VALIDATED = "VALIDATED"  # extraction + comparison + validation all succeeded
    PARTIAL_EXTRACTION = "PARTIAL_EXTRACTION"  # extracted some dimensions but not all
    COMPARISON_INCOMPLETE = "COMPARISON_INCOMPLETE"  # extraction ok but comparison failed
    NO_BASELINE = "NO_BASELINE"  # no baseline revision to compare against
    REVIEW_PENDING = "REVIEW_PENDING"  # insufficient data for deterministic validation


class RevisionValidationContext(BaseModel):
    """
    Tracks extraction/comparison/validation state per revision.
    Separates "validation completed" from "validation succeeded".
    """
    state: ValidationContextState
    
    # Extraction metrics
    entities_extracted: int = 0
    dimensions_extracted: int = 0
    tolerances_extracted: int = 0
    features_extracted: int = 0
    
    # Baseline availability
    baseline_available: bool = False
    baseline_revision: Optional[str] = None
    
    # Comparison execution
    comparison_executed: bool = False
    comparison_completed: bool = False
    
    # Validation execution
    rules_executed: int = 0
    critical_findings: int = 0
    warning_findings: int = 0
    
    # Summary
    summary_text: str = Field(description="Human-readable state description")


class EngineeringImpactAnalysis(BaseModel):
    """
    Classification of engineering impact for a dimension/feature.
    Each flag indicates whether this change affects that domain.
    """
    assembly_alignment: bool = False
    inspection_fixture_dependency: bool = False
    mating_geometry_dependency: bool = False
    tolerance_stack_dependency: bool = False
    manufacturing_process_dependency: bool = False
    safety_critical: bool = False
    
    impact_summary: str = Field(description="Brief text description of impacts")


class DimensionEvaluation(BaseModel):
    """
    Complete evaluation for a single dimension across revisions.
    Shows baseline vs current, delta classification, and validation result.
    """
    dimension_id: str = Field(description="Unique dimension identifier")
    name: str = Field(description="Human-readable dimension name")
    baseline_revision: str = Field(description="Approved reference revision (e.g., 'R3')")
    revision_under_review: str = Field(description="Revision being evaluated (e.g., 'R4')")
    
    # Extraction status
    baseline_exists: bool = Field(description="Dimension present in baseline")
    current_exists: bool = Field(description="Dimension present in current revision")
    tolerance_present_baseline: bool = Field(description="Tolerance spec in baseline")
    tolerance_present_current: bool = Field(description="Tolerance spec in current")
    
    # Baseline values (for reference)
    baseline_value: Optional[str] = None
    baseline_tolerance: Optional[str] = None
    
    # Current values (under review)
    current_value: Optional[str] = None
    current_tolerance: Optional[str] = None
    
    # Delta classification
    change_type: str = Field(
        description="IDENTICAL|ADDED|REMOVED|MODIFIED|TOLERANCE_LOOSENED|TOLERANCE_TIGHTENED"
    )
    delta_percent: Optional[float] = Field(None, description="Percentage change if numeric")
    
    # Criticality classification
    criticality: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = "HIGH"
    
    # Engineering impact
    engineering_impact: EngineeringImpactAnalysis
    
    # Validation result
    severity: Literal["SAFE", "WARN", "BLOCK"] = "SAFE"
    finding: str = Field(description="Short title of finding")
    reason: str = Field(description="Detailed explanation of why this severity")
    
    # Triggered rules
    triggered_rules: List[str] = Field(default_factory=list, description="Which deterministic rules fired")
    
    # Recommendation
    recommended_action: Optional[str] = None


class RevisionAnalysisSummary(BaseModel):
    """
    Complete deterministic analysis for an entire revision.
    Separates extraction/comparison/validation states from release recommendation.
    """
    revision_id: str
    revision_number: int
    part_id: str
    part_name: str
    baseline_revision_id: Optional[str] = None
    baseline_revision_number: Optional[int] = None
    
    # Validation context - tracks completion status
    validation_context: RevisionValidationContext
    
    # Dimension-level analyses
    dimension_analyses: List[DimensionEvaluation] = Field(
        default_factory=list,
        description="Complete evaluation for each dimension"
    )
    
    # Overall recommendation
    status: Literal["SAFE", "WARN", "BLOCK", "REVIEW_PENDING"] = "SAFE"
    release_recommendation: str = Field(description="Human-readable release decision")
    
    # Findings summary
    critical_findings: List[str] = Field(default_factory=list)
    warning_findings: List[str] = Field(default_factory=list)
    
    # Explainability summaries
    extraction_summary: str = Field(
        description="Summary of what was extracted from the revision"
    )
    comparison_summary: str = Field(
        description="Summary of comparison against baseline"
    )
    validation_reasoning: str = Field(
        description="Summary of validation logic and reasoning"
    )
    
    # Metadata
    analysis_timestamp: Optional[datetime] = None
    confidence_score: int = Field(default=95, ge=0, le=100, description="Deterministic rule confidence")