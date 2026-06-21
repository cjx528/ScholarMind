from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from packages.ai.compass_service import CompassService

router = APIRouter(prefix="/recommendation", tags=["recommendation"])


Backend = Literal["auto", "llm", "codex"]


class ProfileUpdate(BaseModel):
    interests: str | None = None
    researchDirections: str | None = None
    readingGoal: str | None = None
    quickProfile: dict[str, Any] | None = None
    questions: list[dict[str, Any]] | None = None
    notes: list[str] | None = None
    confidence: float | None = None


class ProfileBuildRequest(BaseModel):
    source: str
    answers: list[dict[str, Any]] = Field(default_factory=list)
    currentProfile: dict[str, Any] | None = None
    quickProfile: dict[str, Any] | None = None
    backend: Backend | None = None


class AnalyzeRequest(BaseModel):
    input: str = ""
    paper_id: str | None = None
    mode: str = "understand"
    backend: Backend | None = None


class FeedbackRequest(BaseModel):
    recommendation_id: str | None = None
    paper_id: str | None = None
    rating: int = Field(ge=1, le=5)
    notes: str | None = None
    factors: dict[str, Any] | None = None
    base_score: float | None = None


@router.get("/profile")
def get_profile() -> dict:
    service = CompassService()
    return {"profile": service.get_profile(), "model": service.get_model()}


@router.put("/profile")
def update_profile(req: ProfileUpdate) -> dict:
    service = CompassService()
    profile = service.upsert_profile(req.model_dump(exclude_none=True))
    return {"profile": profile, "model": service.get_model()}


@router.post("/profile/build")
def build_profile(req: ProfileBuildRequest) -> dict:
    try:
        return CompassService().build_profile(
            source=req.source,
            answers=req.answers,
            current_profile=req.currentProfile,
            quick_profile=req.quickProfile,
            backend=req.backend,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    try:
        return CompassService().analyze(
            input_text=req.input,
            paper_id=req.paper_id,
            backend=req.backend,
            mode=req.mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/papers/{paper_id}/analysis")
def paper_analysis(paper_id: str) -> dict:
    return CompassService().latest_paper_analysis(paper_id=paper_id)


@router.get("/queue")
def queue(top_k: int = Query(default=20, ge=1, le=100)) -> dict:
    return CompassService().queue(top_k=top_k)


@router.post("/feedback")
def feedback(req: FeedbackRequest) -> dict:
    try:
        return CompassService().feedback(
            recommendation_id=req.recommendation_id,
            paper_id=req.paper_id,
            rating=req.rating,
            notes=req.notes,
            factors=req.factors,
            base_score=req.base_score,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/model/reset")
def reset_model() -> dict:
    return {"model": CompassService().reset_model()}
