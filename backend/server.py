from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from engine.state_builder import state_builder, SCENARIOS
# simulation.py (old fake-data engine) is intentionally left in the repo,
# unimported here, as a reference/fallback -- not deleted.


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')


@asynccontextmanager
async def lifespan(app: FastAPI):
    await state_builder.start()
    yield
    await state_builder.stop()


app = FastAPI(lifespan=lifespan)
api_router = APIRouter(prefix="/api")


class ScenarioIn(BaseModel):
    scenario: str


@api_router.get("/")
async def root():
    return {"message": "Tkil Boiler Digital Twin API"}


@api_router.get("/state")
async def get_state():
    snap = state_builder.snapshot()
    if not snap:
        raise HTTPException(status_code=503, detail="State builder warming up")
    return snap


@api_router.get("/efficiency")
async def get_efficiency():
    snap = state_builder.efficiency_snapshot()
    if not snap:
        raise HTTPException(status_code=503, detail="State builder warming up")
    return snap


@api_router.get("/scenarios")
async def get_scenarios():
    return {"scenarios": SCENARIOS, "active": state_builder.snapshot().get("scenario", "Normal Operation")}


@api_router.post("/scenario")
async def set_scenario(payload: ScenarioIn):
    if payload.scenario not in SCENARIOS:
        raise HTTPException(status_code=400, detail=f"Unknown scenario. Allowed: {SCENARIOS}")
    await state_builder.set_scenario(payload.scenario)
    return {"ok": True, "scenario": payload.scenario}


@api_router.post("/alerts/{alert_id}/ack")
async def ack_alert(alert_id: str):
    ok = await state_builder.acknowledge(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"ok": True}


@api_router.post("/alerts/ack-all")
async def ack_all():
    n = await state_builder.acknowledge_all()
    return {"ok": True, "acknowledged": n}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
