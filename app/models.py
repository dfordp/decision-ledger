"""
Pydantic models for FMEA (Failure Mode and Effects Analysis) API contracts.
Based on AIAG-VDA FMEA 4.0 Harmonized Standard.
These define the shape of data flowing through the system.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any
from datetime import datetime, date
from decimal import Decimal
import json

# ============================================================================
# ENUMS & LITERALS
# ============================================================================

FailureModeType = Literal["no_function", "partial_function", "intermittent", "unintended"]
IshikawCategory = Literal["materials", "methods", "machines", "maintenance", "measurements", "environment", "management"]
ControlType = Literal["prevention", "detection"]
FMEAPhase = Literal["planning", "structural", "functional", "failure_analysis", "risk_analysis", "optimization", "documentation"]
FMEAStatus = Literal["not_started", "in_progress", "under_review", "completed"]
ActionStatus = Literal["open", "in_progress", "completed", "closed"]
ActionPriority = Literal["high", "medium", "low"]
RiskFactorType = Literal["severity", "occurrence", "detection", "action_priority"]

# ============================================================================
# RISK FACTOR & STANDARDS
# ============================================================================

class RiskFactor(BaseModel):
    """Risk scoring factor (Severity, Occurrence, Detection, Action Priority)"""
    id: int
    factor_type: RiskFactorType
    name: str
    scale_min: int = 1
    scale_max: int = 10
    description: Optional[str] = None
    guidance: Optional[str] = None
    
    class Config:
        from_attributes = True

class OrganizationalStandard(BaseModel):
    """Risk acceptance thresholds by domain"""
    id: int
    domain: str
    risk_factor_id: int
    min_acceptable: Optional[Decimal] = None
    max_acceptable: Optional[Decimal] = None
    notes: Optional[str] = None
    
    class Config:
        from_attributes = True

# ============================================================================
# PRODUCT SYSTEM
# ============================================================================

class ProductSystem(BaseModel):
    """Product or Process being analyzed"""
    id: int
    name: str
    domain: str  # automotive, medical, manufacturing, etc.
    system_level: str  # system, subsystem, component
    description: Optional[str] = None
    system_function: str  # Primary function
    scope: Optional[str] = None  # What's included/excluded
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class ProductSystemCreate(BaseModel):
    """Create new product system"""
    name: str
    domain: str
    system_level: str
    description: Optional[str] = None
    system_function: str
    scope: Optional[str] = None

# ============================================================================
# EXPERT MANAGEMENT
# ============================================================================

class ExpertProfile(BaseModel):
    """Team member with skills"""
    id: int
    name: str
    email: Optional[str] = None
    department: Optional[str] = None
    expertise: Optional[Dict[str, Any]] = None  # {"skills": ["design", "testing", ...]}
    contact_info: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class ExpertProfileCreate(BaseModel):
    """Create new expert profile"""
    name: str
    email: Optional[str] = None
    department: Optional[str] = None
    expertise: Optional[Dict[str, Any]] = None
    contact_info: Optional[str] = None

# ============================================================================
# FMEA PROJECT MANAGEMENT
# ============================================================================

class FMEARecord(BaseModel):
    """Main FMEA project container"""
    id: int
    product_system_id: int
    project_name: str
    team_leads: Optional[List[int]] = None  # Expert profile IDs
    team_members: Optional[List[int]] = None  # Expert profile IDs
    current_phase: FMEAPhase
    status: FMEAStatus
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_by: Optional[str] = None
    
    class Config:
        from_attributes = True

class FMEARecordCreate(BaseModel):
    """Create new FMEA record"""
    product_system_id: int
    project_name: str
    team_leads: Optional[List[int]] = None
    team_members: Optional[List[int]] = None
    description: Optional[str] = None
    created_by: Optional[str] = None

class FMEARecordUpdate(BaseModel):
    """Update FMEA record"""
    current_phase: Optional[FMEAPhase] = None
    status: Optional[FMEAStatus] = None
    team_leads: Optional[List[int]] = None
    team_members: Optional[List[int]] = None
    description: Optional[str] = None

class FMEAPhaseChecklist(BaseModel):
    """Track completion of each FMEA phase"""
    id: int
    fmea_record_id: int
    phase: FMEAPhase
    is_complete: bool
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None
    
    class Config:
        from_attributes = True

# ============================================================================
# FAILURE ANALYSIS
# ============================================================================

class FailureMode(BaseModel):
    """Potential failure that can occur"""
    id: int
    fmea_record_id: int
    product_system_id: int
    mode_type: FailureModeType
    description: str
    potential_effects: Optional[str] = None
    severity_score: int = 5
    severity_justification: Optional[str] = None
    source: Optional[str] = None  # historical_data, brainstorm, standard, etc.
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class FailureModeCreate(BaseModel):
    """Create new failure mode"""
    fmea_record_id: int
    product_system_id: int
    mode_type: FailureModeType
    description: str
    potential_effects: Optional[str] = None
    severity_score: int = 5
    severity_justification: Optional[str] = None
    source: Optional[str] = None

class FailureModeUpdate(BaseModel):
    """Update failure mode"""
    description: Optional[str] = None
    potential_effects: Optional[str] = None
    severity_score: Optional[int] = None
    severity_justification: Optional[str] = None

class FailureCause(BaseModel):
    """Root cause of failure mode"""
    id: int
    failure_mode_id: int
    cause_description: str
    ishikawa_category: Optional[IshikawCategory] = None
    occurrence_score: int = 5
    occurrence_justification: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class FailureCauseCreate(BaseModel):
    """Create new failure cause"""
    failure_mode_id: int
    cause_description: str
    ishikawa_category: Optional[IshikawCategory] = None
    occurrence_score: int = 5
    occurrence_justification: Optional[str] = None

class FailureCauseUpdate(BaseModel):
    """Update failure cause"""
    cause_description: Optional[str] = None
    ishikawa_category: Optional[IshikawCategory] = None
    occurrence_score: Optional[int] = None
    occurrence_justification: Optional[str] = None

class CurrentControl(BaseModel):
    """Existing prevention or detection control"""
    id: int
    failure_cause_id: int
    control_description: str
    control_type: ControlType
    detection_score: int = 5
    detection_justification: Optional[str] = None
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class CurrentControlCreate(BaseModel):
    """Create new control"""
    failure_cause_id: int
    control_description: str
    control_type: ControlType
    detection_score: int = 5
    detection_justification: Optional[str] = None

# ============================================================================
# RISK CALCULATION
# ============================================================================

class RiskScore(BaseModel):
    """Calculated risk (S × O × D = RPN) and Action Priority"""
    id: int
    failure_cause_id: int
    severity: int  # S: 1-10
    occurrence: int  # O: 1-10
    detection: int  # D: 1-10
    rpn: int  # Risk Priority Number (S × O × D)
    action_priority: Optional[ActionPriority] = None
    is_current_state: bool = True
    calculated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class RiskScoreCreate(BaseModel):
    """Create new risk score"""
    failure_cause_id: int
    severity: int
    occurrence: int
    detection: int
    action_priority: Optional[ActionPriority] = None
    is_current_state: bool = True

# ============================================================================
# MITIGATION ACTIONS
# ============================================================================

class MitigationAction(BaseModel):
    """Proposed improvement to reduce risk"""
    id: int
    failure_cause_id: int
    action_description: str
    action_type: Optional[str] = None  # prevention, detection, both
    responsibility: Optional[str] = None
    target_date: Optional[date] = None
    status: ActionStatus = "open"
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class MitigationActionCreate(BaseModel):
    """Create new mitigation action"""
    failure_cause_id: int
    action_description: str
    action_type: Optional[str] = None
    responsibility: Optional[str] = None
    target_date: Optional[date] = None

class MitigationActionUpdate(BaseModel):
    """Update mitigation action"""
    action_description: Optional[str] = None
    action_type: Optional[str] = None
    responsibility: Optional[str] = None
    target_date: Optional[date] = None
    status: Optional[ActionStatus] = None

class PostActionRiskScore(BaseModel):
    """Risk score after mitigation measures"""
    id: int
    mitigation_action_id: int
    failure_cause_id: int
    new_severity: Optional[int] = None
    new_occurrence: Optional[int] = None
    new_detection: Optional[int] = None
    new_rpn: Optional[int] = None
    new_action_priority: Optional[ActionPriority] = None
    effectiveness_rating: Optional[int] = None  # 1-10
    effectiveness_notes: Optional[str] = None
    estimated_cost: Optional[Decimal] = None
    calculated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class PostActionRiskScoreCreate(BaseModel):
    """Create post-action risk score"""
    mitigation_action_id: int
    failure_cause_id: int
    new_severity: Optional[int] = None
    new_occurrence: Optional[int] = None
    new_detection: Optional[int] = None
    new_action_priority: Optional[ActionPriority] = None
    effectiveness_rating: Optional[int] = None
    effectiveness_notes: Optional[str] = None
    estimated_cost: Optional[Decimal] = None

# ============================================================================
# HISTORICAL LEARNING
# ============================================================================

class HistoricalFMEA(BaseModel):
    """Past FMEA record for learning and pattern matching"""
    id: int
    fmea_record_id: Optional[int] = None
    domain: str
    system_function: str
    product_name: Optional[str] = None
    failure_modes_summary: Optional[Dict[str, Any]] = None
    mitigation_actions_summary: Optional[Dict[str, Any]] = None
    effectiveness_summary: Optional[str] = None
    lessons_learned: Optional[str] = None
    key_findings: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

# ============================================================================
# REASONING & AI OUTPUT
# ============================================================================

class SimilarFailureMode(BaseModel):
    """Historical failure mode similar to current"""
    failure_mode_id: int
    description: str
    domain: str
    system_function: str
    severity_score: int
    similarity_score: float = Field(ge=0.0, le=1.0, description="Cosine similarity 0-1")

class SuggestedMitigationAction(BaseModel):
    """Proposed mitigation from similar historical FMEA"""
    action_description: str
    action_type: Optional[str] = None
    source_system: str  # System where this was effective
    effectiveness_rating: Optional[int] = None  # From historical data
    similarity_score: float = Field(ge=0.0, le=1.0, description="Similarity to current cause")

class ReasoningResult(BaseModel):
    """Output of FMEA reasoning engine"""
    # Current failure info
    failure_mode: FailureMode
    failure_cause: FailureCause
    current_controls: List[CurrentControl]
    
    # Risk assessment
    current_risk_score: RiskScore
    action_priority: ActionPriority
    status: Literal["REQUIRES_ACTION", "MONITOR", "ACCEPTABLE"]
    
    # Historical evidence
    similar_failure_modes: List[SimilarFailureMode] = Field(
        description="Historical FMEAs with similar failures"
    )
    
    # Recommendations
    suggested_mitigation_actions: List[SuggestedMitigationAction] = Field(
        description="AI-suggested actions from similar cases"
    )
    
    # Reasoning explanation
    reasoning: List[str] = Field(
        description="Bullet points explaining the assessment"
    )
    
    confidence: float = Field(
        ge=0.0, le=1.0, 
        description="Confidence in recommendation"
    )

class IshikawaDiagram(BaseModel):
    """Ishikawa (Fishbone) diagram structure for a failure mode"""
    failure_mode_id: int
    failure_mode_description: str
    causes_by_category: Dict[IshikawCategory, List[str]] = Field(
        description="Causes grouped by Ishikawa category"
    )

class FMEAReport(BaseModel):
    """Complete FMEA report for export/display"""
    fmea_record: FMEARecord
    product_system: ProductSystem
    team_members: List[ExpertProfile]
    failure_modes_analysis: List[Dict[str, Any]]  # Flattened FMEA table
    high_priority_actions: List[MitigationAction]
    lessons_learned: Optional[str] = None
    export_date: datetime = Field(default_factory=datetime.now)

# ============================================================================
# API REQUEST/RESPONSE MODELS
# ============================================================================

class TeamAssignmentRequest(BaseModel):
    """Request to assign team members"""
    fmea_record_id: int
    team_leads: List[int]
    team_members: List[int]

class PhaseCompletionRequest(BaseModel):
    """Mark a phase as complete"""
    fmea_record_id: int
    phase: FMEAPhase
    notes: Optional[str] = None

class SuggestFailureModesRequest(BaseModel):
    """Request AI suggestions for failure modes"""
    fmea_record_id: int
    system_function: str
    domain: str
    limit: int = 10

class SuggestMitigationRequest(BaseModel):
    """Request AI suggestions for mitigation actions"""
    failure_cause_id: int
    domain: str
    limit: int = 5

class RiskScoreUpdateRequest(BaseModel):
    """Update risk scores for a cause"""
    failure_cause_id: int
    severity: int
    occurrence: int
    detection: int

class APIResponse(BaseModel):
    """Generic API response"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None