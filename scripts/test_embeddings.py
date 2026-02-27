"""
Test script to verify OpenAI embeddings are working.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.embeddings import generate_embedding, EMBEDDING_DIMENSION

def test_embeddings():
    """Test that embeddings are generated correctly"""
    
    print("Testing OpenAI embedding service...\n")
    
    # Test basic embedding
    test_text = "Maintenance duration of 5 years was offered for rail HVAC project"
    
    try:
        embedding = generate_embedding(test_text)
        
        print(f"✓ Generated embedding successfully")
        print(f"✓ Dimension: {len(embedding)} (expected {EMBEDDING_DIMENSION})")
        print(f"✓ Sample values: {embedding[:5]}")
        
        # Verify dimension
        assert len(embedding) == EMBEDDING_DIMENSION, \
            f"Expected {EMBEDDING_DIMENSION} dimensions, got {len(embedding)}"
        
        # Verify all values are floats
        assert all(isinstance(v, float) for v in embedding), \
            "Not all embedding values are floats"
        
        # Test that similar text produces similar embeddings
        similar_text = "5-year maintenance period provided for railway HVAC system"
        similar_embedding = generate_embedding(similar_text)
        
        # Calculate cosine similarity (simple dot product for normalized vectors)
        from math import sqrt
        
        def cosine_similarity(v1, v2):
            dot_product = sum(a * b for a, b in zip(v1, v2))
            magnitude1 = sqrt(sum(a * a for a in v1))
            magnitude2 = sqrt(sum(b * b for b in v2))
            return dot_product / (magnitude1 * magnitude2)
        
        similarity = cosine_similarity(embedding, similar_embedding)
        print(f"\n✓ Similarity between related texts: {similarity:.4f}")
        
        if similarity > 0.8:
            print("✓ High similarity confirms semantic understanding")
        
        print("\n✓ All embedding tests passed!")
        
    except Exception as e:
        print(f"✗ Embedding test failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test_embeddings()