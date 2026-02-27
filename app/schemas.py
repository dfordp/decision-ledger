"""
Pydantic schemas for request/response validation.
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, date
from enum import Enum

# ============================================================================
# ENUMS (matching models.py)
# ============================================================================

class DimensionEnum(str, Enum):
    MAINTENANCE_DURATION = "MAINTENANCE_DURATION"
    WARRANTY_YEARS = "WARRANTY_YEARS"
    RESPONSE_TIME_HOURS = "RESPONSE_TIME_HOURS"
    UPTIME_GUARANTEE = "UPTIME_GUARANTEE"
    SUPPORT_AVAILABILITY = "SUPPORT_AVAILABILITY"
    COMPLIANCE_LEVEL = "COMPLIANCE_LEVEL"
    PRICE_TOLERANCE = "PRICE_TOLERANCE"
    DELIVERY_WINDOW_DAYS = "DELIVERY_WINDOW_DAYS"

class RiskProfileEnum(str, Enum):
    conservative = "conservative"
    balanced = "balanced"
    aggressive = "aggressive"

class OutcomeEnum(str, Enum):
    WON = "WON"
    LOST = "LOST"
    REJECTED = "REJECTED"

class NatureEnum(str, Enum):
    default = "default"
    conditional = "conditional"
    exception = "exception"

class StrictnessEnum(str, Enum):
    mandatory = "mandatory"
    preferred = "preferred"

class FlexibilityEnum(str, Enum):
    fixed = "fixed"
    conditional = "conditional"
    flexible = "flexible"

# ============================================================================
# VENDOR SCHEMAS
# ============================================================================

class VendorPolicyCreate(BaseModel):
    dimension: DimensionEnum
    domain: str
    max_value: float
    flexibility: FlexibilityEnum
    notes: Optional[str] = None
    effective_from: date
    effective_to: Optional[date] = None

class VendorPolicyResponse(VendorPolicyCreate):
    id: int
    vendor_id: int
    created_at: datetime

    class Config:
        from_attributes = True

class VendorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    primary_domains: List[str] = []
    risk_profile: RiskProfileEnum

class VendorUpdate(BaseModel):
    name: Optional[str] = None
    primary_domains: Optional[List[str]] = None
    risk_profile: Optional[RiskProfileEnum] = None

class VendorResponse(VendorCreate):
    id: int
    created_at: datetime
    policies: List[VendorPolicyResponse] = []

    class Config:
        from_attributes = True

class VendorDetailResponse(VendorResponse):
    """Vendor with full relationship data"""
    pass

# ============================================================================
# PROPOSAL SCHEMAS
# ============================================================================

class ProposalDecisionCreate(BaseModel):
    dimension: DimensionEnum
    value: float
    nature: NatureEnum
    confidence: Optional[float] = Field(None, ge=0, le=1)
    violation_flag: bool = False
    source_excerpt: Optional[str] = None

class ProposalDecisionResponse(ProposalDecisionCreate):
    id: int
    proposal_id: int
    created_at: datetime

    class Config:
        from_attributes = True

class ProposalCreate(BaseModel):
    vendor_id: int
    year: int
    outcome: OutcomeEnum
    outcome_reason: Optional[str] = None
    proposal_summary: Optional[str] = None
    decisions: List[ProposalDecisionCreate] = []

class ProposalUpdate(BaseModel):
    outcome: Optional[OutcomeEnum] = None
    outcome_reason: Optional[str] = None
    proposal_summary: Optional[str] = None

class ProposalResponse(BaseModel):
    id: int
    vendor_id: int
    year: int
    outcome: OutcomeEnum
    outcome_reason: Optional[str]
    proposal_summary: Optional[str]
    created_at: datetime
    decisions: List[ProposalDecisionResponse] = []

    class Config:
        from_attributes = True

# ============================================================================
# TENDER SCHEMAS
# ============================================================================

class TenderRequirementCreate(BaseModel):
    dimension: DimensionEnum
    required_value: float
    strictness: StrictnessEnum

class TenderRequirementResponse(TenderRequirementCreate):
    id: int
    tender_id: int
    created_at: datetime

    class Config:
        from_attributes = True

class TenderCreate(BaseModel):
    tender_name: str = Field(..., min_length=1, max_length=255)
    domain: str
    year: int
    tender_summary: Optional[str] = None
    requirements: List[TenderRequirementCreate] = []

class TenderUpdate(BaseModel):
    tender_name: Optional[str] = None
    domain: Optional[str] = None
    year: Optional[int] = None
    tender_summary: Optional[str] = None

class TenderResponse(BaseModel):
    id: int
    tender_name: str
    domain: str
    year: int
    tender_summary: Optional[str]
    created_at: datetime
    requirements: List[TenderRequirementResponse] = []

    class Config:
        from_attributes = True

# ============================================================================
# ERROR SCHEMAS
# ============================================================================

class ErrorResponse(BaseModel):
    detail: str
    status_code: int