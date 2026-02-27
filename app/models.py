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