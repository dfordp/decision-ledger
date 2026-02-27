"""
FastAPI application for DecisionLedger POC.
Server-rendered HTML interface for tender evaluation.
"""

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from decimal import Decimal
from typing import Optional

from app.database import fetch_all, fetch_one
from app.reasoning import reason_about_requirement
from app.persistence import save_decision
from app.models import DecisionUpdate, ReasoningResult

# Initialize FastAPI app
app = FastAPI(
    title="DecisionLedger",
    description="AI-powered tender evaluation with historical memory",
    version="1.0.0"
)

# Setup Jinja2 templates
templates = Jinja2Templates(directory="app/templates")

# Helper to format currency/numbers
def format_number(value, unit: str = "") -> str:
    """Format numbers for display"""
    if value is None:
        return "N/A"
    
    if isinstance(value, Decimal):
        value = float(value)
    
    if unit == "%":
        return f"{value:.1f}%"
    elif unit == "days":
        return f"{int(value)} days"
    elif unit == "years":
        return f"{value:.1f} years"
    else:
        return f"{value:.1f}"

# Add custom filter to Jinja2
templates.env.filters['format_number'] = format_number

# ============================================================================
# HTML PAGES
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """
    Home page - Project overview and introduction to DecisionLedger
    """
    return templates.TemplateResponse("index.html", {
        "request": request
    })

@app.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    """
    History page - Show all historical proposals grouped by outcome
    """
    # Fetch all proposals
    proposals = fetch_all("""
        SELECT 
            p.*,
            COUNT(pd.id) as decision_count
        FROM proposals p
        LEFT JOIN proposal_decisions pd ON p.id = pd.proposal_id
        GROUP BY p.id
        ORDER BY p.submitted_at DESC
    """)
    
    # Group by outcome
    won_proposals = [p for p in proposals if p['outcome'] == 'WON']
    lost_proposals = [p for p in proposals if p['outcome'] == 'LOST']
    rejected_proposals = [p for p in proposals if p['outcome'] == 'REJECTED']
    
    return templates.TemplateResponse("history.html", {
        "request": request,
        "won_proposals": won_proposals,
        "lost_proposals": lost_proposals,
        "rejected_proposals": rejected_proposals
    })

@app.get("/proposal/{proposal_id}", response_class=HTMLResponse)
async def proposal_detail(request: Request, proposal_id: int):
    """
    Proposal detail page - Show all decisions for a specific proposal
    """
    # Fetch proposal
    proposal = fetch_one(
        "SELECT * FROM proposals WHERE id = %s",
        (proposal_id,)
    )
    
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    
    # Fetch all decisions for this proposal
    decisions = fetch_all("""
        SELECT 
            pd.*,
            ed.key as dimension_key,
            ed.display_name as dimension_name,
            ed.unit as dimension_unit
        FROM proposal_decisions pd
        JOIN evaluation_dimension ed ON pd.dimension_id = ed.id
        WHERE pd.proposal_id = %s
        ORDER BY ed.display_name
    """, (proposal_id,))
    
    return templates.TemplateResponse("proposal_detail.html", {
        "request": request,
        "proposal": proposal,
        "decisions": decisions
    })

@app.get("/tender/{tender_id}", response_class=HTMLResponse)
async def tender_page(
    request: Request, 
    tender_id: int,
    dimension: str = "MAINTENANCE_DURATION"
):
    """
    Tender evaluation page - Main interface for evaluating a tender
    Shows one dimension at a time with reasoning and evidence
    """
    # Fetch tender
    tender = fetch_one(
        "SELECT * FROM tenders WHERE id = %s",
        (tender_id,)
    )
    
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")
    
    # Get all dimensions for this tender
    all_dimensions = fetch_all("""
        SELECT DISTINCT
            ed.key,
            ed.display_name,
            ed.unit
        FROM tender_requirements tr
        JOIN evaluation_dimension ed ON tr.dimension_id = ed.id
        WHERE tr.tender_id = %s
        ORDER BY ed.display_name
    """, (tender_id,))
    
    # Get reasoning for current dimension
    try:
        reasoning_result = reason_about_requirement(tender_id, dimension)
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error reasoning about requirement: {str(e)}"
        )
    
    # Check if user has already made a decision for this dimension
    existing_decision = fetch_one("""
        SELECT pd.offered_value, pd.justification
        FROM proposal_decisions pd
        JOIN proposals p ON pd.proposal_id = p.id
        JOIN tenders t ON p.tender_name = t.name
        JOIN evaluation_dimension ed ON pd.dimension_id = ed.id
        WHERE t.id = %s AND ed.key = %s
    """, (tender_id, dimension))
    
    return templates.TemplateResponse("tender.html", {
        "request": request,
        "tender": tender,
        "all_dimensions": all_dimensions,
        "current_dimension": dimension,
        "reasoning": reasoning_result,
        "existing_decision": existing_decision
    })

# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.post("/api/reason/{tender_id}")
async def api_reason(tender_id: int, dimension: str):
    """
    API endpoint to get reasoning for a specific dimension
    Returns JSON with recommendation, status, reasoning, and evidence
    """
    try:
        result = reason_about_requirement(tender_id, dimension)
        
        # Convert to dict for JSON serialization
        return {
            "success": True,
            "dimension_key": result.dimension_key,
            "dimension_name": result.dimension_name,
            "dimension_unit": result.dimension_unit,
            "requirement": {
                "required_value": float(result.requirement.required_value),
                "strictness": result.requirement.strictness,
                "description": result.requirement.description
            },
            "policy": {
                "min_value": float(result.policy.min_value),
                "max_value": float(result.policy.max_value),
                "flexibility": result.policy.flexibility,
                "domain": result.policy.domain
            },
            "recommended_value": float(result.recommended_value),
            "status": result.status,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "evidence": [
                {
                    "tender_name": e.tender_name,
                    "outcome": e.outcome,
                    "offered_value": float(e.offered_value),
                    "similarity": e.similarity,
                    "justification": e.justification,
                    "source_excerpt": e.source_excerpt
                }
                for e in result.evidence
            ]
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )

@app.post("/api/decision/update")
async def api_update_decision(
    tender_id: int = Form(...),
    dimension: str = Form(...),
    final_value: float = Form(...),
    user_notes: str = Form(default="")
):
    """
    API endpoint to save user's decision
    Persists to database with embeddings for future similarity search
    """
    try:
        decision_id = save_decision(
            tender_id=tender_id,
            dimension_key=dimension,
            final_value=Decimal(str(final_value)),
            user_notes=user_notes
        )
        
        # Redirect back to tender page with success message
        return RedirectResponse(
            url=f"/tender/{tender_id}?dimension={dimension}&saved=true",
            status_code=303
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error saving decision: {str(e)}"
        )

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "DecisionLedger API"
    }

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    """Custom 404 page"""
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "error_code": 404,
            "error_message": "Page not found"
        },
        status_code=404
    )

@app.exception_handler(500)
async def server_error_handler(request: Request, exc: Exception):
    """Custom 500 page"""
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "error_code": 500,
            "error_message": "Internal server error"
        },
        status_code=500
    )

# ============================================================================
# STARTUP
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Run on application startup"""
    print("=" * 60)
    print("DecisionLedger - Starting up...")
    print("=" * 60)
    print()
    print("Available routes:")
    print("  → http://localhost:8000/")
    print("  → http://localhost:8000/history")
    print("  → http://localhost:8000/tender/1")
    print("  → http://localhost:8000/tender/2")
    print()