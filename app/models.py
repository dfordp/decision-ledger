"""
SQLAlchemy ORM models for DecisionLedger.
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Numeric, Boolean, Text, ARRAY, Enum, Date
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

Base = declarative_base()

# ============================================================================
# ENUM CLASSES
# ============================================================================

class DimensionEnum(str, enum.Enum):
    MAINTENANCE_DURATION = "MAINTENANCE_DURATION"
    WARRANTY_YEARS = "WARRANTY_YEARS"
    RESPONSE_TIME_HOURS = "RESPONSE_TIME_HOURS"
    UPTIME_GUARANTEE = "UPTIME_GUARANTEE"
    SUPPORT_AVAILABILITY = "SUPPORT_AVAILABILITY"
    COMPLIANCE_LEVEL = "COMPLIANCE_LEVEL"
    PRICE_TOLERANCE = "PRICE_TOLERANCE"
    DELIVERY_WINDOW_DAYS = "DELIVERY_WINDOW_DAYS"

class RiskProfileEnum(str, enum.Enum):
    conservative = "conservative"
    balanced = "balanced"
    aggressive = "aggressive"

class OutcomeEnum(str, enum.Enum):
    WON = "WON"
    LOST = "LOST"
    REJECTED = "REJECTED"

class NatureEnum(str, enum.Enum):
    default = "default"
    conditional = "conditional"
    exception = "exception"

class StrictnessEnum(str, enum.Enum):
    mandatory = "mandatory"
    preferred = "preferred"

class FlexibilityEnum(str, enum.Enum):
    fixed = "fixed"
    conditional = "conditional"
    flexible = "flexible"

# ============================================================================
# MODELS
# ============================================================================

class Vendor(Base):
    __tablename__ = "vendors"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    primary_domains = Column(ARRAY(String), default=[])
    risk_profile = Column(Enum(RiskProfileEnum, name="risk_profile_enum", native_enum=True), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    policies = relationship("VendorPolicy", back_populates="vendor", cascade="all, delete-orphan")
    proposals = relationship("Proposal", back_populates="vendor", cascade="all, delete-orphan")

class VendorPolicy(Base):
    __tablename__ = "vendor_policy"
    
    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    dimension = Column(Enum(DimensionEnum, name="dimension_enum", native_enum=True), nullable=False)
    domain = Column(String(100), nullable=False)
    max_value = Column(Numeric(10, 2), nullable=False)
    flexibility = Column(Enum(FlexibilityEnum, name="flexibility_enum", native_enum=True), nullable=False)
    notes = Column(Text)
    effective_from = Column(Date, nullable=False, default=datetime.utcnow)
    effective_to = Column(Date)
    embedding = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    vendor = relationship("Vendor", back_populates="policies")

class Proposal(Base):
    __tablename__ = "proposals"
    
    id = Column(Integer, primary_key=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)
    year = Column(Integer, nullable=False)
    outcome = Column(Enum(OutcomeEnum, name="outcome_enum", native_enum=True), nullable=False)
    outcome_reason = Column(Text)
    proposal_summary = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    vendor = relationship("Vendor", back_populates="proposals")
    decisions = relationship("ProposalDecision", back_populates="proposal", cascade="all, delete-orphan")

class ProposalDecision(Base):
    __tablename__ = "proposal_decisions"
    
    id = Column(Integer, primary_key=True)
    proposal_id = Column(Integer, ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False)
    dimension = Column(Enum(DimensionEnum, name="dimension_enum", native_enum=True), nullable=False)
    value = Column(Numeric(10, 2), nullable=False)
    nature = Column(Enum(NatureEnum, name="nature_enum", native_enum=True), nullable=False)
    confidence = Column(Numeric(3, 2))
    violation_flag = Column(Boolean, default=False)
    source_excerpt = Column(Text)
    embedding = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    proposal = relationship("Proposal", back_populates="decisions")

class Tender(Base):
    __tablename__ = "tenders"
    
    id = Column(Integer, primary_key=True)
    tender_name = Column(String(255), nullable=False)
    domain = Column(String(100), nullable=False)
    year = Column(Integer, nullable=False)
    tender_summary = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    requirements = relationship("TenderRequirement", back_populates="tender", cascade="all, delete-orphan")

class TenderRequirement(Base):
    __tablename__ = "tender_requirements"
    
    id = Column(Integer, primary_key=True)
    tender_id = Column(Integer, ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False)
    dimension = Column(Enum(DimensionEnum, name="dimension_enum", native_enum=True), nullable=False)
    required_value = Column(Numeric(10, 2), nullable=False)
    strictness = Column(Enum(StrictnessEnum, name="strictness_enum", native_enum=True), nullable=False)
    embedding = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    tender = relationship("Tender", back_populates="requirements")