"""
FastAPI application for DecisionLedger POC.
Server-rendered HTML interface for tender evaluation.
"""

from datetime import datetime
import os

from fastapi import FastAPI, Request, Form, File, UploadFile, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from decimal import Decimal
from typing import Optional
from fastapi.responses import StreamingResponse

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
    
    # First, ensure a proposal exists for this tender
    proposal = fetch_one("""
        SELECT id FROM proposals 
        WHERE tender_name = %s
        ORDER BY submitted_at DESC
        LIMIT 1
    """, (tender['name'],))
    
    if not proposal:
        # Create a new proposal if none exists
        from app.persistence import create_or_get_proposal
        proposal_id = create_or_get_proposal(
            tender_name=tender['name'],
            domain=tender['domain'],
            vendor_id=1  # Default vendor
        )
        proposal = {'id': proposal_id}
    
    # Get all decisions for this proposal
    decisions = fetch_all("""
        SELECT 
            ed.display_name,
            ed.unit,
            pd.offered_value,
            pd.justification,
            tr.required_value,
            tr.strictness
        FROM proposal_decisions pd
        JOIN evaluation_dimension ed ON pd.dimension_id = ed.id
        JOIN tender_requirements tr ON tr.dimension_id = ed.id
        WHERE pd.proposal_id = %s
        AND tr.tender_id = %s
        ORDER BY ed.display_name
    """, (proposal['id'], tender_id))
    
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
Our Offer:   {decision['offered_value']} {decision['unit']}
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
    Upload PDF → Extract text → Use Groq to intelligently parse requirements
    Returns all extracted fields with color-coded status, page numbers, and positions
    """
    try:
        # Read PDF
        pdf_bytes = await pdf_file.read()
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
        
        # Extract text WITH page numbers
        pages_text = []
        for page_num, page in enumerate(pdf_reader.pages, start=1):
            page_text = page.extract_text()
            pages_text.append({
                'page_number': page_num,
                'text': page_text
            })
        
        full_text = "\n\n".join([f"[PAGE {p['page_number']}]\n{p['text']}" for p in pages_text])
        
        print(f"\n=== PDF EXTRACTION WITH GROQ ===")
        print(f"Pages: {len(pdf_reader.pages)}")
        print(f"Characters extracted: {len(full_text)}")
        
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
            max_tokens=3000
        )
        
        groq_output = groq_response.choices[0].message.content.strip()
        
        # Clean JSON response
        if groq_output.startswith("```json"):
            groq_output = groq_output[7:]
        if groq_output.startswith("```"):
            groq_output = groq_output[3:]
        if groq_output.endswith("```"):
            groq_output = groq_output[:-3]
        groq_output = groq_output.strip()
        
        print(f"\n📥 Groq response:\n{groq_output[:800]}...")
        
        # Parse Groq's structured output
        import json
        groq_fields = json.loads(groq_output)
        
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
                if value_type == "NUMERIC" and policy_min and policy_max:
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
        
        return {
            "success": True,
            "pdf_name": pdf_file.filename,
            "pages": len(pdf_reader.pages),
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
    Generate PDF export of all decisions made for this tender
    """
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        import io
        from datetime import datetime
        
        # Get tender info - FIX: Use %s instead of ?
        tender = fetch_one("SELECT * FROM tender WHERE id = %s", (tender_id,))
        if not tender:
            return JSONResponse(status_code=404, content={"error": "Tender not found"})
        
        # Get all decisions for this tender - FIX: Use %s instead of ?
        decisions = fetch_all("""
            SELECT 
                d.*,
                ed.display_name,
                ed.unit,
                vp.min_value as policy_min,
                vp.max_value as policy_max
            FROM decision d
            JOIN evaluation_dimension ed ON d.dimension_id = ed.id
            LEFT JOIN vendor_policy vp ON ed.id = vp.dimension_id
            WHERE d.tender_id = %s
            ORDER BY ed.display_name
        """, (tender_id,))
        
        # Create PDF in memory
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
        story = []
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#667eea'),
            spaceAfter=12,
            alignment=TA_CENTER
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=16,
            textColor=colors.HexColor('#333333'),
            spaceAfter=10,
            spaceBefore=20
        )
        
        # Title
        story.append(Paragraph(f"Decision Ledger Report", title_style))
        story.append(Paragraph(f"{tender['name']}", styles['Heading2']))
        story.append(Spacer(1, 0.3*inch))
        
        # Metadata table
        metadata = [
            ['Tender Information', ''],
            ['Domain', tender['domain']],
            ['Status', tender['status']],
            ['Generated', datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
            ['Total Decisions', str(len(decisions))]
        ]
        
        meta_table = Table(metadata, colWidths=[2.5*inch, 4*inch])
        meta_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey)
        ]))
        
        story.append(meta_table)
        story.append(Spacer(1, 0.4*inch))
        
        # Decisions heading
        story.append(Paragraph("Decisions Summary", heading_style))
        
        # Decisions table
        decision_data = [['Field', 'Policy Range', 'Final Decision', 'Status']]
        
        for dec in decisions:
            field_name = dec['display_name']
            policy_range = f"{dec['policy_min']}-{dec['policy_max']} {dec['unit']}" if dec['policy_min'] and dec['policy_max'] else "No policy"
            final_value = f"{dec['final_value']} {dec['unit']}" if dec['final_value'] else "Not decided"
            
            # Determine status
            if dec['final_value']:
                if dec['policy_min'] and dec['policy_max']:
                    val = float(dec['final_value'])
                    if dec['policy_min'] <= val <= dec['policy_max']:
                        status_text = "✓ In Policy"
                    else:
                        status_text = "⚠ Out of Policy"
                else:
                    status_text = "✓ Decided"
            else:
                status_text = "⏳ Pending"
            
            decision_data.append([field_name, policy_range, final_value, status_text])
        
        decisions_table = Table(decision_data, colWidths=[2*inch, 1.8*inch, 1.5*inch, 1.2*inch])
        decisions_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
        ]))
        
        story.append(decisions_table)
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        
        # Return PDF as download
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=DecisionLedger_{tender['name'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
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
    extracted_value: float = Query(...),
    tender_domain: str = Query(...)
):
    """
    Get decision options for a field based on historical data
    Now handles new fields that don't exist in database
    """
    try:
        # First, check if dimension exists in database
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
        
        # If dimension doesn't exist, return empty options
        if not dimension:
            print(f"⚠️  Dimension '{dimension_key}' not found in database - new field detected")
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
        
        # Option 1: Use extracted value (if within policy range)
        if dimension['policy_min'] and dimension['policy_max']:
            policy_min_val = float(dimension['policy_min'])
            policy_max_val = float(dimension['policy_max'])
            
            if policy_min_val <= extracted_value <= policy_max_val:
                options.append({
                    "title": f"Use Extracted Value",
                    "value": extracted_value,
                    "description": f"{extracted_value} {dimension['unit']} (from tender document)",
                    "rationale": "✅ Within policy range - recommended"
                })
            else:
                options.append({
                    "title": f"Use Extracted Value (Out of Policy)",
                    "value": extracted_value,
                    "description": f"{extracted_value} {dimension['unit']} (from tender document)",
                    "rationale": f"⚠️ Outside policy range ({policy_min_val}-{policy_max_val} {dimension['unit']})"
                })
        else:
            options.append({
                "title": f"Use Extracted Value",
                "value": extracted_value,
                "description": f"{extracted_value} {dimension['unit']} (from tender document)",
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