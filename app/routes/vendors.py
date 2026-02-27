"""
Vendor management endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app import models, schemas

router = APIRouter(prefix="/vendors", tags=["vendors"])

# ============================================================================
# VENDOR ENDPOINTS
# ============================================================================

@router.get("", response_model=List[schemas.VendorResponse])
def list_vendors(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    risk_profile: Optional[schemas.RiskProfileEnum] = None,
    db: Session = Depends(get_db)
):
    """List all vendors with optional filtering."""
    query = db.query(models.Vendor)
    
    if risk_profile:
        query = query.filter(models.Vendor.risk_profile == risk_profile)
    
    vendors = query.offset(skip).limit(limit).all()
    return vendors

@router.get("/{vendor_id}", response_model=schemas.VendorDetailResponse)
def get_vendor(vendor_id: int, db: Session = Depends(get_db)):
    """Get vendor by ID with all policies."""
    vendor = db.query(models.Vendor).filter(models.Vendor.id == vendor_id).first()
    
    if not vendor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vendor {vendor_id} not found"
        )
    
    return vendor

@router.post("", response_model=schemas.VendorResponse, status_code=status.HTTP_201_CREATED)
def create_vendor(vendor: schemas.VendorCreate, db: Session = Depends(get_db)):
    """Create new vendor."""
    # Check if vendor already exists
    existing = db.query(models.Vendor).filter(models.Vendor.name == vendor.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Vendor '{vendor.name}' already exists"
        )
    
    db_vendor = models.Vendor(
        name=vendor.name,
        primary_domains=vendor.primary_domains,
        risk_profile=vendor.risk_profile
    )
    db.add(db_vendor)
    db.commit()
    db.refresh(db_vendor)
    
    return db_vendor

@router.put("/{vendor_id}", response_model=schemas.VendorResponse)
def update_vendor(
    vendor_id: int,
    vendor_update: schemas.VendorUpdate,
    db: Session = Depends(get_db)
):
    """Update vendor."""
    vendor = db.query(models.Vendor).filter(models.Vendor.id == vendor_id).first()
    
    if not vendor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vendor {vendor_id} not found"
        )
    
    update_data = vendor_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(vendor, field, value)
    
    db.commit()
    db.refresh(vendor)
    
    return vendor

@router.delete("/{vendor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vendor(vendor_id: int, db: Session = Depends(get_db)):
    """Delete vendor and cascade to policies/proposals."""
    vendor = db.query(models.Vendor).filter(models.Vendor.id == vendor_id).first()
    
    if not vendor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vendor {vendor_id} not found"
        )
    
    db.delete(vendor)
    db.commit()

# ============================================================================
# VENDOR POLICY ENDPOINTS
# ============================================================================

@router.get("/{vendor_id}/policies", response_model=List[schemas.VendorPolicyResponse])
def list_vendor_policies(
    vendor_id: int,
    dimension: Optional[schemas.DimensionEnum] = None,
    domain: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """List policies for a specific vendor."""
    vendor = db.query(models.Vendor).filter(models.Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vendor {vendor_id} not found"
        )
    
    query = db.query(models.VendorPolicy).filter(models.VendorPolicy.vendor_id == vendor_id)
    
    if dimension:
        query = query.filter(models.VendorPolicy.dimension == dimension)
    if domain:
        query = query.filter(models.VendorPolicy.domain == domain)
    
    return query.all()

@router.post("/{vendor_id}/policies", response_model=schemas.VendorPolicyResponse, status_code=status.HTTP_201_CREATED)
def create_vendor_policy(
    vendor_id: int,
    policy: schemas.VendorPolicyCreate,
    db: Session = Depends(get_db)
):
    """Add policy to vendor."""
    vendor = db.query(models.Vendor).filter(models.Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vendor {vendor_id} not found"
        )
    
    db_policy = models.VendorPolicy(
        vendor_id=vendor_id,
        dimension=policy.dimension,
        domain=policy.domain,
        max_value=policy.max_value,
        flexibility=policy.flexibility,
        notes=policy.notes,
        effective_from=policy.effective_from,
        effective_to=policy.effective_to
    )
    db.add(db_policy)
    db.commit()
    db.refresh(db_policy)
    
    return db_policy

@router.put("/policies/{policy_id}", response_model=schemas.VendorPolicyResponse)
def update_vendor_policy(
    policy_id: int,
    policy_update: schemas.VendorPolicyCreate,
    db: Session = Depends(get_db)
):
    """Update vendor policy."""
    policy = db.query(models.VendorPolicy).filter(models.VendorPolicy.id == policy_id).first()
    
    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy {policy_id} not found"
        )
    
    update_data = policy_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(policy, field, value)
    
    db.commit()
    db.refresh(policy)
    
    return policy

@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vendor_policy(policy_id: int, db: Session = Depends(get_db)):
    """Delete vendor policy."""
    policy = db.query(models.VendorPolicy).filter(models.VendorPolicy.id == policy_id).first()
    
    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy {policy_id} not found"
        )
    
    db.delete(policy)
    db.commit()