"""
FastAPI application for DecisionLedger POC.
Server-rendered HTML interface for tender evaluation.
All decisions stored in memory (no database persistence for POC).
"""

from datetime import datetime
import os
import re
import tempfile
from psycopg2.extras import Json

from fastapi import FastAPI, Request, Form, File, UploadFile, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from decimal import Decimal
from typing import Optional
from fastapi.responses import StreamingResponse

from app.database import fetch_all, fetch_one, execute_query, insert_and_return_id
from app.reasoning import reason_about_requirement, perform_ai_evaluation
from app.models import DecisionUpdate, ReasoningResult
from app.document_ingestion import (
    detect_file_type,
    is_scanned_pdf,
    extract_with_pypdf,
    extract_with_ocr,
    extract_with_excel,
    normalize_document,
    chunk_document
)
from app.rpn_suggestion_engine import get_rpn_suggestions


# Initialize FastAPI app
app = FastAPI(
    title="DecisionLedger",
    description="AI-powered tender evaluation with historical memory",
    version="1.0.0"
)

# In-memory store for decisions (POC - no database persistence)
# Structure: {tender_id: {dimension_key: {offered_value, justification, saved_at}}}
decisions_store = {}

# Session-scoped evaluation cache (AI evaluations for PFMEA canvas)
# Structure: {part_id: {entry_id: {status, justification, timestamp}}}
evaluation_cache = {}

# Mount static files only if directory exists
static_dir = "app/static"
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
else:
    print(f"Warning: Static directory '{static_dir}' not found. Skipping static file mounting.")

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
    Handles both database dimensions and new extracted dimensions (memory store)
    """
    # Fetch tender
    tender = fetch_one(
        "SELECT * FROM tenders WHERE id = %s",
        (tender_id,)
    )
    
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")
    
    # Get all dimensions for this tender FROM DATABASE
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
    
    # Add any new dimensions from memory store (extracted by Groq)
    all_dim_keys = {d['key'] for d in all_dimensions}
    if tender_id in decisions_store:
        for mem_dimension in decisions_store[tender_id].keys():
            if mem_dimension not in all_dim_keys:
                # New dimension from extraction - add to list
                all_dimensions.append({
                    'key': mem_dimension,
                    'display_name': mem_dimension.replace('_', ' ').title(),
                    'unit': 'N/A'
                })
    
    # Get reasoning for current dimension (with graceful fallback for new dimensions)
    reasoning_result = None
    try:
        reasoning_result = reason_about_requirement(tender_id, dimension)
    except Exception as e:
        print(f"⚠️ Could not get reasoning for {dimension}: {e}")
        # Continue without reasoning for new/extracted dimensions
        reasoning_result = None
    
    # Check if user has already made a decision for this dimension (from memory)
    existing_decision = None
    if tender_id in decisions_store and dimension in decisions_store[tender_id]:
        decision = decisions_store[tender_id][dimension]
        existing_decision = {
            'offered_value': decision['offered_value'],
            'justification': decision['justification'],
            'requirement_value': decision.get('requirement_value', '')  # Include extracted requirement
        }
    
    return templates.TemplateResponse("tender.html", {
        "request": request,
        "tender": tender,
        "all_dimensions": all_dimensions,
        "current_dimension": dimension,
        "reasoning": reasoning_result,
        "existing_decision": existing_decision
    })


@app.get("/tender/{tender_id}/canvas", response_class=HTMLResponse)
async def tender_canvas(request: Request, tender_id: int):
    """
    Canvas-style PDF extraction interface.
    Load PDF → Extract → Match against vector DB → Show options
    """
    # Fetch tender (minimal info)
    tender = fetch_one(
        "SELECT * FROM tenders WHERE id = %s",
        (tender_id,)
    )
    
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")
    
    # Get ALL available dimensions (not tied to requirements)
    all_dimensions = fetch_all("""
        SELECT 
            ed.id,
            ed.key,
            ed.display_name,
            ed.unit,
            vp.min_value as policy_min,
            vp.max_value as policy_max,
            vp.flexibility as policy_flexibility,
            vp.domain as policy_domain
        FROM evaluation_dimension ed
        LEFT JOIN vendor_policy vp ON ed.id = vp.dimension_id 
            AND (vp.domain = %s OR vp.domain = 'GLOBAL')
        ORDER BY 
            ed.display_name,
            CASE 
                WHEN vp.domain = %s THEN 0
                WHEN vp.domain = 'GLOBAL' THEN 1
                ELSE 2
            END
    """, (tender['domain'], tender['domain']))
    
    # Convert Decimals
    dimensions_list = []
    seen_keys = set()
    
    for dim in all_dimensions:
        if dim['key'] in seen_keys:
            continue
        seen_keys.add(dim['key'])
        
        dimensions_list.append({
            'dimension_id': dim['id'],
            'dimension_key': dim['key'],
            'dimension_name': dim['display_name'],
            'dimension_unit': dim['unit'],
            'policy_min': float(dim['policy_min']) if dim['policy_min'] else None,
            'policy_max': float(dim['policy_max']) if dim['policy_max'] else None,
            'policy_flexibility': dim['policy_flexibility'],
            'policy_domain': dim['policy_domain'],
            'extracted_value': None,  # Will be filled by PDF extraction
            'extracted_text': None,
            'clarity_status': 'PENDING'  # PENDING until PDF uploaded
        })
    
    print(f"\n=== CANVAS VIEW: {tender['name']} ===")
    print(f"Available dimensions: {len(dimensions_list)}")
    print("Waiting for PDF upload to extract requirements...")
    print("=" * 50)
    
    return templates.TemplateResponse("canvas_template.html", {
        "request": request,
        "tender": tender,
        "dimensions": dimensions_list
    })


@app.post("/api/tender/{tender_id}/generate-proposal")
async def generate_proposal(tender_id: int):
    """
    Generate final proposal document with all decisions.
    Returns JSON with proposal text and download link.
    """
    tender = fetch_one("SELECT * FROM tenders WHERE id = %s", (tender_id,))
    
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")
    
    # Get all decisions from memory store
    decisions = []
    processed_keys = set()
    
    if tender_id in decisions_store:
        # Get tender requirements from DB to match with stored decisions
        requirements = fetch_all("""
            SELECT 
                ed.display_name,
                ed.unit,
                tr.required_value,
                tr.strictness,
                ed.key
            FROM tender_requirements tr
            JOIN evaluation_dimension ed ON tr.dimension_id = ed.id
            WHERE tr.tender_id = %s
            ORDER BY ed.display_name
        """, (tender_id,))
        
        for req in requirements:
            dim_key = req['key']
            processed_keys.add(dim_key)
            if dim_key in decisions_store[tender_id]:
                decision = decisions_store[tender_id][dim_key]
                decisions.append({
                    'display_name': req['display_name'],
                    'unit': req['unit'],
                    'offered_value': decision['offered_value'],
                    'justification': decision['justification'],
                    'required_value': req['required_value'],
                    'strictness': req['strictness']
                })
        
        # Add newly extracted fields (not in database requirements)
        for new_dim_key, decision_data in decisions_store[tender_id].items():
            if new_dim_key not in processed_keys:
                # This is a new field extracted from PDF that's not in the DB
                decisions.append({
                    'display_name': new_dim_key.replace('_', ' ').title(),
                    'unit': 'N/A',
                    'offered_value': decision_data['offered_value'],
                    'justification': decision_data['justification'],
                    'required_value': None,
                    'strictness': 'NEW_FIELD'
                })
    
    if not decisions:
        raise HTTPException(
            status_code=400, 
            detail="No decisions found. Complete all requirements first."
        )
    
    # Generate proposal text
    proposal_text = f"""
PROPOSAL SUBMISSION
{'=' * 70}

Tender: {tender['name']}
Domain: {tender['domain']}
Year: {tender['year']}
Submission Date: {datetime.now().strftime('%B %d, %Y')}

{'=' * 70}
COMMERCIAL TERMS
{'=' * 70}

"""
    
    for decision in decisions:
        proposal_text += f"""
{decision['display_name']}
{'-' * 50}
Requirement: {decision['required_value']} {decision['unit']} ({decision['strictness']})
Our Offer:   {float(decision['offered_value']):.2f} {decision['unit']}
Rationale:   {decision['justification']}

"""
    
    proposal_text += f"""
{'=' * 70}
DECLARATION

We confirm that all terms stated above are binding and represent our 
final offer for the tender: {tender['name']}.

All policy compliance checks have been completed and approved.

Generated by DecisionLedger on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{'=' * 70}
"""
    
    return {
        "success": True,
        "tender_id": tender_id,
        "tender_name": tender['name'],
        "proposal_text": proposal_text,
        "decision_count": len(decisions),
        "generated_at": datetime.now().isoformat()
    }


@app.get("/api/tender/{tender_id}/mcq-options/{dimension_key}")
async def get_mcq_options(tender_id: int, dimension_key: str):
    """
    Generate MCQ options for a specific requirement based on:
    1. Exact requirement match
    2. Policy minimum
    3. Policy maximum  
    4. Historical average from similar WON cases
    """
    # Get requirement and policy
    requirement_data = fetch_one("""
        SELECT 
            tr.required_value,
            tr.strictness,
            ed.display_name,
            ed.unit,
            vp.min_value as policy_min,
            vp.max_value as policy_max,
            vp.flexibility
        FROM tender_requirements tr
        JOIN evaluation_dimension ed ON tr.dimension_id = ed.id
        LEFT JOIN vendor_policy vp ON ed.id = vp.dimension_id
        WHERE tr.tender_id = %s AND ed.key = %s
        LIMIT 1
    """, (tender_id, dimension_key))
    
    if not requirement_data:
        raise HTTPException(status_code=404, detail="Requirement not found")
    
    # Get reasoning to find historical average
    try:
        reasoning = reason_about_requirement(tender_id, dimension_key)
    except Exception as e:
        # If reasoning fails, continue with basic options
        print(f"Warning: Could not get reasoning: {e}")
        reasoning = None
    
    # Build 4 MCQ options
    options = []
    
    # Option 1: Exact requirement (if within policy)
    required_val = float(requirement_data['required_value'])
    policy_min = float(requirement_data['policy_min']) if requirement_data['policy_min'] else None
    policy_max = float(requirement_data['policy_max']) if requirement_data['policy_max'] else None
    
    if policy_min and policy_max:
        if policy_min <= required_val <= policy_max:
            options.append({
                "value": required_val,
                "label": f"{required_val} {requirement_data['unit']} (Match Requirement)",
                "rationale": f"Exactly meets the {requirement_data['strictness']} requirement",
                "type": "requirement"
            })
        
        # Option 2: Policy minimum (conservative)
        options.append({
            "value": policy_min,
            "label": f"{policy_min} {requirement_data['unit']} (Policy Minimum)",
            "rationale": "Conservative approach - minimum acceptable per company policy",
            "type": "policy_min"
        })
        
        # Option 3: Policy maximum (aggressive)
        options.append({
            "value": policy_max,
            "label": f"{policy_max} {requirement_data['unit']} (Policy Maximum)",
            "rationale": "Aggressive approach - maximum we can commit per policy",
            "type": "policy_max"
        })
    
    # Option 4: AI Recommendation (based on history)
    if reasoning:
        recommended_val = float(reasoning.recommended_value)
        options.append({
            "value": recommended_val,
            "label": f"{recommended_val} {requirement_data['unit']} (AI Recommended)",
            "rationale": f"Based on {len(reasoning.evidence)} similar past decisions",
            "type": "recommended",
            "confidence": reasoning.confidence
        })
    else:
        # Fallback: use requirement value
        options.append({
            "value": required_val,
            "label": f"{required_val} {requirement_data['unit']} (Baseline)",
            "rationale": "Baseline recommendation based on requirement",
            "type": "recommended",
            "confidence": 0.5
        })
    
    # Deduplicate options with same value
    seen_values = set()
    unique_options = []
    for opt in options:
        if opt['value'] not in seen_values:
            seen_values.add(opt['value'])
            unique_options.append(opt)
    
    # Ensure we have 4 options (add mid-range if needed)
    if len(unique_options) < 4 and policy_min and policy_max:
        mid_value = round((policy_min + policy_max) / 2, 1)
        if mid_value not in seen_values:
            unique_options.insert(2, {
                "value": mid_value,
                "label": f"{mid_value} {requirement_data['unit']} (Balanced Mid-Range)",
                "rationale": "Balanced approach between minimum and maximum policy limits",
                "type": "balanced"
            })
    
    # Build reasoning dict
    reasoning_dict = {
        "status": reasoning.status if reasoning else "UNKNOWN",
        "confidence": reasoning.confidence if reasoning else 0.5,
        "bullets": reasoning.reasoning if reasoning else [
            "No historical data available",
            "Recommendation based on policy bounds only"
        ]
    }
    
    return {
        "dimension": requirement_data['display_name'],
        "unit": requirement_data['unit'],
        "requirement": required_val,
        "strictness": requirement_data['strictness'],
        "options": unique_options[:4],  # Max 4 options
        "reasoning": reasoning_dict
    }


@app.get("/api/tender/{tender_id}/pdf")
async def get_tender_pdf(tender_id: int):
    """
    Serve the tender PDF document for viewing/annotation
    """
    from fastapi.responses import FileResponse
    import os
    
    # Path to tender PDFs
    pdf_path = f"data/tenders/tender_{tender_id}.pdf"
    
    if not os.path.exists(pdf_path):
        # Return a sample/default PDF if specific one doesn't exist
        pdf_path = "data/tenders/sample_tender.pdf"
    
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF not found")
    
    return FileResponse(
        pdf_path,
        media_type='application/pdf',
        filename=f'tender_{tender_id}.pdf'
    )


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
    final_value: str = Form(...),
    user_notes: str = Form(default=""),
    requirement_value: str = Form(default=None)
):
    """
    API endpoint to save user's decision IN MEMORY (POC mode)
    Data is not persisted to database
    Handles both numeric and boolean values
    Stores extracted requirement value for new fields
    """
    try:
        # Initialize tender store if not exists
        if tender_id not in decisions_store:
            decisions_store[tender_id] = {}
        
        # Try to convert to float, otherwise keep as string (for booleans/text)
        try:
            converted_value = float(final_value)
        except (ValueError, TypeError):
            # Keep as-is for boolean strings like "true"/"false" or text values
            converted_value = final_value
        
        # Store decision in memory
        decisions_store[tender_id][dimension] = {
            'offered_value': converted_value,
            'justification': user_notes,
            'requirement_value': requirement_value,  # Store extracted requirement for new fields
            'saved_at': datetime.now().isoformat()
        }
        
        print(f"✓ Decision stored in memory - Tender {tender_id}, {dimension}: {converted_value}")
        
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
        "service": "DecisionLedger API",
        "mode": "POC",
        "storage": "in-memory"
    }


from fastapi import UploadFile, File
import PyPDF2
import io
import re
from groq import Groq
import os

# Initialize Groq client
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

@app.post("/api/tender/{tender_id}/upload-pdf")
async def upload_and_extract_pdf(
    tender_id: int,
    pdf_file: UploadFile = File(...)
):
    """
    Upload PDF (native or scanned) → Extract text → Use Groq to intelligently parse requirements
    
    Handles:
    - Native PDFs with selectable text (PyPDF2)
    - Scanned PDFs / image-only (Tesseract OCR)
    
    Returns all extracted fields with color-coded status, page numbers
    """
    try:
        # Read PDF
        pdf_bytes = await pdf_file.read()
        
        print(f"\n{'='*70}")
        print(f"📥 PDF UPLOAD: {pdf_file.filename}")
        print(f"{'='*70}")
        
        # Step 1: Detect file type and extract accordingly
        file_type = detect_file_type(pdf_file.filename)
        print(f"\n🔍 Detecting document type...")
        print(f"📊 File type: {file_type}")
        
        if file_type == "PDF":
            if is_scanned_pdf(pdf_bytes):
                print(f"📋 Strategy: Using OCR (EasyOCR)")
                pages_text = extract_with_ocr(pdf_bytes)
            else:
                print(f"📄 Strategy: Using PyPDF2")
                pages_text = extract_with_pypdf(pdf_bytes)
        elif file_type == "Excel":
            print(f"📊 Strategy: Using openpyxl")
            pages_text = extract_with_excel(pdf_bytes)
        else:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": f"Unsupported file type: {file_type}. Supported: PDF, Excel"
                }
            )
        
        if not pages_text:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "Could not extract text from PDF. Check file format or install Tesseract OCR."
                }
            )
        
        # Step 2: Normalize document
        print(f"\n📝 Normalizing document...")
        full_text = normalize_document(pages_text)
        print(f"✅ Total characters extracted: {len(full_text)}")
        
        # Get all existing dimensions from DB
        db_dimensions = fetch_all("""
            SELECT 
                ed.id,
                ed.key,
                ed.display_name,
                ed.unit,
                ed.data_type,
                vp.min_value as policy_min,
                vp.max_value as policy_max,
                vp.flexibility
            FROM evaluation_dimension ed
            LEFT JOIN vendor_policy vp ON ed.id = vp.dimension_id
            ORDER BY ed.display_name
        """)
        
        # Build context for Groq
        db_fields_context = "\n".join([
            f"- {dim['display_name']} (type: {dim['data_type']}, unit: {dim['unit']}, policy range: {dim['policy_min']}-{dim['policy_max']})"
            for dim in db_dimensions
        ])
        
        # Enhanced Groq prompt for all requirement types
        groq_prompt = f"""You are a tender document analyzer. Extract ALL requirements from the document.

For EACH requirement found, provide:
1. **requirement_number**: The serial/reference number mentioned in document (e.g., "Requirement 1", "Clause 3.2", "Item 5")
2. **field_name**: Name of the requirement (e.g., "Maintenance Duration", "Warranty Period")
3. **value**: The extracted value
4. **value_type**: One of "NUMERIC", "BOOLEAN", "ENUM", "TEXT"
5. **unit**: Unit if applicable (e.g., "years", "days", "%", "stars", "N/A")
6. **full_context**: The complete sentence/paragraph where you found it
7. **page_number**: Which page number this appears on (look for [PAGE n] markers)

Value Type Guidelines:
- **NUMERIC**: Any measurable quantity (4 years, 120 days, 55%, 5.5 COP, 750 GWP)
- **BOOLEAN**: Yes/No, Mandatory/Optional, Required/Not Required (convert to true/false)
- **ENUM**: Fixed choices (e.g., BEE Star Rating: "5-Star", Compliance: "ISO 14001")
- **TEXT**: Descriptive requirements that don't fit above

Known reference fields (match to these if similar):
{db_fields_context}

TENDER DOCUMENT TEXT:
{full_text}

Return ONLY a valid JSON array with this structure:
[
  {{
    "requirement_number": "Requirement: Maintenance Duration",
    "field_name": "Maintenance Duration",
    "value": 6,
    "value_type": "NUMERIC",
    "unit": "years",
    "full_context": "The bidder shall provide comprehensive preventive and corrective maintenance for a minimum duration of six (6) years from the date of commissioning.",
    "page_number": 1
  }},
  {{
    "requirement_number": "Requirement: IoT & Predictive Maintenance",
    "field_name": "IoT Enabled",
    "value": true,
    "value_type": "BOOLEAN",
    "unit": "N/A",
    "full_context": "The proposed system shall include IoT-enabled sensors and a centralized monitoring platform...",
    "page_number": 2
  }},
  {{
    "requirement_number": "Requirement: Energy Efficiency Standards",
    "field_name": "Energy Efficiency Rating",
    "value": "BEE 5-Star",
    "value_type": "ENUM",
    "unit": "rating",
    "full_context": "HVAC systems must comply with BEE 5-Star rating and achieve a minimum Coefficient of Performance (COP) of 5.5...",
    "page_number": 2
  }}
]

Extract ALL requirements. Do not miss any fields."""

        print("\n📤 Sending to Groq for intelligent extraction...")
        
        groq_response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise document parser. Return only valid JSON arrays."
                },
                {
                    "role": "user",
                    "content": groq_prompt
                }
            ],
            temperature=0.1,
            max_tokens=5000
        )
        
        groq_output = groq_response.choices[0].message.content.strip()
        
        # Clean JSON response and extract JSON array
        if groq_output.startswith("```json"):
            groq_output = groq_output[7:]
        if groq_output.startswith("```"):
            groq_output = groq_output[3:]
        if groq_output.endswith("```"):
            groq_output = groq_output[:-3]
        groq_output = groq_output.strip()
        
        print(f"\n📥 Groq response:\n{groq_output[:800]}...")
        
        # Extract JSON array from response (may have text before it)
        import json
        json_start = groq_output.find('[')
        json_end = groq_output.rfind(']')
        
        if json_start == -1 or json_end == -1:
            print("❌ Could not find JSON array in Groq response")
            return JSONResponse(status_code=500, content={"success": False, "error": "Invalid Groq response format"})
        
        json_str = groq_output[json_start:json_end+1]
        groq_fields = json.loads(json_str)
        
        # Build lookup for existing dimensions
        db_lookup = {}
        for dim in db_dimensions:
            db_lookup[dim['display_name'].lower()] = dim
            db_lookup[dim['key'].lower()] = dim
        
        # Process each field from Groq
        extracted_fields = []
        
        for idx, groq_field in enumerate(groq_fields, start=1):
            field_name = groq_field['field_name']
            value = groq_field['value']
            value_type = groq_field['value_type']
            unit = groq_field['unit']
            context = groq_field.get('full_context', '')
            page_number = groq_field.get('page_number', 1)
            requirement_number = groq_field.get('requirement_number', f"Req {idx}")
            
            field_key = field_name.lower()
            
            # Parse numeric values that may contain units (e.g., "30 days", "3 mm")
            if value_type == "NUMERIC" and isinstance(value, str):
                match = re.match(r'^([\d.]+)', value.strip())
                if match:
                    numeric_value = float(match.group(1))
                    unit_part = value[len(match.group(1)):].strip()
                    if unit_part and unit == "N/A":
                        unit = unit_part
                    value = numeric_value
            elif value_type == "NUMERIC":
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    print(f"⚠️ Could not parse numeric value: {value}")
                    value = None
            
            # Check if field exists in DB
            dimension_key = None
            dimension_name = field_name
            policy_min = None
            policy_max = None
            policy_flexibility = None
            status = 'red'  # Default: not in DB
            
            # Exact match in DB
            if field_key in db_lookup:
                dim = db_lookup[field_key]
                dimension_key = dim['key']
                dimension_name = dim['display_name']
                policy_min = float(dim['policy_min']) if dim['policy_min'] else None
                policy_max = float(dim['policy_max']) if dim['policy_max'] else None
                policy_flexibility = dim['flexibility']
                
                # Check if value matches policy (only for numeric)
                if value_type == "NUMERIC" and value is not None and policy_min and policy_max:
                    numeric_val = float(value)
                    if policy_min <= numeric_val <= policy_max:
                        status = 'green'
                    else:
                        status = 'yellow'
                elif value_type == "BOOLEAN":
                    status = 'green' if value else 'yellow'
                else:
                    status = 'green'  # In DB, non-numeric
            else:
                # Fuzzy match
                for db_name, dim in db_lookup.items():
                    field_words = set(field_key.split())
                    db_words = set(db_name.split())
                    
                    if len(field_words & db_words) >= 2:
                        dimension_key = dim['key']
                        dimension_name = f"{field_name} (→ {dim['display_name']})"
                        policy_min = float(dim['policy_min']) if dim['policy_min'] else None
                        policy_max = float(dim['policy_max']) if dim['policy_max'] else None
                        policy_flexibility = dim['flexibility']
                        status = 'yellow'
                        break
                
                # Completely new field
                if dimension_key is None:
                    dimension_key = field_name.upper().replace(' ', '_')
                    status = 'red'
            
            extracted_fields.append({
                'serial_number': idx,
                'requirement_reference': requirement_number,
                'dimension_key': dimension_key,
                'dimension_name': dimension_name,
                'dimension_unit': unit,
                'value_type': value_type,
                'extracted_value': value,
                'extracted_text': context,
                'page_number': page_number,
                'policy_min': policy_min,
                'policy_max': policy_max,
                'policy_flexibility': policy_flexibility,
                'clarity_status': status.upper()
            })
        
        print(f"\n✅ Groq extracted {len(extracted_fields)} requirements:")
        for field in extracted_fields:
            status_emoji = "🟢" if field['clarity_status'] == "GREEN" else "🟡" if field['clarity_status'] == "YELLOW" else "🔴"
            print(f"  {field['serial_number']}. {status_emoji} [{field['value_type']}] {field['dimension_name']}: {field['extracted_value']} (Page {field['page_number']})")
        print("=" * 80)
        
        # Store extracted requirement values in decisions_store for later reference
        # This allows newly extracted fields to show actual requirements in PDFs
        if tender_id not in decisions_store:
            decisions_store[tender_id] = {}
        
        for field in extracted_fields:
            dim_key = field['dimension_key'] if field['dimension_key'] else field['dimension_name'].lower().replace(' ', '_')
            
            # Only store requirement_value, don't overwrite existing decisions
            if dim_key not in decisions_store[tender_id]:
                # Initialize new entry for extracted field
                decisions_store[tender_id][dim_key] = {
                    'requirement_value': str(field['extracted_value']),
                    'extracted_from': f"Page {field['page_number']}",
                    'offered_value': None,  # Will be filled when user makes a decision
                    'justification': '',
                    'saved_at': datetime.now().isoformat()
                }
                print(f"  → Stored extracted requirement: {dim_key} = {field['extracted_value']}")
            elif 'requirement_value' not in decisions_store[tender_id][dim_key]:
                # Update existing entry with requirement value if not already set
                decisions_store[tender_id][dim_key]['requirement_value'] = str(field['extracted_value'])
                decisions_store[tender_id][dim_key]['extracted_from'] = f"Page {field['page_number']}"
                print(f"  → Updated requirement: {dim_key} = {field['extracted_value']}")
                if dim_key not in decisions_store[tender_id]:
                    decisions_store[tender_id][dim_key] = {}
                
                # Store the extracted requirement value
                decisions_store[tender_id][dim_key]['requirement_value'] = str(field['extracted_value'])
                decisions_store[tender_id][dim_key]['extracted_from'] = f"Page {field['page_number']}"
                print(f"  → Stored requirement: {dim_key} = {field['extracted_value']}")
        
        return {
            "success": True,
            "pdf_name": pdf_file.filename,
            "pages": len(pages_text),
            "fields_extracted": len(extracted_fields),
            "fields": extracted_fields
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )


@app.post("/api/tender/{tender_id}/export-decisions-pdf")
async def export_decisions_pdf(tender_id: int):
    """
    Generate professional PDF export of all decisions made for this tender
    Reads from in-memory store (POC mode)
    Uses Groq to generate professional tender language
    """
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, HRFlowable
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
        import io
        from datetime import datetime
        import json
        
        # Get tender info
        tender = fetch_one("SELECT * FROM tenders WHERE id = %s", (tender_id,))
        if not tender:
            return JSONResponse(status_code=404, content={"error": "Tender not found"})
        
        # Get decisions from memory store
        decisions = []
        processed_keys = set()
        
        if tender_id in decisions_store:
            # Get tender requirements from DB to match with stored decisions
            requirements = fetch_all("""
                SELECT 
                    ed.display_name,
                    ed.unit,
                    tr.required_value,
                    tr.strictness,
                    ed.key
                FROM tender_requirements tr
                JOIN evaluation_dimension ed ON tr.dimension_id = ed.id
                WHERE tr.tender_id = %s
                ORDER BY ed.display_name
            """, (tender_id,))
            
            for req in requirements:
                dim_key = req['key']
                processed_keys.add(dim_key)
                if dim_key in decisions_store[tender_id]:
                    decision = decisions_store[tender_id][dim_key]
                    decisions.append({
                        'display_name': req['display_name'],
                        'unit': req['unit'],
                        'offered_value': decision['offered_value'],
                        'justification': decision['justification'],
                        'required_value': req['required_value'],
                        'strictness': req['strictness']
                    })
            
            # Add newly extracted fields (not in database requirements)
            for new_dim_key, decision_data in decisions_store[tender_id].items():
                if new_dim_key not in processed_keys:
                    # Only include if a decision has been made (offered_value is set)
                    if decision_data.get('offered_value') is not None:
                        # This is a new field extracted from PDF that's not in the DB
                        req_value = decision_data.get('requirement_value')
                        decisions.append({
                            'display_name': new_dim_key.replace('_', ' ').title(),
                            'unit': 'N/A',
                            'offered_value': decision_data['offered_value'],
                            'justification': decision_data.get('justification', ''),
                            'required_value': req_value,
                            'strictness': 'NEW_FIELD'
                        })
        
        if not decisions:
            return JSONResponse(status_code=400, content={"error": "No decisions found"})
        
        # Generate professional language for each decision using Groq
        print("\n📝 Generating professional tender language with Groq...")
        decision_details = []
        
        for dec in decisions:
            try:
                requirement_text = dec['required_value'] if dec['required_value'] else 'NEW FIELD'
                
                # Format offered value - handle both numeric and boolean
                try:
                    offered_val_str = f"{float(dec['offered_value']):.2f}"
                except (ValueError, TypeError):
                    # Boolean or text value - capitalize if it's a string
                    offered_val_str = str(dec['offered_value'])
                    if offered_val_str.lower() == 'true':
                        offered_val_str = 'Yes'
                    elif offered_val_str.lower() == 'false':
                        offered_val_str = 'No'
                    else:
                        offered_val_str = offered_val_str.title()
                
                groq_prompt = f"""You are a senior tender response specialist and contract writer. Generate a formal, authoritative response paragraph (3-4 sentences) for the following tender specification detail.

SPECIFICATION: {dec['display_name']}
TENDER REQUIREMENT: {requirement_text} {dec['unit'].rstrip()}
OUR COMMITMENT: {offered_val_str} {dec['unit'].rstrip()}
COMMERCIAL JUSTIFICATION: {dec['justification']}

Generate formal contractual language that:
1. Demonstrates comprehensive understanding of the specification and its strategic implications
2. Articulates our technical/commercial positioning relative to the stated requirement
3. Establishes value proposition through capability, compliance, and operational excellence
4. Uses industry-standard terminology appropriate to the domain context

The response must be suitable for inclusion in a formal binding tender submission document. Employ technical precision, professional acumen, and contractual authority. Avoid generic language or overly simplified explanations.

Format as a single cohesive paragraph without headers or bullet points."""

                groq_response = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a expert tender response writer and contract specialist. Your responsibility is to craft formal, authoritative contractual language for tender submissions. Use professional business terminology, technical precision, and demonstrate strategic commercial positioning. Write with the authority and formality appropriate to binding contractual documents."
                        },
                        {
                            "role": "user",
                            "content": groq_prompt
                        }
                    ],
                    temperature=0.2,
                    max_tokens=350
                )
                
                professional_text = groq_response.choices[0].message.content.strip()
                
                decision_details.append({
                    'display_name': dec['display_name'],
                    'unit': dec['unit'],
                    'offered_value': dec['offered_value'],
                    'required_value': dec['required_value'],
                    'strictness': dec['strictness'],
                    'professional_text': professional_text
                })
                
            except Exception as e:
                print(f"⚠️ Error generating language for {dec['display_name']}: {e}")
                decision_details.append({
                    'display_name': dec['display_name'],
                    'unit': dec['unit'],
                    'offered_value': dec['offered_value'],
                    'required_value': dec['required_value'],
                    'strictness': dec['strictness'],
                    'professional_text': dec['justification']
                })
        
        # Create PDF in memory
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.75*inch, bottomMargin=0.75*inch)
        story = []
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            textColor=colors.HexColor('#1a3a52'),
            spaceAfter=6,
            alignment=TA_CENTER,
            bold=True
        )
        
        subtitle_style = ParagraphStyle(
            'SubTitle',
            parent=styles['Normal'],
            fontSize=12,
            textColor=colors.HexColor('#667eea'),
            spaceAfter=12,
            alignment=TA_CENTER
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=13,
            textColor=colors.HexColor('#1a3a52'),
            spaceAfter=10,
            spaceBefore=12,
            bold=True,
            borderPadding=6
        )
        
        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['Normal'],
            fontSize=10,
            alignment=TA_JUSTIFY,
            spaceAfter=10,
            leading=12
        )
        
        # ====== TITLE PAGE ======
        story.append(Spacer(1, 0.3*inch))
        story.append(Paragraph("TENDER RESPONSE PROPOSAL", title_style))
        story.append(Paragraph(tender['name'], subtitle_style))
        story.append(Spacer(1, 0.2*inch))
        story.append(HRFlowable(width=6*inch, thickness=2, lineCap='round', color=colors.HexColor('#667eea')))
        story.append(Spacer(1, 0.3*inch))
        
        # Metadata table
        metadata = [
            ['Tender Name', tender['name']],
            ['Domain', tender['domain']],
            ['Year', str(tender['year'])],
            ['Status', tender['status']],
            ['Generated Date', datetime.now().strftime('%B %d, %Y')],
            ['Generated Time', datetime.now().strftime('%H:%M:%S UTC')]
        ]
        
        meta_table = Table(metadata, colWidths=[2*inch, 4*inch])
        meta_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f4f8')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#1a3a52')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#d0d8e0')),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#f9fafb')])
        ]))
        
        story.append(meta_table)
        story.append(Spacer(1, 0.4*inch))
        
        # Executive Summary
        story.append(Paragraph("EXECUTIVE SUMMARY", heading_style))
        exec_summary = f"""This proposal represents our comprehensive response to the {tender['name']} tender 
requirements. We have carefully evaluated each specification and provided offers that balance commercial considerations 
with our organizational capabilities and policy constraints. Our proposals are based on extensive experience in the 
{tender['domain']} sector and our commitment to delivering exceptional value to our clients."""
        story.append(Paragraph(exec_summary, body_style))
        story.append(Spacer(1, 0.2*inch))
        
        # Commercial Terms Section
        story.append(PageBreak())
        story.append(Paragraph("COMMERCIAL TERMS & CONDITIONS", heading_style))
        story.append(Spacer(1, 0.1*inch))
        
        # Detailed decisions table
        decision_data = [['Field', 'Requirement', 'Our Offer', 'Status']]
        
        for dec_detail in decision_details:
            field_name = dec_detail['display_name']
            
            # Handle boolean or string values for offered field
            offered_raw = dec_detail['offered_value']
            try:
                offered_val = float(offered_raw)
                # Only add unit if it's not "N/A"
                if dec_detail['unit'] and dec_detail['unit'] != 'N/A':
                    offered = f"{offered_val:.2f} {dec_detail['unit']}"
                else:
                    offered = f"{offered_val:.2f}"
                is_numeric = True
            except (ValueError, TypeError):
                # Boolean or text value - format appropriately
                if str(offered_raw).lower() == 'true':
                    offered_display = 'Yes'
                elif str(offered_raw).lower() == 'false':
                    offered_display = 'No'
                else:
                    offered_display = str(offered_raw)
                
                # Only add unit if it's not "N/A"
                if dec_detail['unit'] and dec_detail['unit'] != 'N/A':
                    offered = f"{offered_display} {dec_detail['unit']}"
                else:
                    offered = offered_display
                is_numeric = False
            
            # Handle new fields without requirements
            if dec_detail['required_value'] is None:
                requirement = "SPECIFICATION"
                status_text = "✓ Assessed"
                status_color = colors.HexColor('#8b5cf6')
            elif dec_detail['strictness'] == 'NEW_FIELD':
                # New field with extracted requirement value - display as tender specification
                requirement = str(dec_detail['required_value'])
                status_text = "✓ Assessed"
                status_color = colors.HexColor('#8b5cf6')
            else:
                try:
                    required_val = float(dec_detail['required_value'])
                    requirement = f"{required_val} {dec_detail['unit']}".strip()
                    
                    # Status indicator (only for numeric)
                    if is_numeric:
                        if offered_val >= required_val:
                            status_text = "✓ Exceeds"
                            status_color = colors.HexColor('#10b981')
                        elif offered_val == required_val:
                            status_text = "✓ Meets"
                            status_color = colors.HexColor('#3b82f6')
                        else:
                            status_text = "⚠ Below"
                            status_color = colors.HexColor('#f59e0b')
                    else:
                        # Non-numeric field
                        status_text = "✓ Present"
                        status_color = colors.HexColor('#10b981')
                except (ValueError, TypeError):
                    # Non-numeric requirement
                    requirement = f"{dec_detail['required_value']} {dec_detail['unit']}".strip()
                    status_text = "✓ Present"
                    status_color = colors.HexColor('#10b981')
            
            decision_data.append([field_name, requirement, offered, status_text])
        
        decision_summary_table = Table(decision_data, colWidths=[1.8*inch, 1.6*inch, 1.6*inch, 1.3*inch])
        decision_summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a3a52')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#d0d8e0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9fafb')])
        ]))
        
        story.append(decision_summary_table)
        story.append(Spacer(1, 0.3*inch))
        
        # Detailed justifications
        story.append(Paragraph("DETAILED JUSTIFICATION BY REQUIREMENT", heading_style))
        story.append(Spacer(1, 0.1*inch))
        
        for idx, dec_detail in enumerate(decision_details, 1):
            # Requirement heading
            req_heading = f"{idx}. {dec_detail['display_name'].upper()}"
            story.append(Paragraph(req_heading, ParagraphStyle(
                'ReqHeading',
                parent=styles['Normal'],
                fontSize=11,
                textColor=colors.HexColor('#667eea'),
                spaceAfter=6,
                spaceBefore=8,
                bold=True
            )))
            
            # Requirement details in a small box
            # Format offered value
            try:
                offered_display = f"{float(dec_detail['offered_value']):.2f}"
            except (ValueError, TypeError):
                offered_display = str(dec_detail['offered_value'])
                if offered_display.lower() == 'true':
                    offered_display = 'Yes'
                elif offered_display.lower() == 'false':
                    offered_display = 'No'
            
            # Build unit display - only show if not "N/A"
            unit_display = dec_detail['unit'] if dec_detail['unit'] != 'N/A' else ''
            offered_field = f"{offered_display} {unit_display}".strip()
            
            if dec_detail['required_value'] is None:
                req_box_data = [
                    [f"Tender Specification: As Tendered", 
                     f"Our Commitment: {offered_field}"]
                ]
            elif dec_detail['strictness'] == 'NEW_FIELD' and dec_detail['required_value']:
                # New field with extracted requirement - show as specification
                req_box_data = [
                    [f"Tender Specification: {dec_detail['required_value']}", 
                     f"Our Commitment: {offered_field}"]
                ]
            else:
                req_box_data = [
                    [f"Tender Specification: {dec_detail['required_value']} {dec_detail['unit']} ({dec_detail['strictness']})", 
                     f"Our Commitment: {offered_field}"]
                ]
            req_box = Table(req_box_data, colWidths=[3*inch, 3*inch])
            req_box.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f3f4f6')),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#1a3a52')),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('PADDING', (0, 0), (-1, -1), 8),
                ('BORDERS', (0, 0), (-1, -1), 1, colors.HexColor('#d0d8e0')),
            ]))
            story.append(req_box)
            story.append(Spacer(1, 0.1*inch))
            
            # Professional justification
            story.append(Paragraph(dec_detail['professional_text'], body_style))
            story.append(Spacer(1, 0.15*inch))
        
        # Add page break before declarations
        story.append(PageBreak())
        
        # Terms & Conditions
        story.append(Paragraph("TERMS & CONDITIONS", heading_style))
        terms_text = f"""All offers detailed in this proposal are binding commitments by our organization. We confirm that:
        
        • All specifications and terms stated above represent our final offer for the {tender['name']} tender
        • We have validated all offers against our organizational policies and capacity constraints
        • All pricing and commercial terms are firm for a period of 90 days from the date of submission
        • We commit to meeting or exceeding all mandatory requirements as specified in the tender documentation
        • This proposal is submitted in compliance with all applicable regulations and industry standards"""
        
        story.append(Paragraph(terms_text, body_style))
        story.append(Spacer(1, 0.3*inch))
        
        # Declaration Section
        story.append(Paragraph("DECLARATION AND AUTHORIZATION", heading_style))
        declaration_text = f"""We hereby declare that:

        1. This proposal is authentic and complete in all material respects
        2. All information provided is accurate and has been verified by appropriate personnel
        3. We accept full responsibility for the performance of all terms and conditions outlined herein
        4. We have the authority and organizational capacity to fulfill this proposal in its entirety
        5. There are no conflicts of interest or undisclosed relationships that would compromise our ability to perform
        
        By submission of this proposal, our organization commits to the specifications and commercial terms outlined above 
for the {tender['name']} tender, scheduled for {tender['year']}. This proposal is submitted as our final and binding offer.
        
        Prepared by: DecisionLedger AI System
        Date: {datetime.now().strftime('%B %d, %Y')}
        Time: {datetime.now().strftime('%H:%M:%S')} UTC"""
        
        story.append(Paragraph(declaration_text, body_style))
        story.append(Spacer(1, 0.4*inch))
        
        # Signature Section
        story.append(HRFlowable(width=6*inch, thickness=1, color=colors.HexColor('#d0d8e0')))
        story.append(Spacer(1, 0.2*inch))
        
        sig_data = [
            ['AUTHORIZED SIGNATORY', '', 'TECHNICAL REVIEWER'],
            ['', '', ''],
            ['_' * 25, '', '_' * 25],
            ['Name (Print)', '', 'Name (Print)'],
            ['', '', ''],
            ['_' * 25, '', '_' * 25],
            ['Signature', '', 'Signature'],
            ['', '', ''],
            ['_' * 25, '', '_' * 25],
            ['Date', '', 'Date']
        ]
        
        sig_table = Table(sig_data, colWidths=[2*inch, 0.5*inch, 2*inch])
        sig_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
        ]))
        
        story.append(sig_table)
        story.append(Spacer(1, 0.3*inch))
        
        # Footer
        story.append(HRFlowable(width=6*inch, thickness=1, color=colors.HexColor('#d0d8e0')))
        footer_text = f"DecisionLedger Tender Response System | Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')} | Document Reference: {tender_id}-{datetime.now().strftime('%Y%m%d')}"
        story.append(Paragraph(footer_text, ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#9ca3af'),
            alignment=TA_CENTER,
            spaceAfter=6
        )))
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        
        # Return PDF as download
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=TenderResponse_{tender['name'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)}
        )


@app.get("/api/field/{dimension_key}/options")
async def get_field_options_from_history(
    dimension_key: str,
    extracted_value: str = Query(...),
    tender_domain: str = Query(...)
):
    """
    Get decision options for a field based on historical data
    Now handles new fields that don't exist in database
    Accepts string values for non-numeric extracted data
    """
    try:
        # Try to convert extracted_value to float for numeric fields
        try:
            extracted_val_float = float(extracted_value)
        except (ValueError, TypeError):
            extracted_val_float = None
        
        # First, check if dimension exists in database
        try:
            dimension = fetch_one("""
                SELECT
                    ed.id,
                    ed.key,
                    ed.display_name,
                    ed.unit,
                    vp.min_value as policy_min,
                    vp.max_value as policy_max,
                    vp.flexibility,
                    vp.notes as policy_notes
                FROM evaluation_dimension ed
                LEFT JOIN vendor_policy vp ON ed.id = vp.dimension_id
                    AND (vp.domain = %s OR vp.domain = 'GLOBAL')
                WHERE ed.key = %s
                ORDER BY
                    CASE
                        WHEN vp.domain = %s THEN 0
                        WHEN vp.domain = 'GLOBAL' THEN 1
                        ELSE 2
                    END
                LIMIT 1
            """, (tender_domain, dimension_key, tender_domain))
        except Exception as db_error:
            # Handle invalid enum values gracefully
            print(f"⚠️ Dimension '{dimension_key}' caused error: {db_error}")
            return {
                "dimension_key": dimension_key,
                "display_name": dimension_key.replace('_', ' ').title(),
                "extracted_value": extracted_value,
                "options": [],
                "message": f"This is a new field not yet in our system: {dimension_key}"
            }
        
        # If dimension doesn't exist, return empty options
        if not dimension:
            print(f"⚠️ Dimension '{dimension_key}' not found in database - new field detected")
            return {
                "dimension_key": dimension_key,
                "display_name": dimension_key.replace('_', ' ').title(),
                "extracted_value": extracted_value,
                "options": [],
                "message": "This is a new field not in our database. Please enter a custom value."
            }
        
        # Get historical decisions for this dimension
        history = fetch_all("""
            SELECT 
                pd.offered_value as final_value,
                pd.justification as user_notes,
                p.tender_name,
                p.domain,
                EXTRACT(YEAR FROM p.submitted_at) as year
            FROM proposal_decisions pd
            JOIN proposals p ON pd.proposal_id = p.id
            WHERE pd.dimension_id = %s
                AND pd.offered_value IS NOT NULL
                AND (p.domain = %s OR p.domain = 'GLOBAL')
            ORDER BY p.submitted_at DESC
            LIMIT 10
        """, (dimension['id'], tender_domain))
        
        options = []
        
        # Only process numeric values for options
        if extracted_val_float is not None:
            # Option 1: Use extracted value (if within policy range)
            if dimension['policy_min'] and dimension['policy_max']:
                policy_min_val = float(dimension['policy_min'])
                policy_max_val = float(dimension['policy_max'])
                
                if policy_min_val <= extracted_val_float <= policy_max_val:
                    options.append({
                        "title": f"Use Extracted Value",
                        "value": extracted_val_float,
                        "description": f"{extracted_val_float} {dimension['unit']} (from tender document)",
                        "rationale": "✅ Within policy range - recommended"
                    })
                else:
                    options.append({
                        "title": f"Use Extracted Value (Out of Policy)",
                        "value": extracted_val_float,
                        "description": f"{extracted_val_float} {dimension['unit']} (from tender document)",
                        "rationale": f"⚠️ Outside policy range ({policy_min_val}-{policy_max_val} {dimension['unit']})"
                    })
            else:
                options.append({
                    "title": f"Use Extracted Value",
                    "value": extracted_val_float,
                    "description": f"{extracted_val_float} {dimension['unit']} (from tender document)",
                    "rationale": "From tender requirements"
                })
            
            # Option 2: Use policy minimum (if exists)
            if dimension['policy_min']:
                options.append({
                    "title": f"Policy Minimum",
                    "value": float(dimension['policy_min']),
                    "description": f"{dimension['policy_min']} {dimension['unit']} (organization policy)",
                    "rationale": f"Meets minimum requirements with {dimension['flexibility'] or 'standard'} flexibility"
                })
            
            # Option 3: Historical average
            if history:
                avg_value = sum(float(h['final_value']) for h in history) / len(history)
                options.append({
                    "title": f"Historical Average",
                    "value": round(avg_value, 2),
                    "description": f"{round(avg_value, 2)} {dimension['unit']} (based on {len(history)} past tenders)",
                    "rationale": f"Average from recent {tender_domain} projects"
                })
                
                # Option 4: Most recent decision
                if history[0]['final_value']:
                    options.append({
                        "title": f"Most Recent Decision",
                        "value": float(history[0]['final_value']),
                        "description": f"{history[0]['final_value']} {dimension['unit']} (from {history[0]['tender_name']}, {int(history[0]['year'])})",
                        "rationale": f"Used in latest similar tender"
                    })
        
        return {
            "dimension_key": dimension_key,
            "display_name": dimension['display_name'],
            "unit": dimension['unit'],
            "extracted_value": extracted_value,
            "policy_min": float(dimension['policy_min']) if dimension['policy_min'] else None,
            "policy_max": float(dimension['policy_max']) if dimension['policy_max'] else None,
            "policy_flexibility": dimension['flexibility'],
            "options": options,
            "history_count": len(history)
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


# ============================================================================
# PFMEA CANVAS ROUTES (NEW)
# ============================================================================

@app.get("/pfmea/select", response_class=HTMLResponse)
async def pfmea_select_part(request: Request):
    """Part selection page - list available parts or create new"""
    parts = fetch_all("""
        SELECT 
            pr.id, 
            pr.part_name, 
            pr.part_number, 
            pr.model_year,
            COUNT(pfe.id) as failure_mode_count
        FROM pfmea_records pr
        LEFT JOIN pfmea_failure_mode_entries pfe ON pr.id = pfe.pfmea_record_id
        GROUP BY pr.id
        ORDER BY pr.created_at DESC
    """)
    
    return templates.TemplateResponse("pfmea_select.html", {
        "request": request,
        "parts": parts
    })


@app.get("/pfmea/{part_id}/canvas", response_class=HTMLResponse)
async def pfmea_canvas(request: Request, part_id: int):
    """FMEA Canvas - Main editing interface with auto-evaluation of all entries"""
    part = fetch_one("SELECT * FROM pfmea_records WHERE id = %s", (part_id,))
    
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")
    
    entries = fetch_all("""
        SELECT 
            pfe.*,
            fm.canonical_name as failure_mode_name,
            fm.category,
            ps.step_name as process_step_name
        FROM pfmea_failure_mode_entries pfe
        JOIN failure_mode_taxonomy fm ON pfe.failure_mode_id = fm.id
        LEFT JOIN process_steps ps ON pfe.process_step_id = ps.id
        WHERE pfe.pfmea_record_id = %s
        ORDER BY pfe.process_step_number
    """, (part_id,))
    
    # Auto-evaluate all entries on canvas load
    part_specs = {
        'part_name': part.get('part_name', 'Unknown'),
        'part_number': part.get('part_number', ''),
        'material': part.get('material', 'Unknown'),  # May be None - will default in evaluation
        'environment': part.get('environment', 'Unknown'),  # May be None - will default in evaluation
        'model_year': part.get('model_year', '')
    }
    
    entries_with_evaluations = []
    for entry in entries:
        try:
            # Get historical incidents for this failure mode
            suggestions = get_rpn_suggestions(
                failure_mode_id=entry['failure_mode_id'],
                part_number=part_specs['part_number'],
                limit=10
            )
            
            historical_incidents = []
            if suggestions and 'incidents' in suggestions:
                historical_incidents = suggestions['incidents']
            
            # Perform AI evaluation
            if entry.get('severity_user_input') and len(historical_incidents) > 0:
                evaluation_result = perform_ai_evaluation(
                    failure_mode_name=entry.get('failure_mode_name', 'Unknown'),
                    user_severity=entry.get('severity_user_input'),
                    user_occurrence=entry.get('occurrence_user_input'),
                    user_detection=entry.get('detection_user_input'),
                    historical_incidents=historical_incidents,
                    part_specs=part_specs
                )
                
                entry['evaluation_status'] = evaluation_result['evaluation_status']
                entry['ai_justification'] = evaluation_result['ai_justification']
                entry['severity_recommendation'] = evaluation_result['severity_recommendation']
            else:
                # No user severity or no historical data - default to SAFE
                entry['evaluation_status'] = 'SAFE'
                entry['ai_justification'] = 'No historical data or user severity to compare.'
                entry['severity_recommendation'] = entry.get('severity_user_input', 5)
                
        except Exception as e:
            print(f"⚠️ Evaluation error for entry {entry.get('id')}: {e}")
            # Graceful fallback - don't break page if evaluation fails
            entry['evaluation_status'] = 'SAFE'
            entry['ai_justification'] = 'Evaluation temporarily unavailable.'
            entry['severity_recommendation'] = entry.get('severity_user_input', 5)
        
        entries_with_evaluations.append(entry)
    
    return templates.TemplateResponse("pfmea_canvas.html", {
        "request": request,
        "part": part,
        "entries": entries_with_evaluations,
        "part_id": part_id
    })


@app.post("/api/pfmea/parts")
async def create_pfmea_part(request: Request):
    """Create new PFMEA part and auto-populate with relevant failure modes"""
    from app.rpn_suggestion_engine import find_similar_parts, get_part_failures, find_relevant_failure_modes
    
    data = await request.json()
    
    # Find similar existing parts BEFORE creating this part
    similar_parts = find_similar_parts(data['part_name'], limit=3)
    
    # Create part
    part_id = insert_and_return_id("""
        INSERT INTO pfmea_records 
        (part_number, part_name, model_year, process_responsibility, status, format_number)
        VALUES (%s, %s, %s, %s, 'DRAFT', %s)
    """, (
        data['part_number'],
        data['part_name'],
        data['model_year'],
        "User",
        f"AUTO/{data['part_number']}/{datetime.now().strftime('%Y%m%d')}"
    ))
    
    # Try to clone from most similar part (with best match score)
    cloned_from_part = None
    
    if similar_parts and similar_parts[0]['match_score'] > 0:
        cloned_from_part = similar_parts[0]
        source_part_id = cloned_from_part['id']
        
        # Clone process steps from similar part
        source_steps = fetch_all("""
            SELECT step_number, step_name, function_hierarchy, design_intent, critical_parameters
            FROM process_steps WHERE pfmea_record_id = %s
            ORDER BY step_number
        """, (source_part_id,))
        
        step_id_map = {}
        for step in source_steps:
            step_id = insert_and_return_id("""
                INSERT INTO process_steps (pfmea_record_id, step_number, step_name, function_hierarchy, design_intent, critical_parameters)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (part_id, step['step_number'], step['step_name'], step.get('function_hierarchy'), step.get('design_intent'), Json(step.get('critical_parameters', []))))
            step_id_map[step['step_number']] = step_id
        
        # Clone failure modes from similar part
        source_failures = get_part_failures(source_part_id)
        modes_added = 0
        
        for failure in source_failures:
            step_id = step_id_map.get(failure['process_step_number'])
            if not step_id:
                # Default to first step if mapping fails
                first_step = fetch_one("""
                    SELECT id FROM process_steps WHERE pfmea_record_id = %s
                    ORDER BY step_number LIMIT 1
                """, (part_id,))
                if first_step:
                    step_id = first_step['id']
                else:
                    continue
            
            insert_and_return_id("""
                INSERT INTO pfmea_failure_mode_entries
                (pfmea_record_id, process_step_id, process_step_number, failure_mode_id,
                 potential_effect, severity_user_input, occurrence_user_input, detection_user_input)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                part_id, step_id, failure['process_step_number'], failure['failure_mode_id'],
                f"Potential: {failure['failure_mode_name']}",
                failure['severity'] or 5,
                failure['occurrence'] or 2,
                failure['detection'] or 2
            ))
            modes_added += 1
    else:
        # Fallback: Create default design functions and auto-populate with pgvector search
        default_steps = [
            {"step_number": 10, "step_name": "Design Function 1", "function_hierarchy": f"{data['part_name']} > Component 1", "design_intent": "Primary design function"},
            {"step_number": 20, "step_name": "Design Function 2", "function_hierarchy": f"{data['part_name']} > Component 2", "design_intent": "Secondary design function"},
            {"step_number": 30, "step_name": "Design Function 3", "function_hierarchy": f"{data['part_name']} > Component 3", "design_intent": "Tertiary design function"},
        ]
        
        step_id_map = {}
        for step in default_steps:
            step_id = insert_and_return_id("""
                INSERT INTO process_steps (pfmea_record_id, step_number, step_name, function_hierarchy, design_intent, critical_parameters)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (part_id, step['step_number'], step['step_name'], step['function_hierarchy'], step['design_intent'], Json([])))
            step_id_map[step['step_number']] = step_id
        
        # Find relevant failure modes using pgvector semantic search
        relevant_modes = find_relevant_failure_modes(
            data['part_name'], 
            data['part_number'], 
            limit=5
        )
        
        modes_added = 0
        for idx, mode in enumerate(relevant_modes[:5]):
            step_number = default_steps[idx % len(default_steps)]['step_number']
            step_id = step_id_map[step_number]
            fm_id = mode['id']
            
            insert_and_return_id("""
                INSERT INTO pfmea_failure_mode_entries
                (pfmea_record_id, process_step_id, process_step_number, failure_mode_id,
                 potential_effect, severity_user_input, occurrence_user_input, detection_user_input)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                part_id, step_id, step_number, fm_id,
                f"Potential: {mode['canonical_name']}",
                5, 2, 2
            ))
            modes_added += 1
    
    return JSONResponse({
        "id": part_id,
        "part_name": data['part_name'],
        "part_number": data['part_number'],
        "auto_populated_modes": modes_added,
        "cloned_from": cloned_from_part['part_number'] if cloned_from_part else None,
        "message": f"Part created with {modes_added} auto-populated failure modes" + 
                  (f" (cloned from {cloned_from_part['part_number']})" if cloned_from_part else "")
    })




@app.get("/api/pfmea/parts/{part_id}")
async def get_pfmea_part(part_id: int):
    """Get PFMEA part details"""
    part = fetch_one("SELECT * FROM pfmea_records WHERE id = %s", (part_id,))
    
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")
    
    return dict(part)


@app.get("/api/pfmea/parts/{part_id}/steps")
async def get_process_steps(part_id: int):
    """Get process steps for a PFMEA record"""
    steps = fetch_all("""
        SELECT * FROM process_steps WHERE pfmea_record_id = %s
        ORDER BY step_number
    """, (part_id,))
    
    return [dict(s) for s in steps]


@app.get("/api/pfmea/parts/{part_id}/entries")
async def get_failure_mode_entries(part_id: int):
    """Get all failure mode entries for a PFMEA record with AI evaluations"""
    from app.rpn_suggestion_engine import get_rpn_suggestions, classify_rpn_risk
    
    entries = fetch_all("""
        SELECT 
            pfe.*,
            fm.canonical_name as failure_mode_name,
            ps.step_name as process_step_name
        FROM pfmea_failure_mode_entries pfe
        JOIN failure_mode_taxonomy fm ON pfe.failure_mode_id = fm.id
        LEFT JOIN process_steps ps ON pfe.process_step_id = ps.id
        WHERE pfe.pfmea_record_id = %s
        ORDER BY pfe.process_step_number
    """, (part_id,))
    
    # Enrich with RPN suggestions and AI evaluations
    part = fetch_one("SELECT part_number, part_name, domain, model_year FROM pfmea_records WHERE id = %s", (part_id,))
    
    part_specs = {
        'part_name': part.get('part_name', 'Unknown'),
        'part_number': part.get('part_number', ''),
        'domain': part.get('domain', 'Unknown'),
        'model_year': part.get('model_year', '')
    }
    
    result = []
    for entry in entries:
        entry_dict = dict(entry)
        
        # Get RPN suggestions from historical data
        suggestions = get_rpn_suggestions(
            failure_mode_id=entry['failure_mode_id'],
            part_number=part['part_number']
        )
        
        # Always set suggested values (with defaults if no historical data)
        if suggestions:
            entry_dict['severity_suggested'] = suggestions.get('severity_suggested')
            entry_dict['occurrence_suggested'] = suggestions.get('occurrence_suggested')
            entry_dict['detection_suggested'] = suggestions.get('detection_suggested')
            entry_dict['rpn_suggested'] = suggestions.get('rpn_suggested')
            entry_dict['similar_incidents_count'] = suggestions.get('similar_incident_count', 0)
        else:
            # No historical data: Set reasonable defaults
            entry_dict['severity_suggested'] = 5  # Default moderate severity
            entry_dict['occurrence_suggested'] = 3  # Default moderate occurrence
            entry_dict['detection_suggested'] = 3  # Default moderate detection
            entry_dict['rpn_suggested'] = 5 * 3 * 3  # = 45 (moderate risk)
            entry_dict['similar_incidents_count'] = 0
        
        # Calculate RPN if user has entered values (S * O * D)
        s_user = entry_dict.get('severity_user_input')
        o_user = entry_dict.get('occurrence_user_input')
        d_user = entry_dict.get('detection_user_input')
        
        if s_user and o_user and d_user:
            entry_dict['rpn_user_calculated'] = s_user * o_user * d_user
        
        # Ensure we have an RPN value for display (prefer user-calculated, fall back to suggested)
        rpn = entry_dict.get('rpn_user_calculated') or entry_dict.get('rpn_suggested')
        if rpn:
            entry_dict['rpn_risk_class'] = classify_rpn_risk(rpn)
            entry_dict['rpn_display'] = rpn  # Add explicit display value
        
        # ✅ AI Evaluation (new feature)
        try:
            historical_incidents = []
            if suggestions and 'incidents' in suggestions:
                historical_incidents = suggestions['incidents']
            
            # Perform AI evaluation if we have user severity and historical incidents
            if entry_dict.get('severity_user_input') and len(historical_incidents) > 0:
                evaluation_result = perform_ai_evaluation(
                    failure_mode_name=entry.get('failure_mode_name', 'Unknown'),
                    user_severity=entry_dict.get('severity_user_input'),
                    user_occurrence=entry_dict.get('occurrence_user_input'),
                    user_detection=entry_dict.get('detection_user_input'),
                    historical_incidents=historical_incidents,
                    part_specs=part_specs
                )
                
                entry_dict['evaluation_status'] = evaluation_result['evaluation_status']
                entry_dict['ai_justification'] = evaluation_result['ai_justification']
                entry_dict['severity_recommendation'] = evaluation_result['severity_recommendation']
            else:
                # No user severity or no historical data
                entry_dict['evaluation_status'] = 'SAFE'
                entry_dict['ai_justification'] = 'No historical data or user severity to compare.'
                entry_dict['severity_recommendation'] = entry_dict.get('severity_user_input', 5)
                
        except Exception as e:
            # Graceful fallback
            print(f"⚠️ AI evaluation error for entry {entry.get('id')}: {e}")
            entry_dict['evaluation_status'] = 'SAFE'
            entry_dict['ai_justification'] = 'Evaluation temporarily unavailable.'
            entry_dict['severity_recommendation'] = entry_dict.get('severity_user_input', 5)
        
        result.append(entry_dict)
    
    return result


@app.get("/api/pfmea/entries/{entry_id}/suggestions")
async def get_rpn_suggestions_api(entry_id: int):
    """Get suggested RPN scores from historical data"""
    from app.rpn_suggestion_engine import get_rpn_suggestions
    
    entry = fetch_one("SELECT * FROM pfmea_failure_mode_entries WHERE id = %s", (entry_id,))
    
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    pfmea_record = fetch_one("""
        SELECT part_number FROM pfmea_records WHERE id = %s
    """, (entry['pfmea_record_id'],))
    
    suggestions = get_rpn_suggestions(
        failure_mode_id=entry['failure_mode_id'],
        part_number=pfmea_record['part_number']
    )
    
    return suggestions or {}


@app.get("/api/pfmea/entries/{entry_id}/incidents")
async def get_similar_incidents(entry_id: int):
    """Get similar historical incidents for a failure mode"""
    entry = fetch_one("SELECT * FROM pfmea_failure_mode_entries WHERE id = %s", (entry_id,))
    
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    incidents = fetch_all("""
        SELECT 
            hi.id, 
            hi.part_number, 
            hi.incident_date, 
            hi.location,
            fm.canonical_name as failure_mode_name, 
            hi.severity_actual as severity,
            hi.impact_hours,
            hi.corrective_action as action
        FROM historical_incidents hi
        JOIN failure_mode_taxonomy fm ON hi.failure_mode_id = fm.id
        WHERE hi.failure_mode_id = %s
        ORDER BY hi.incident_date DESC
        LIMIT 10
    """, (entry['failure_mode_id'],))
    
    return [dict(i) for i in incidents]


@app.get("/api/pfmea/parts/{part_id}/similar")
async def get_similar_parts(part_id: int):
    """Get similar existing parts for cloning failure modes"""
    from app.rpn_suggestion_engine import find_similar_parts
    
    part = fetch_one("SELECT part_name FROM pfmea_records WHERE id = %s", (part_id,))
    
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")
    
    # Exclude the current part from results
    similar_parts = find_similar_parts(part['part_name'], limit=5)
    
    # Filter out the current part
    filtered = [p for p in similar_parts if p['id'] != part_id]
    
    return filtered[:3]


@app.post("/api/pfmea/parts/{part_id}/clone-failures")
async def clone_failures_from_part(part_id: int, request: Request):
    """Clone failure modes and process steps from a similar part"""
    from app.rpn_suggestion_engine import get_part_failures
    
    data = await request.json()
    source_part_id = data.get('source_part_id')
    
    if not source_part_id:
        raise HTTPException(status_code=400, detail="source_part_id required")
    
    # Verify target part exists
    target_part = fetch_one("SELECT id FROM pfmea_records WHERE id = %s", (part_id,))
    if not target_part:
        raise HTTPException(status_code=404, detail="Target part not found")
    
    # Verify source part exists
    source_part = fetch_one("SELECT part_number FROM pfmea_records WHERE id = %s", (source_part_id,))
    if not source_part:
        raise HTTPException(status_code=404, detail="Source part not found")
    
    # Get source failures
    source_failures = get_part_failures(source_part_id)
    
    # Get or create process steps on target
    existing_steps = fetch_all("""
        SELECT id, step_number FROM process_steps WHERE pfmea_record_id = %s
        ORDER BY step_number
    """, (part_id,))
    
    step_map = {s['step_number']: s['id'] for s in existing_steps}
    
    # Clone each failure
    cloned_count = 0
    for failure in source_failures:
        step_number = failure['process_step_number']
        step_id = step_map.get(step_number)
        
        # Skip if step doesn't exist on target
        if not step_id:
            continue
        
        # Check if this failure mode already exists on target
        existing = fetch_one("""
            SELECT id FROM pfmea_failure_mode_entries
            WHERE pfmea_record_id = %s AND failure_mode_id = %s
        """, (part_id, failure['failure_mode_id']))
        
        if not existing:
            insert_and_return_id("""
                INSERT INTO pfmea_failure_mode_entries
                (pfmea_record_id, process_step_id, process_step_number, failure_mode_id,
                 potential_effect, severity_user_input, occurrence_user_input, detection_user_input)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                part_id, step_id, step_number, failure['failure_mode_id'],
                f"Potential: {failure['failure_mode_name']}",
                failure['severity'] or 5,
                failure['occurrence'] or 2,
                failure['detection'] or 2
            ))
            cloned_count += 1
    
    return JSONResponse({
        "cloned_count": cloned_count,
        "source_part": source_part['part_number'],
        "target_part_id": part_id,
        "message": f"Cloned {cloned_count} failure modes from {source_part['part_number']}"
    })


@app.post("/api/pfmea/parts/{part_id}/entries")
async def add_failure_mode_entry(part_id: int, request: Request):
    """Add a new failure mode to a PFMEA part"""
    data = await request.json()
    
    failure_mode_id = data.get('failure_mode_id')
    process_step_number = data.get('process_step_number', 10)
    potential_effect = data.get('potential_effect', '')
    
    if not failure_mode_id:
        raise HTTPException(status_code=400, detail="failure_mode_id required")
    
    # Verify part exists
    part = fetch_one("SELECT id FROM pfmea_records WHERE id = %s", (part_id,))
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")
    
    # Verify failure mode exists
    fm = fetch_one("SELECT canonical_name FROM failure_mode_taxonomy WHERE id = %s", (failure_mode_id,))
    if not fm:
        raise HTTPException(status_code=404, detail="Failure mode not found")
    
    # Get process step ID
    step = fetch_one("""
        SELECT id FROM process_steps 
        WHERE pfmea_record_id = %s AND step_number = %s
    """, (part_id, process_step_number))
    
    if not step:
        raise HTTPException(status_code=404, detail="Process step not found")
    
    # Insert new entry
    entry_id = insert_and_return_id("""
        INSERT INTO pfmea_failure_mode_entries
        (pfmea_record_id, process_step_id, process_step_number, failure_mode_id,
         potential_effect, severity_user_input, occurrence_user_input, detection_user_input)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        part_id, step['id'], process_step_number, failure_mode_id,
        potential_effect or f"Potential: {fm['canonical_name']}",
        5, 2, 2  # Default moderate scores
    ))
    
    return JSONResponse({
        "id": entry_id,
        "failure_mode_id": failure_mode_id,
        "message": f"Added {fm['canonical_name']} to {part_id}"
    })


@app.delete("/api/pfmea/entries/{entry_id}")
async def delete_failure_mode_entry(entry_id: int):
    """Delete a failure mode entry from a PFMEA part"""
    entry = fetch_one("SELECT id, pfmea_record_id FROM pfmea_failure_mode_entries WHERE id = %s", (entry_id,))
    
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    
    # Delete related causes
    execute_query("""
        DELETE FROM failure_mode_causes WHERE fmea_entry_id = %s
    """, (entry_id,))
    
    # Delete related controls
    execute_query("""
        DELETE FROM process_controls WHERE fmea_entry_id = %s
    """, (entry_id,))
    
    # Delete the entry
    execute_query("""
        DELETE FROM pfmea_failure_mode_entries WHERE id = %s
    """, (entry_id,))
    
    return JSONResponse({
        "message": f"Entry {entry_id} deleted",
        "affected_part_id": entry['pfmea_record_id']
    })


@app.get("/api/taxonomy/failure-modes")
async def list_failure_modes():
    """List all available failure modes from taxonomy"""
    modes = fetch_all("""
        SELECT id, canonical_name, category, version
        FROM failure_mode_taxonomy
        ORDER BY canonical_name
    """)
    
    return [dict(m) for m in modes] if modes else []


@app.post("/api/v1/evaluate-risk")
async def evaluate_risk(request: Request):
    """
    AI-powered risk evaluation for FMEA failure modes.
    
    Uses Groq to compare user's scores (S, O, D) against historical data
    and generates engineering justification.
    
    Request body:
    {
        "part_id": int,
        "entry_id": int,
        "failure_mode_name": str,
        "failure_mode_id": int,
        "user_severity": int (1-10),
        "user_occurrence": int (1-10),
        "user_detection": int (1-10),
        "part_specs": {
            "part_name": str,
            "domain": str,
            "part_number": str,
            "model_year": str
        }
    }
    """
    try:
        data = await request.json()
        
        part_id = data.get('part_id')
        entry_id = data.get('entry_id')
        failure_mode_name = data.get('failure_mode_name', 'Unknown')
        failure_mode_id = data.get('failure_mode_id')
        user_severity = data.get('user_severity', 5)
        user_occurrence = data.get('user_occurrence', 3)
        user_detection = data.get('user_detection', 3)
        part_specs = data.get('part_specs', {})
        
        # Validate entry belongs to part
        entry = fetch_one(
            "SELECT * FROM pfmea_failure_mode_entries WHERE id = %s AND pfmea_record_id = %s",
            (entry_id, part_id)
        )
        
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found for this part")
        
        # Fetch historical incidents for this failure mode
        suggestions = get_rpn_suggestions(failure_mode_id, part_specs.get('part_number', ''), limit=10)
        
        historical_incidents = []
        if suggestions and 'incidents' in suggestions:
            historical_incidents = suggestions['incidents']
        
        # Call AI evaluation engine with full RPN context
        evaluation_result = perform_ai_evaluation(
            failure_mode_name=failure_mode_name,
            user_severity=user_severity,
            user_occurrence=user_occurrence,
            user_detection=user_detection,
            historical_incidents=historical_incidents,
            part_specs=part_specs
        )
        
        # Cache the evaluation result in session memory
        if part_id not in evaluation_cache:
            evaluation_cache[part_id] = {}
        
        evaluation_cache[part_id][entry_id] = {
            'evaluation_status': evaluation_result['evaluation_status'],
            'ai_justification': evaluation_result['ai_justification'],
            'severity_recommendation': evaluation_result['severity_recommendation'],
            'confidence': evaluation_result['confidence'],
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Return evaluation result
        return JSONResponse({
            'entry_id': entry_id,
            'evaluation_status': evaluation_result['evaluation_status'],
            'ai_justification': evaluation_result['ai_justification'],
            'severity_recommendation': evaluation_result['severity_recommendation'],
            'confidence': round(evaluation_result['confidence'], 2),
            'historical_median_severity': evaluation_result['historical_median_severity'],
            'similar_incidents_count': evaluation_result['similar_incidents_count']
        })
        
    except Exception as e:
        print(f"❌ Evaluation error: {e}")
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")


@app.post("/api/pfmea/canvas/save")
async def save_pfmea_draft(request: Request):
    """Save PFMEA canvas draft"""
    from app.database import execute_query
    
    data = await request.json()
    
    for entry in data['entries']:
        execute_query("""
            UPDATE pfmea_failure_mode_entries
            SET severity_user_input = %s,
                occurrence_user_input = %s,
                detection_user_input = %s,
                rpn_user_calculated = %s,
                canvas_notes = %s,
                updated_at = NOW()
            WHERE id = %s
        """, (
            entry.get('severity_user_input'),
            entry.get('occurrence_user_input'),
            entry.get('detection_user_input'),
            entry.get('rpn_user_calculated'),
            entry.get('canvas_notes'),
            entry['id']
        ))
    
    # Update overall RPN summary
    execute_query("""
        UPDATE pfmea_records
        SET overall_rpn = %s,
            overall_rpn_average = %s,
            updated_at = NOW()
        WHERE id = %s
    """, (
        data['overall_rpn']['max'],
        data['overall_rpn']['average'],
        data['part_id']
    ))
    
    return JSONResponse({"status": "saved"})


@app.get("/api/pfmea/parts/{part_id}/export/excel")
async def export_pfmea_excel(part_id: int):
    """Export PFMEA to Excel"""
    from app.excel_export import export_pfmea_to_excel
    import tempfile
    
    try:
        # Generate Excel file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
            file_path = export_pfmea_to_excel(part_id, tmp.name)
        
        part = fetch_one("SELECT part_name FROM pfmea_records WHERE id = %s", (part_id,))
        filename = f"PFMEA_{part['part_name']}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        
        async def iterfile():
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(4096)
                    if not chunk:
                        break
                    yield chunk
            os.unlink(file_path)  # Clean up temp file
        
        return StreamingResponse(
            iterfile(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# PLM HIERARCHY ENDPOINTS (NEW)
# ============================================================================

@app.get("/hierarchy", response_class=HTMLResponse)
async def view_hierarchy(request: Request):
    """Display hierarchical vehicle → system → assembly → part view"""
    
    # Get all vehicles with hierarchy data
    vehicles_data = fetch_all("""
        SELECT 
            v.id, 
            v.name, 
            v.category, 
            v.model_year,
            COUNT(DISTINCT vs.id) as system_count,
            SUM(COUNT(DISTINCT p.id)) OVER (PARTITION BY v.id) as total_parts
        FROM vehicles v
        LEFT JOIN vehicle_systems vs ON v.id = vs.vehicle_id
        LEFT JOIN assemblies a ON vs.id = a.system_id
        LEFT JOIN parts p ON a.id = p.assembly_id
        GROUP BY v.id, v.name, v.category, v.model_year
        ORDER BY v.model_year DESC, v.name
    """)
    
    # Build hierarchy structure for template
    vehicles = []
    total_systems = 0
    total_assemblies = 0
    total_parts = 0
    
    if vehicles_data:
        for vehicle in vehicles_data:
            # Get systems for this vehicle
            systems = []
            systems_data = fetch_all("""
                SELECT 
                    vs.id,
                    vs.system_name as name
                FROM vehicle_systems vs
                WHERE vs.vehicle_id = %s
                ORDER BY vs.system_name
            """, (vehicle['id'],))
            
            if systems_data:
                for system in systems_data:
                    total_systems += 1
                    # Get assemblies for this system
                    assemblies = []
                    assemblies_data = fetch_all("""
                        SELECT 
                            a.id,
                            a.assembly_name as name,
                            a.part_number
                        FROM assemblies a
                        WHERE a.system_id = %s
                        ORDER BY a.assembly_name
                    """, (system['id'],))
                    
                    if assemblies_data:
                        for assembly in assemblies_data:
                            total_assemblies += 1
                            # Get parts for this assembly
                            parts = []
                            parts_data = fetch_all("""
                                SELECT 
                                    p.id,
                                    p.part_name as name,
                                    p.part_number,
                                    COUNT(pr.id) as revision_count
                                FROM parts p
                                LEFT JOIN part_revisions pr ON p.id = pr.part_id
                                WHERE p.assembly_id = %s
                                GROUP BY p.id, p.part_name, p.part_number
                                ORDER BY p.part_name
                            """, (assembly['id'],))
                            
                            if parts_data:
                                for part in parts_data:
                                    total_parts += 1
                                    parts.append(dict(part))
                            
                            assemblies.append({
                                'id': assembly['id'],
                                'name': assembly['name'],
                                'part_number': assembly['part_number'],
                                'parts': parts
                            })
                    
                    systems.append({
                        'id': system['id'],
                        'name': system['name'],
                        'assemblies': assemblies
                    })
            
            vehicles.append({
                'id': vehicle['id'],
                'name': vehicle['name'],
                'category': vehicle['category'],
                'model_year': vehicle['model_year'],
                'system_count': vehicle['system_count'],
                'total_parts': vehicle['total_parts'],
                'systems': systems
            })
    
    return templates.TemplateResponse("hierarchy_view.html", {
        "request": request,
        "vehicles": vehicles,
        "total_systems": total_systems,
        "total_assemblies": total_assemblies,
        "total_parts": total_parts
    })


@app.get("/api/vehicles")
async def list_vehicles():
    """Get all vehicles with basic hierarchy counts"""
    vehicles = fetch_all("""
        SELECT 
            v.id, 
            v.name, 
            v.category, 
            v.model_year,
            COUNT(DISTINCT vs.id) as system_count,
            SUM(COUNT(DISTINCT p.id)) OVER (PARTITION BY v.id) as total_parts
        FROM vehicles v
        LEFT JOIN vehicle_systems vs ON v.id = vs.vehicle_id
        LEFT JOIN assemblies a ON vs.id = a.system_id
        LEFT JOIN parts p ON a.id = p.assembly_id
        GROUP BY v.id, v.name, v.category, v.model_year
        ORDER BY v.model_year DESC, v.name
    """)
    
    return [dict(v) for v in vehicles] if vehicles else []


@app.get("/api/vehicles/{vehicle_id}/hierarchy")
async def get_vehicle_hierarchy(vehicle_id: str):
    """Get complete hierarchical view of vehicle (Vehicle → System → Assembly → Part → Revision)"""
    try:
        import json
        # Use the helper function to get JSON hierarchy
        result = fetch_one("""
            SELECT get_vehicle_hierarchy(%s::uuid)
        """, (vehicle_id,))
        
        if not result:
            raise HTTPException(status_code=404, detail="Vehicle not found")
        
        # Extract the JSONB column (it's named 'get_vehicle_hierarchy' due to the function name)
        hierarchy_json = result.get('get_vehicle_hierarchy')
        if hierarchy_json is None:
            raise HTTPException(status_code=404, detail="Vehicle not found")
        
        # If it's already a dict (JSONB parsed), return it; otherwise parse it
        if isinstance(hierarchy_json, dict):
            return hierarchy_json
        else:
            return json.loads(hierarchy_json)
        
    except Exception as e:
        print(f"Error getting hierarchy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    print("🔧 POC MODE - In-Memory Storage")
    print("📝 Decisions stored in memory (not persisted)")
    print("📋 Seeded historical data loaded from database")
    print()
    print("Available routes:")
    print("  → http://localhost:8000/")
    print("  → http://localhost:8000/history")
    print("  → http://localhost:8000/tender/1")
    print("  → http://localhost:8000/tender/2")
    print()