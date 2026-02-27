"""
DecisionLedger FastAPI application.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.database import engine
from app import models
from app.routes import vendors, proposals, tenders, home
import logging
import os

# Create tables
models.Base.metadata.create_all(bind=engine)

# Initialize FastAPI app
app = FastAPI(
    title="DecisionLedger",
    description="Strategic vendor decision ledger with tender matching",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files (CSS, JS, images)
static_dir = os.path.join(os.path.dirname(__file__), 'static')
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Health check
@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

# Include routers
app.include_router(home.router)  # Home page with Jinja2 templates
app.include_router(vendors.router)
app.include_router(proposals.router)
app.include_router(tenders.router)

logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 DecisionLedger API started")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 DecisionLedger API shutdown")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)