"""
Seed DecisionLedger database with realistic mock data.

Generates:
- Vendor policies (bounds & flexibility for each dimension)
- Historical proposals with outcomes (8 past bids)
- Proposal decisions (what values were chosen historically)
- Incoming tenders (2 new RFPs to evaluate)
- Tender requirements (dimensions needed)
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal
from app.models import (
    Vendor, VendorPolicy, Proposal, ProposalDecision,
    Tender, TenderRequirement,
    DimensionEnum, FlexibilityEnum, OutcomeEnum, NatureEnum,
    StrictnessEnum, RiskProfileEnum
)
from datetime import datetime, date
import random

def seed_vendor_policies(db, vendor_id):
    """
    Create vendor policies defining what the vendor will accept.
    
    Policies vary by:
    - Domain (GLOBAL or specific domain)
    - Flexibility (fixed, conditional, flexible)
    - Risk profile influence
    """
    print("\n📋 Seeding Vendor Policies...")
    
    policies = [
        # GLOBAL policies (apply to all domains)
        {
            "dimension": DimensionEnum.MAINTENANCE_DURATION,
            "domain": "GLOBAL",
            "max_value": 24,  # max 24 hour maintenance window
            "flexibility": FlexibilityEnum.fixed,
            "notes": "Strict maintenance window requirement across all domains"
        },
        {
            "dimension": DimensionEnum.WARRANTY_YEARS,
            "domain": "GLOBAL",
            "max_value": 5,  # willing to offer up to 5 year warranty
            "flexibility": FlexibilityEnum.flexible,
            "notes": "Can negotiate warranty duration depending on pricing"
        },
        {
            "dimension": DimensionEnum.RESPONSE_TIME_HOURS,
            "domain": "GLOBAL",
            "max_value": 4,  # cannot promise faster than 4 hour response
            "flexibility": FlexibilityEnum.conditional,
            "notes": "Response time depends on support tier purchased"
        },
        {
            "dimension": DimensionEnum.UPTIME_GUARANTEE,
            "domain": "GLOBAL",
            "max_value": 99.9,  # maximum 99.9% SLA
            "flexibility": FlexibilityEnum.fixed,
            "notes": "Cannot guarantee higher than 99.9% uptime"
        },
        {
            "dimension": DimensionEnum.SUPPORT_AVAILABILITY,
            "domain": "GLOBAL",
            "max_value": 24,  # 24/7 support is maximum offering
            "flexibility": FlexibilityEnum.flexible,
            "notes": "Support hours negotiable based on contract tier"
        },
        {
            "dimension": DimensionEnum.COMPLIANCE_LEVEL,
            "domain": "GLOBAL",
            "max_value": 4,  # ISO 27001, SOC2, HIPAA, PCI-DSS certified
            "flexibility": FlexibilityEnum.fixed,
            "notes": "Compliance certifications are fixed, not negotiable"
        },
        {
            "dimension": DimensionEnum.PRICE_TOLERANCE,
            "domain": "GLOBAL",
            "max_value": 150000,  # willing to quote up to $150k/year
            "flexibility": FlexibilityEnum.flexible,
            "notes": "Price is flexible based on scope and commitment"
        },
        {
            "dimension": DimensionEnum.DELIVERY_WINDOW_DAYS,
            "domain": "GLOBAL",
            "max_value": 90,  # minimum 90 day delivery window
            "flexibility": FlexibilityEnum.conditional,
            "notes": "Delivery depends on complexity and resource availability"
        },
        
        # Domain-specific policies (infrastructure)
        {
            "dimension": DimensionEnum.UPTIME_GUARANTEE,
            "domain": "infrastructure",
            "max_value": 99.95,  # higher guarantee for infrastructure
            "flexibility": FlexibilityEnum.fixed,
            "notes": "Infrastructure services have stricter uptime requirements"
        },
        {
            "dimension": DimensionEnum.RESPONSE_TIME_HOURS,
            "domain": "infrastructure",
            "max_value": 2,  # faster response for infrastructure
            "flexibility": FlexibilityEnum.fixed,
            "notes": "Infrastructure issues need immediate response"
        },
        
        # Domain-specific policies (cloud)
        {
            "dimension": DimensionEnum.COMPLIANCE_LEVEL,
            "domain": "cloud",
            "max_value": 5,  # higher compliance for cloud services
            "flexibility": FlexibilityEnum.fixed,
            "notes": "Cloud services require additional compliance certifications"
        },
        {
            "dimension": DimensionEnum.DELIVERY_WINDOW_DAYS,
            "domain": "cloud",
            "max_value": 30,  # faster delivery for cloud
            "flexibility": FlexibilityEnum.flexible,
            "notes": "Cloud offerings can be deployed quickly"
        },
    ]
    
    for policy_data in policies:
        policy = VendorPolicy(
            vendor_id=vendor_id,
            dimension=policy_data["dimension"],
            domain=policy_data["domain"],
            max_value=policy_data["max_value"],
            flexibility=policy_data["flexibility"],
            notes=policy_data["notes"],
            effective_from=date.today()
        )
        db.add(policy)
    
    db.commit()
    print(f"✓ Created {len(policies)} vendor policies")

def seed_historical_proposals(db, vendor_id):
    """
    Create 8 historical proposals showing past bids and outcomes.
    
    Mix of WON, LOST, and REJECTED proposals to show reasoning patterns.
    """
    print("\n📝 Seeding Historical Proposals...")
    
    proposals_data = [
        {
            "year": 2025,
            "outcome": OutcomeEnum.WON,
            "summary": "Cloud infrastructure platform for e-commerce platform",
            "outcome_reason": "Met all requirements with competitive pricing and excellent support terms",
            "decisions": [
                {"dimension": DimensionEnum.MAINTENANCE_DURATION, "value": 12, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.WARRANTY_YEARS, "value": 3, "nature": NatureEnum.default, "confidence": 0.90},
                {"dimension": DimensionEnum.RESPONSE_TIME_HOURS, "value": 2, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.UPTIME_GUARANTEE, "value": 99.95, "nature": NatureEnum.conditional, "confidence": 0.85},
                {"dimension": DimensionEnum.SUPPORT_AVAILABILITY, "value": 24, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.COMPLIANCE_LEVEL, "value": 4, "nature": NatureEnum.default, "confidence": 1.0},
                {"dimension": DimensionEnum.PRICE_TOLERANCE, "value": 85000, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.DELIVERY_WINDOW_DAYS, "value": 45, "nature": NatureEnum.default, "confidence": 0.90},
            ]
        },
        {
            "year": 2024,
            "outcome": OutcomeEnum.LOST,
            "summary": "Enterprise storage infrastructure for healthcare provider",
            "outcome_reason": "Competitor offered higher uptime SLA (99.99%) at lower price point",
            "decisions": [
                {"dimension": DimensionEnum.MAINTENANCE_DURATION, "value": 16, "nature": NatureEnum.default, "confidence": 0.90},
                {"dimension": DimensionEnum.WARRANTY_YEARS, "value": 4, "nature": NatureEnum.default, "confidence": 0.88},
                {"dimension": DimensionEnum.RESPONSE_TIME_HOURS, "value": 3, "nature": NatureEnum.conditional, "confidence": 0.80, "violation": True},
                {"dimension": DimensionEnum.UPTIME_GUARANTEE, "value": 99.9, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.SUPPORT_AVAILABILITY, "value": 24, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.COMPLIANCE_LEVEL, "value": 4, "nature": NatureEnum.default, "confidence": 1.0},
                {"dimension": DimensionEnum.PRICE_TOLERANCE, "value": 120000, "nature": NatureEnum.default, "confidence": 0.90},
                {"dimension": DimensionEnum.DELIVERY_WINDOW_DAYS, "value": 60, "nature": NatureEnum.default, "confidence": 0.85},
            ]
        },
        {
            "year": 2024,
            "outcome": OutcomeEnum.WON,
            "summary": "Managed cloud services for financial services firm",
            "outcome_reason": "Best combination of compliance, uptime, and responsive support",
            "decisions": [
                {"dimension": DimensionEnum.MAINTENANCE_DURATION, "value": 8, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.WARRANTY_YEARS, "value": 5, "nature": NatureEnum.default, "confidence": 0.92},
                {"dimension": DimensionEnum.RESPONSE_TIME_HOURS, "value": 1, "nature": NatureEnum.exception, "confidence": 0.88},
                {"dimension": DimensionEnum.UPTIME_GUARANTEE, "value": 99.99, "nature": NatureEnum.conditional, "confidence": 0.90},
                {"dimension": DimensionEnum.SUPPORT_AVAILABILITY, "value": 24, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.COMPLIANCE_LEVEL, "value": 5, "nature": NatureEnum.default, "confidence": 1.0},
                {"dimension": DimensionEnum.PRICE_TOLERANCE, "value": 140000, "nature": NatureEnum.default, "confidence": 0.85},
                {"dimension": DimensionEnum.DELIVERY_WINDOW_DAYS, "value": 30, "nature": NatureEnum.default, "confidence": 0.95},
            ]
        },
        {
            "year": 2023,
            "outcome": OutcomeEnum.REJECTED,
            "summary": "Infrastructure services request (internal rejection)",
            "outcome_reason": "Decided to focus on cloud offerings instead; not pursuing infrastructure bids",
            "decisions": [
                {"dimension": DimensionEnum.MAINTENANCE_DURATION, "value": 6, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.WARRANTY_YEARS, "value": 3, "nature": NatureEnum.default, "confidence": 0.90},
                {"dimension": DimensionEnum.RESPONSE_TIME_HOURS, "value": 1, "nature": NatureEnum.exception, "confidence": 0.95},
                {"dimension": DimensionEnum.UPTIME_GUARANTEE, "value": 99.95, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.SUPPORT_AVAILABILITY, "value": 24, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.COMPLIANCE_LEVEL, "value": 3, "nature": NatureEnum.default, "confidence": 0.80},
                {"dimension": DimensionEnum.PRICE_TOLERANCE, "value": 75000, "nature": NatureEnum.default, "confidence": 0.90},
                {"dimension": DimensionEnum.DELIVERY_WINDOW_DAYS, "value": 60, "nature": NatureEnum.default, "confidence": 0.85},
            ]
        },
        {
            "year": 2023,
            "outcome": OutcomeEnum.WON,
            "summary": "Cloud migration services for retail company",
            "outcome_reason": "Strong technical fit, competitive pricing, and proven migration track record",
            "decisions": [
                {"dimension": DimensionEnum.MAINTENANCE_DURATION, "value": 10, "nature": NatureEnum.default, "confidence": 0.92},
                {"dimension": DimensionEnum.WARRANTY_YEARS, "value": 2, "nature": NatureEnum.default, "confidence": 0.85},
                {"dimension": DimensionEnum.RESPONSE_TIME_HOURS, "value": 3, "nature": NatureEnum.default, "confidence": 0.88},
                {"dimension": DimensionEnum.UPTIME_GUARANTEE, "value": 99.9, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.SUPPORT_AVAILABILITY, "value": 24, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.COMPLIANCE_LEVEL, "value": 3, "nature": NatureEnum.default, "confidence": 0.90},
                {"dimension": DimensionEnum.PRICE_TOLERANCE, "value": 95000, "nature": NatureEnum.default, "confidence": 0.92},
                {"dimension": DimensionEnum.DELIVERY_WINDOW_DAYS, "value": 60, "nature": NatureEnum.default, "confidence": 0.90},
            ]
        },
        {
            "year": 2023,
            "outcome": OutcomeEnum.LOST,
            "summary": "Government infrastructure contract (security clearance required)",
            "outcome_reason": "Could not meet security/compliance requirements; competitor had existing certifications",
            "decisions": [
                {"dimension": DimensionEnum.MAINTENANCE_DURATION, "value": 4, "nature": NatureEnum.exception, "confidence": 0.95},
                {"dimension": DimensionEnum.WARRANTY_YEARS, "value": 5, "nature": NatureEnum.default, "confidence": 0.90},
                {"dimension": DimensionEnum.RESPONSE_TIME_HOURS, "value": 1, "nature": NatureEnum.exception, "confidence": 0.95},
                {"dimension": DimensionEnum.UPTIME_GUARANTEE, "value": 99.99, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.SUPPORT_AVAILABILITY, "value": 24, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.COMPLIANCE_LEVEL, "value": 4, "nature": NatureEnum.default, "confidence": 0.70, "violation": True},
                {"dimension": DimensionEnum.PRICE_TOLERANCE, "value": 130000, "nature": NatureEnum.default, "confidence": 0.85},
                {"dimension": DimensionEnum.DELIVERY_WINDOW_DAYS, "value": 45, "nature": NatureEnum.default, "confidence": 0.85},
            ]
        },
        {
            "year": 2022,
            "outcome": OutcomeEnum.WON,
            "summary": "Managed services platform for media & entertainment",
            "outcome_reason": "Cost-effective solution with flexible pricing tiers",
            "decisions": [
                {"dimension": DimensionEnum.MAINTENANCE_DURATION, "value": 12, "nature": NatureEnum.default, "confidence": 0.90},
                {"dimension": DimensionEnum.WARRANTY_YEARS, "value": 2, "nature": NatureEnum.default, "confidence": 0.88},
                {"dimension": DimensionEnum.RESPONSE_TIME_HOURS, "value": 4, "nature": NatureEnum.default, "confidence": 0.85},
                {"dimension": DimensionEnum.UPTIME_GUARANTEE, "value": 99.5, "nature": NatureEnum.default, "confidence": 0.90},
                {"dimension": DimensionEnum.SUPPORT_AVAILABILITY, "value": 16, "nature": NatureEnum.conditional, "confidence": 0.85},
                {"dimension": DimensionEnum.COMPLIANCE_LEVEL, "value": 2, "nature": NatureEnum.default, "confidence": 0.90},
                {"dimension": DimensionEnum.PRICE_TOLERANCE, "value": 65000, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.DELIVERY_WINDOW_DAYS, "value": 90, "nature": NatureEnum.default, "confidence": 0.85},
            ]
        },
        {
            "year": 2022,
            "outcome": OutcomeEnum.LOST,
            "summary": "Premium SaaS platform for insurance industry",
            "outcome_reason": "Required higher uptime SLA and compliance level; couldn't match terms",
            "decisions": [
                {"dimension": DimensionEnum.MAINTENANCE_DURATION, "value": 4, "nature": NatureEnum.conditional, "confidence": 0.85},
                {"dimension": DimensionEnum.WARRANTY_YEARS, "value": 3, "nature": NatureEnum.default, "confidence": 0.88},
                {"dimension": DimensionEnum.RESPONSE_TIME_HOURS, "value": 2, "nature": NatureEnum.default, "confidence": 0.90},
                {"dimension": DimensionEnum.UPTIME_GUARANTEE, "value": 99.95, "nature": NatureEnum.default, "confidence": 0.90},
                {"dimension": DimensionEnum.SUPPORT_AVAILABILITY, "value": 24, "nature": NatureEnum.default, "confidence": 0.95},
                {"dimension": DimensionEnum.COMPLIANCE_LEVEL, "value": 4, "nature": NatureEnum.default, "confidence": 0.80, "violation": True},
                {"dimension": DimensionEnum.PRICE_TOLERANCE, "value": 110000, "nature": NatureEnum.default, "confidence": 0.88},
                {"dimension": DimensionEnum.DELIVERY_WINDOW_DAYS, "value": 60, "nature": NatureEnum.default, "confidence": 0.85},
            ]
        },
    ]
    
    for proposal_data in proposals_data:
        proposal = Proposal(
            vendor_id=vendor_id,
            year=proposal_data["year"],
            outcome=proposal_data["outcome"],
            outcome_reason=proposal_data["outcome_reason"],
            proposal_summary=proposal_data["summary"]
        )
        db.add(proposal)
        db.flush()  # Get the proposal ID
        
        # Add decisions for this proposal
        for decision_data in proposal_data["decisions"]:
            decision = ProposalDecision(
                proposal_id=proposal.id,
                dimension=decision_data["dimension"],
                value=decision_data["value"],
                nature=decision_data["nature"],
                confidence=decision_data.get("confidence", 0.90),
                violation_flag=decision_data.get("violation", False),
                source_excerpt=f"Extracted from {proposal_data['summary']} proposal document"
            )
            db.add(decision)
    
    db.commit()
    print(f"✓ Created {len(proposals_data)} historical proposals with decisions")

def seed_tenders(db):
    """
    Create 2 incoming tenders to evaluate.
    
    These represent new RFP requests that need responses.
    """
    print("\n📮 Seeding Incoming Tenders...")
    
    tenders_data = [
        {
            "tender_name": "RFP-2026-001: Enterprise Cloud Platform",
            "domain": "cloud",
            "year": 2026,
            "summary": "Large enterprise cloud infrastructure and managed services for manufacturing conglomerate. Requires high availability, compliance certifications, and 24/7 support.",
            "requirements": [
                {"dimension": DimensionEnum.MAINTENANCE_DURATION, "required_value": 8, "strictness": StrictnessEnum.mandatory},
                {"dimension": DimensionEnum.WARRANTY_YEARS, "required_value": 3, "strictness": StrictnessEnum.mandatory},
                {"dimension": DimensionEnum.RESPONSE_TIME_HOURS, "required_value": 2, "strictness": StrictnessEnum.mandatory},
                {"dimension": DimensionEnum.UPTIME_GUARANTEE, "required_value": 99.95, "strictness": StrictnessEnum.mandatory},
                {"dimension": DimensionEnum.SUPPORT_AVAILABILITY, "required_value": 24, "strictness": StrictnessEnum.mandatory},
                {"dimension": DimensionEnum.COMPLIANCE_LEVEL, "required_value": 4, "strictness": StrictnessEnum.mandatory},
                {"dimension": DimensionEnum.PRICE_TOLERANCE, "required_value": 120000, "strictness": StrictnessEnum.preferred},
                {"dimension": DimensionEnum.DELIVERY_WINDOW_DAYS, "required_value": 45, "strictness": StrictnessEnum.mandatory},
            ]
        },
        {
            "tender_name": "RFP-2026-002: Managed Security Services",
            "domain": "infrastructure",
            "year": 2026,
            "summary": "Managed security and infrastructure services for financial services firm. Focus on compliance, rapid incident response, and comprehensive monitoring.",
            "requirements": [
                {"dimension": DimensionEnum.MAINTENANCE_DURATION, "required_value": 4, "strictness": StrictnessEnum.mandatory},
                {"dimension": DimensionEnum.WARRANTY_YEARS, "required_value": 2, "strictness": StrictnessEnum.preferred},
                {"dimension": DimensionEnum.RESPONSE_TIME_HOURS, "required_value": 1, "strictness": StrictnessEnum.mandatory},
                {"dimension": DimensionEnum.UPTIME_GUARANTEE, "required_value": 99.99, "strictness": StrictnessEnum.mandatory},
                {"dimension": DimensionEnum.SUPPORT_AVAILABILITY, "required_value": 24, "strictness": StrictnessEnum.mandatory},
                {"dimension": DimensionEnum.COMPLIANCE_LEVEL, "required_value": 5, "strictness": StrictnessEnum.mandatory},
                {"dimension": DimensionEnum.PRICE_TOLERANCE, "required_value": 100000, "strictness": StrictnessEnum.preferred},
                {"dimension": DimensionEnum.DELIVERY_WINDOW_DAYS, "required_value": 30, "strictness": StrictnessEnum.mandatory},
            ]
        },
    ]
    
    for tender_data in tenders_data:
        tender = Tender(
            tender_name=tender_data["tender_name"],
            domain=tender_data["domain"],
            year=tender_data["year"],
            tender_summary=tender_data["summary"]
        )
        db.add(tender)
        db.flush()  # Get the tender ID
        
        # Add requirements for this tender
        for req_data in tender_data["requirements"]:
            requirement = TenderRequirement(
                tender_id=tender.id,
                dimension=req_data["dimension"],
                required_value=req_data["required_value"],
                strictness=req_data["strictness"]
            )
            db.add(requirement)
    
    db.commit()
    print(f"✓ Created {len(tenders_data)} incoming tenders with requirements")

def main():
    """Seed all data."""
    db = SessionLocal()
    
    try:
        print("\n" + "="*60)
        print("DecisionLedger - Seed Mock Data")
        print("="*60)
        
        # Get or create vendor
        vendor = db.query(Vendor).filter(Vendor.name == "TechVendor Solutions").first()
        if not vendor:
            print("\n✗ Vendor 'TechVendor Solutions' not found!")
            print("  Run docker-compose up first to initialize database.")
            sys.exit(1)
        
        vendor_id = vendor.id
        print(f"\n✓ Found vendor: {vendor.name} (ID: {vendor_id})")
        
        # Seed policies
        seed_vendor_policies(db, vendor_id)
        
        # Seed historical proposals
        seed_historical_proposals(db, vendor_id)
        
        # Seed tenders
        seed_tenders(db)
        
        print("\n" + "="*60)
        print("✓ All mock data seeded successfully!")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n✗ Seeding failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()