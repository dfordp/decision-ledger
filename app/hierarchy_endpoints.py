# ============================================================================
# PLM HIERARCHY ENDPOINTS (NEW)
# ============================================================================

@app.get("/api/vehicles")
async def list_vehicles():
    """Get all vehicles with basic hierarchy"""
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
        # Use the helper function to get JSON hierarchy
        result = fetch_one("""
            SELECT get_vehicle_hierarchy(%s::uuid)
        """, (vehicle_id,))
        
        if not result or result[0] is None:
            raise HTTPException(status_code=404, detail="Vehicle not found")
        
        import json
        return json.loads(result[0])
        
    except Exception as e:
        print(f"Error getting hierarchy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/vehicles")
async def create_vehicle(request: Request):
    """Create new vehicle"""
    data = await request.json()
    
    vehicle_id = str(uuid4()) if 'uuid' not in dir() else uuid4()
    
    # Actually import uuid if not already done
    from uuid import uuid4 as make_uuid
    vehicle_id = str(make_uuid())
    
    execute_query("""
        INSERT INTO vehicles (id, name, category, model_year, description)
        VALUES (%s, %s, %s, %s, %s)
    """, (
        vehicle_id,
        data['name'],
        data['category'],
        data.get('model_year'),
        data.get('description', '')
    ))
    
    return JSONResponse({
        "id": vehicle_id,
        "name": data['name'],
        "message": "Vehicle created successfully"
    })


@app.post("/api/parts/{part_id}/revision")
async def create_part_revision(part_id: str, request: Request):
    """Create new revision of a part"""
    data = await request.json()
    
    try:
        from uuid import uuid4 as make_uuid
        revision_id = str(make_uuid())
        
        # Get next revision number
        result = fetch_one("""
            SELECT MAX(revision_number) as num FROM part_revisions WHERE part_id = %s::uuid
        """, (part_id,))
        
        next_rev_num = (result['num'] or 0) + 1 if result else 1
        
        # Get current part specs as previous version
        current_part = fetch_one("""
            SELECT 
                p.part_name, p.part_number, p.supplier, p.material, p.cost, p.mass,
                pr.new_specs_json as prev_specs
            FROM parts p
            LEFT JOIN part_revisions pr ON p.id = pr.part_id AND pr.revision_number = (
                SELECT MAX(revision_number) FROM part_revisions WHERE part_id = p.id
            )
            WHERE p.id = %s::uuid
        """, (part_id,))
        
        if not current_part:
            raise HTTPException(status_code=404, detail="Part not found")
        
        import json
        
        # Insert new revision
        execute_query("""
            INSERT INTO part_revisions 
            (id, part_id, revision_number, change_type, previous_specs_json, new_specs_json, 
             change_description, changed_by, approval_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'draft')
        """, (
            revision_id,
            part_id,
            next_rev_num,
            data.get('change_type', 'design_change'),
            current_part.get('prev_specs') or json.dumps({}),
            json.dumps(data['new_specs_json']),
            data.get('change_description', ''),
            data.get('changed_by', 'system')
        ))
        
        return JSONResponse({
            "id": revision_id,
            "part_id": part_id,
            "revision_number": next_rev_num,
            "message": f"Revision {next_rev_num} created"
        })
        
    except Exception as e:
        print(f"Error creating revision: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/revisions/{revision_id}/analyze")
async def analyze_revision(revision_id: str):
    """Trigger AI analysis of part revision changes (Groq)"""
    try:
        # Get revision details
        revision = fetch_one("""
            SELECT 
                pr.id, pr.part_id, pr.previous_specs_json, pr.new_specs_json,
                p.part_name, a.assembly_name,
                pr.revision_number, pr.change_type, pr.change_description
            FROM part_revisions pr
            JOIN parts p ON pr.part_id = p.id
            JOIN assemblies a ON p.assembly_id = a.id
            WHERE pr.id = %s::uuid
        """, (revision_id,))
        
        if not revision:
            raise HTTPException(status_code=404, detail="Revision not found")
        
        import json
        old_specs = json.loads(revision['previous_specs_json'] or '{}')
        new_specs = json.loads(revision['new_specs_json'])
        
        # Build Groq prompt for change analysis
        prompt = f"""You are a senior failure analysis engineer. A part specification has changed:

PART: {revision['assembly_name']} - {revision['part_name']}
REVISION: {revision['revision_number']}
CHANGE TYPE: {revision['change_type']}

OLD SPECIFICATION:
{json.dumps(old_specs, indent=2)}

NEW SPECIFICATION:
{json.dumps(new_specs, indent=2)}

CHANGE DESCRIPTION: {revision['change_description']}

Analyze the impact of this change on product reliability and risk. Provide:
1. How will existing failure mode RPN values change?
2. What new failure modes might this introduce?
3. What design mitigations are recommended?

Return JSON: {{
    "updated_failures": [
        {{"name": "...", "old_rpn": 56, "new_rpn_estimate": 48, "reasoning": "..."}}
    ],
    "new_failure_modes": [
        {{"name": "...", "estimated_rpn": 21, "probability": "HIGH"}}
    ],
    "mitigations": ["...", "..."],
    "confidence_score": 85
}}"""
        
        # Call Groq
        from groq import Clientas groq_client_temp
        groq_resp = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500
        )
        
        response_text = groq_resp.choices[0].message.content.strip()
        
        # Extract JSON from response
        json_start = response_text.find('{')
        json_end = response_text.rfind('}')
        
        if json_start != -1 and json_end != -1:
            json_str = response_text[json_start:json_end+1]
            analysis_json = json.loads(json_str)
        else:
            analysis_json = {"error": "Could not parse Groq response", "raw": response_text}
        
        # Store analysis result
        from uuid import uuid4 as make_uuid
        analysis_id = str(make_uuid())
        
        execute_query("""
            INSERT INTO revision_impact_analysis 
            (id, part_revision_id, analysis_json, confidence_score)
            VALUES (%s, %s, %s, %s)
        """, (
            analysis_id,
            revision_id,
            json.dumps(analysis_json),
            analysis_json.get('confidence_score', 0)
        ))
        
        return JSONResponse({
            "id": analysis_id,
            "revision_id": revision_id,
            "analysis": analysis_json,
            "status": "analysis_complete"
        })
        
    except Exception as e:
        print(f"Error analyzing revision: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/compare/revisions/{revision1_id}/{revision2_id}")
async def compare_revisions(revision1_id: str, revision2_id: str):
    """Compare two revisions of the same part"""
    try:
        rev1 = fetch_one("""
            SELECT id, part_id, revision_number, new_specs_json, change_description
            FROM part_revisions WHERE id = %s::uuid
        """, (revision1_id,))
        
        rev2 = fetch_one("""
            SELECT id, part_id, revision_number, new_specs_json, change_description
            FROM part_revisions WHERE id = %s::uuid
        """, (revision2_id,))
        
        if not rev1 or not rev2:
            raise HTTPException(status_code=404, detail="One or both revisions not found")
        
        if rev1['part_id'] != rev2['part_id']:
            raise HTTPException(status_code=400, detail="Revisions must be from the same part")
        
        import json
        from deepdiff import DeepDiff
        
        specs1 = json.loads(rev1['new_specs_json'] or '{}')
        specs2 = json.loads(rev2['new_specs_json'] or '{}')
        
        # Compute diff
        diff = DeepDiff(specs1, specs2, ignore_order=True)
        
        # Get impact analysis if exists
        analysis1 = fetch_one("""
            SELECT analysis_json FROM revision_impact_analysis 
            WHERE part_revision_id = %s::uuid
        """, (revision1_id,))
        
        analysis2 = fetch_one("""
            SELECT analysis_json FROM revision_impact_analysis 
            WHERE part_revision_id = %s::uuid
        """, (revision2_id,))
        
        return JSONResponse({
            "rev1_id": revision1_id,
            "rev1_number": rev1['revision_number'],
            "rev2_id": revision2_id,
            "rev2_number": rev2['revision_number'],
            "changes": dict(diff) if diff else {},
            "rev1_analysis": json.loads(analysis1['analysis_json']) if analysis1 else None,
            "rev2_analysis": json.loads(analysis2['analysis_json']) if analysis2 else None
        })
        
    except Exception as e:
        print(f"Error comparing revisions: {e}")
        raise HTTPException(status_code=500, detail=str(e))
