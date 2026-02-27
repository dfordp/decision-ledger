"""
Proposal management endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app import models, schemas

router = APIRouter(prefix="/proposals", tags=["proposals"])

# ============================================================================
# PROPOSAL ENDPOINTS
# ============================================================================

@router.get("", response_model=List[schemas.ProposalResponse])
def list_proposals(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    vendor_id: Optional[int] = None,
    year: Optional[int] = None,
    outcome: Optional[schemas.OutcomeEnum] = None,
    db: Session = Depends(get_db)
):
    """List all proposals with optional filtering."""
    query = db.query(models.Proposal)
    
    if vendor_id:
        query = query.filter(models.Proposal.vendor_id == vendor_id)
    if year:
        query = query.filter(models.Proposal.year == year)
    if outcome:
        query = query.filter(models.Proposal.outcome == outcome)
    
    proposals = query.offset(skip).limit(limit).all()
    return proposals

@router.get("/{proposal_id}", response_model=schemas.ProposalResponse)
def get_proposal(proposal_id: int, db: Session = Depends(get_db)):
    """Get proposal by ID with all decisions."""
    proposal = db.query(models.Proposal).filter(models.Proposal.id == proposal_id).first()
    
    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proposal {proposal_id} not found"
        )
    
    return proposal

@router.post("", response_model=schemas.ProposalResponse, status_code=status.HTTP_201_CREATED)
def create_proposal(proposal: schemas.ProposalCreate, db: Session = Depends(get_db)):
    """Create new proposal with decisions."""
    # Verify vendor exists
    vendor = db.query(models.Vendor).filter(models.Vendor.id == proposal.vendor_id).first()
    if not vendor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vendor {proposal.vendor_id} not found"
        )
    
    db_proposal = models.Proposal(
        vendor_id=proposal.vendor_id,
        year=proposal.year,
        outcome=proposal.outcome,
        outcome_reason=proposal.outcome_reason,
        proposal_summary=proposal.proposal_summary
    )
    
    # Add decisions
    for decision in proposal.decisions:
        db_decision = models.ProposalDecision(
            dimension=decision.dimension,
            value=decision.value,
            nature=decision.nature,
            confidence=decision.confidence,
            violation_flag=decision.violation_flag,
            source_excerpt=decision.source_excerpt
        )
        db_proposal.decisions.append(db_decision)
    
    db.add(db_proposal)
    db.commit()
    db.refresh(db_proposal)
    
    return db_proposal

@router.put("/{proposal_id}", response_model=schemas.ProposalResponse)
def update_proposal(
    proposal_id: int,
    proposal_update: schemas.ProposalUpdate,
    db: Session = Depends(get_db)
):
    """Update proposal."""
    proposal = db.query(models.Proposal).filter(models.Proposal.id == proposal_id).first()
    
    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proposal {proposal_id} not found"
        )
    
    update_data = proposal_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(proposal, field, value)
    
    db.commit()
    db.refresh(proposal)
    
    return proposal

@router.delete("/{proposal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_proposal(proposal_id: int, db: Session = Depends(get_db)):
    """Delete proposal and cascade to decisions."""
    proposal = db.query(models.Proposal).filter(models.Proposal.id == proposal_id).first()
    
    if not proposal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proposal {proposal_id} not found"
        )
    
    db.delete(proposal)
    db.commit()

# ============================================================================
# VENDOR PROPOSALS ENDPOINT
# ============================================================================

@router.get("/vendor/{vendor_id}", response_model=List[schemas.ProposalResponse])
def list_vendor_proposals(
    vendor_id: int,
    year: Optional[int] = None,
    outcome: Optional[schemas.OutcomeEnum] = None,
    db: Session = Depends(get_db)
):
    """List all proposals for a specific vendor."""
    vendor = db.query(models.Vendor).filter(models.Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vendor {vendor_id} not found"
        )
    
    query = db.query(models.Proposal).filter(models.Proposal.vendor_id == vendor_id)
    
    if year:
        query = query.filter(models.Proposal.year == year)
    if outcome:
        query = query.filter(models.Proposal.outcome == outcome)
    
    return query.all()