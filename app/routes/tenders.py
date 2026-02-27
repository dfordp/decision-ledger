"""
Tender management endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app import models, schemas

router = APIRouter(prefix="/tenders", tags=["tenders"])

# ============================================================================
# TENDER ENDPOINTS
# ============================================================================

@router.get("", response_model=List[schemas.TenderResponse])
def list_tenders(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    year: Optional[int] = None,
    domain: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """List all tenders with optional filtering."""
    query = db.query(models.Tender)
    
    if year:
        query = query.filter(models.Tender.year == year)
    if domain:
        query = query.filter(models.Tender.domain == domain)
    
    tenders = query.offset(skip).limit(limit).all()
    return tenders

@router.get("/{tender_id}", response_model=schemas.TenderResponse)
def get_tender(tender_id: int, db: Session = Depends(get_db)):
    """Get tender by ID with all requirements."""
    tender = db.query(models.Tender).filter(models.Tender.id == tender_id).first()
    
    if not tender:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender {tender_id} not found"
        )
    
    return tender

@router.post("", response_model=schemas.TenderResponse, status_code=status.HTTP_201_CREATED)
def create_tender(tender: schemas.TenderCreate, db: Session = Depends(get_db)):
    """Create new tender with requirements."""
    db_tender = models.Tender(
        tender_name=tender.tender_name,
        domain=tender.domain,
        year=tender.year,
        tender_summary=tender.tender_summary
    )
    
    # Add requirements
    for req in tender.requirements:
        db_requirement = models.TenderRequirement(
            dimension=req.dimension,
            required_value=req.required_value,
            strictness=req.strictness
        )
        db_tender.requirements.append(db_requirement)
    
    db.add(db_tender)
    db.commit()
    db.refresh(db_tender)
    
    return db_tender

@router.put("/{tender_id}", response_model=schemas.TenderResponse)
def update_tender(
    tender_id: int,
    tender_update: schemas.TenderUpdate,
    db: Session = Depends(get_db)
):
    """Update tender."""
    tender = db.query(models.Tender).filter(models.Tender.id == tender_id).first()
    
    if not tender:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender {tender_id} not found"
        )
    
    update_data = tender_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tender, field, value)
    
    db.commit()
    db.refresh(tender)
    
    return tender

@router.delete("/{tender_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tender(tender_id: int, db: Session = Depends(get_db)):
    """Delete tender and cascade to requirements."""
    tender = db.query(models.Tender).filter(models.Tender.id == tender_id).first()
    
    if not tender:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender {tender_id} not found"
        )
    
    db.delete(tender)
    db.commit()

# ============================================================================
# TENDER REQUIREMENTS ENDPOINTS
# ============================================================================

@router.get("/{tender_id}/requirements", response_model=List[schemas.TenderRequirementResponse])
def list_tender_requirements(
    tender_id: int,
    dimension: Optional[schemas.DimensionEnum] = None,
    db: Session = Depends(get_db)
):
    """List requirements for a specific tender."""
    tender = db.query(models.Tender).filter(models.Tender.id == tender_id).first()
    if not tender:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender {tender_id} not found"
        )
    
    query = db.query(models.TenderRequirement).filter(models.TenderRequirement.tender_id == tender_id)
    
    if dimension:
        query = query.filter(models.TenderRequirement.dimension == dimension)
    
    return query.all()

@router.post("/{tender_id}/requirements", response_model=schemas.TenderRequirementResponse, status_code=status.HTTP_201_CREATED)
def create_tender_requirement(
    tender_id: int,
    requirement: schemas.TenderRequirementCreate,
    db: Session = Depends(get_db)
):
    """Add requirement to tender."""
    tender = db.query(models.Tender).filter(models.Tender.id == tender_id).first()
    if not tender:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender {tender_id} not found"
        )
    
    db_requirement = models.TenderRequirement(
        tender_id=tender_id,
        dimension=requirement.dimension,
        required_value=requirement.required_value,
        strictness=requirement.strictness
    )
    
    db.add(db_requirement)
    db.commit()
    db.refresh(db_requirement)
    
    return db_requirement

@router.delete("/requirements/{requirement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tender_requirement(requirement_id: int, db: Session = Depends(get_db)):
    """Delete tender requirement."""
    requirement = db.query(models.TenderRequirement).filter(models.TenderRequirement.id == requirement_id).first()
    
    if not requirement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Requirement {requirement_id} not found"
        )
    
    db.delete(requirement)
    db.commit()