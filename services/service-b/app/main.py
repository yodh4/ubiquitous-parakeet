from fastapi import FastAPI

from app.config import settings
from app.schemas import HealthResponse

app = FastAPI(
    title="Service B (Worker / Consumer)",
    description="Receives tasks, executes simulated work or simulated failures.",
    version="0.1.0",
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(service=settings.service_name)
