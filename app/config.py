import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://decisionledger:devpass123@postgres:5432/decisionledger"
)

# Groq
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Environment
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Validation
if ENVIRONMENT == "production" and not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY must be set in production")

print(f"✓ Config loaded: ENV={ENVIRONMENT}, DB={DATABASE_URL[:40]}...")