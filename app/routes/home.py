from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Vendor, Proposal, Tender
import os

# Setup Jinja2 templates
templates_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
templates = Jinja2Templates(directory=templates_dir)

router = APIRouter(tags=["home"])

@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    """
    Home page showing vendor profile and historical proposals.
    """
    try:
        # Get first vendor (for POC, we only have one)
        vendor = db.query(Vendor).first()
        
        if not vendor:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error_code": "404",
                "error_message": "No vendor found. Please seed the database with vendor data."
            })
        
        # Get all proposals for this vendor
        proposals = db.query(Proposal).filter(
            Proposal.vendor_id == vendor.id
        ).order_by(Proposal.year.desc()).all()
        
        return templates.TemplateResponse("home.html", {
            "request": request,
            "vendor": {
                "name": vendor.name,
                "risk_profile": vendor.risk_profile.value,
                "primary_domains": vendor.primary_domains
            },
            "proposals": [
                {
                    "id": p.id,
                    "year": p.year,
                    "outcome": p.outcome.value,
                    "summary": p.proposal_summary,
                    "outcome_reason": p.outcome_reason
                }
                for p in proposals
            ]
        })
    except Exception as e:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error_code": "500",
            "error_message": f"Failed to load home data: {str(e)}"
        })

# ============================================================================
# PROPOSAL DETAIL PAGE (HTML RENDERING)
# ============================================================================

@router.get("/proposal/{proposal_id}", response_class=HTMLResponse)
async def view_proposal(proposal_id: int, request: Request, db: Session = Depends(get_db)):
    """
    View proposal details page.
    """
    proposal = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    
    if not proposal:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error_code": "404",
            "error_message": f"Proposal {proposal_id} not found"
        })
    
    vendor = db.query(Vendor).filter(Vendor.id == proposal.vendor_id).first()
    
    return templates.TemplateResponse("proposal_detail.html", {
        "request": request,
        "proposal": {
            "id": proposal.id,
            "year": proposal.year,
            "outcome": proposal.outcome.value,
            "summary": proposal.proposal_summary,
            "reason": proposal.outcome_reason,
            "vendor_name": vendor.name if vendor else "Unknown"
        },
        "decisions": [
            {
                "dimension": d.dimension.value,
                "value": float(d.value),
                "nature": d.nature.value,
                "confidence": float(d.confidence) if d.confidence else None,
                "violation": d.violation_flag,
                "excerpt": d.source_excerpt
            }
            for d in proposal.decisions
        ] if proposal.decisions else []
    })

# ============================================================================
# TENDER DETAIL PAGE (HTML RENDERING)
# ============================================================================

@router.get("/tender/{tender_id}", response_class=HTMLResponse)
async def view_tender(tender_id: int, request: Request, db: Session = Depends(get_db)):
    """
    View tender details page.
    """
    tender = db.query(Tender).filter(Tender.id == tender_id).first()
    
    if not tender:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error_code": "404",
            "error_message": f"Tender {tender_id} not found"
        })
    
    return templates.TemplateResponse("tender_detail.html", {
        "request": request,
        "tender": {
            "id": tender.id,
            "name": tender.tender_name,
            "domain": tender.domain,
            "year": tender.year,
            "summary": tender.tender_summary
        },
        "requirements": [
            {
                "dimension": r.dimension.value,
                "required_value": float(r.required_value),
                "strictness": r.strictness.value
            }
            for r in tender.requirements
        ] if tender.requirements else []
    })

# ============================================================================
# TENDERS LIST PAGE (HTML RENDERING)
# ============================================================================

@router.get("/tender", response_class=HTMLResponse)
async def view_tenders(request: Request, db: Session = Depends(get_db)):
    """
    View all tenders page.
    """
    tenders = db.query(Tender).order_by(Tender.year.desc()).all()
    
    return templates.TemplateResponse("tenders_list.html", {
        "request": request,
        "tenders": [
            {
                "id": t.id,
                "name": t.tender_name,
                "domain": t.domain,
                "year": t.year,
                "summary": t.tender_summary,
                "requirements_count": len(t.requirements) if t.requirements else 0
            }
            for t in tenders
        ]
    })