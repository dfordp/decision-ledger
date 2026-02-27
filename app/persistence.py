"""
Handle persistence of user decisions back to the database.
Creates proposal and proposal_decisions when user accepts/overrides recommendations.
"""

from decimal import Decimal
from datetime import datetime
from typing import Optional

from app.database import (
    insert_and_return_id, fetch_one, get_vendor_id, get_dimension_id, execute_query
)
from app.embeddings import (
    generate_proposal_embedding,
    generate_decision_embedding
)

def save_decision(
    tender_id: int,
    dimension_key: str,
    final_value: Decimal,
    user_notes: str
) -> int:
    """
    Save user's decision to database.
    
    Creates:
    1. Proposal record (if first decision for this tender)
    2. Proposal decision record
    3. Embeddings for future similarity search
    
    Returns:
        proposal_decision_id
    """
    
    vendor_id = get_vendor_id()
    dimension_id = get_dimension_id(dimension_key)
    
    # Get tender info
    tender = fetch_one(
        "SELECT name, domain FROM tenders WHERE id = %s",
        (tender_id,)
    )
    
    if not tender:
        raise ValueError(f"Tender {tender_id} not found")
    
    tender_name = tender['name']
    domain = tender['domain']
    
    # Check if proposal already exists for this tender
    existing_proposal = fetch_one(
        """
        SELECT id FROM proposals 
        WHERE vendor_id = %s 
        AND tender_name = %s
        """,
        (vendor_id, tender_name)
    )
    
    proposal_id = existing_proposal['id'] if existing_proposal else None
    
    # Create proposal if doesn't exist
    if not proposal_id:
        proposal_embedding = generate_proposal_embedding(
            tender_name=tender_name,
            domain=domain,
            outcome="WON",  # Placeholder - actual outcome determined later
            outcome_reason=f"Decision in progress for tender {tender_id}"
        )
        
        embedding_str = "[" + ",".join(map(str, proposal_embedding)) + "]"
        
        proposal_id = insert_and_return_id(
            """
            INSERT INTO proposals 
            (vendor_id, tender_name, domain, outcome, outcome_reason, submitted_at, embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
            """,
            (
                vendor_id,
                tender_name,
                domain,
                'WON',  # Default - can be updated later
                'Evaluation in progress',
                datetime.now(),
                embedding_str
            )
        )
    
    # Get dimension details
    dimension = fetch_one(
        "SELECT display_name FROM evaluation_dimension WHERE id = %s",
        (dimension_id,)
    )
    
    dimension_name = dimension['display_name']
    
    # Create justification text
    justification = f"Decision made for {tender_name}. {user_notes}" if user_notes else f"Decision made for {tender_name}."
    
    source_excerpt = f"User decision: Offered {final_value} for {dimension_name}. {user_notes}"
    
    # Generate decision embedding
    decision_embedding = generate_decision_embedding(
        dimension_name=dimension_name,
        offered_value=float(final_value),
        justification=justification,
        domain=domain,
        outcome='WON',  # Placeholder
        source_excerpt=source_excerpt
    )
    
    decision_embedding_str = "[" + ",".join(map(str, decision_embedding)) + "]"
    
    # Check if decision already exists (update vs insert)
    existing_decision = fetch_one(
        """
        SELECT id FROM proposal_decisions 
        WHERE proposal_id = %s AND dimension_id = %s
        """,
        (proposal_id, dimension_id)
    )
    
    existing_decision_id = existing_decision['id'] if existing_decision else None
    
    if existing_decision_id:
        # Update existing decision
        execute_query(
            """
            UPDATE proposal_decisions
            SET offered_value = %s,
                justification = %s,
                source_excerpt = %s,
                embedding = %s::vector
            WHERE id = %s
            """,
            (
                final_value,
                justification,
                source_excerpt,
                decision_embedding_str,
                existing_decision_id
            )
        )
        return existing_decision_id
    else:
        # Insert new decision
        decision_id = insert_and_return_id(
            """
            INSERT INTO proposal_decisions
            (proposal_id, dimension_id, offered_value, justification, source_excerpt, embedding)
            VALUES (%s, %s, %s, %s, %s, %s::vector)
            """,
            (
                proposal_id,
                dimension_id,
                final_value,
                justification,
                source_excerpt,
                decision_embedding_str
            )
        )
        return decision_id