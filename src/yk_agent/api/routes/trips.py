"""攻略接口：列表 / 详情 / 反馈（docs/08-api-spec.md）。

反馈进 TripRecord.status 与 feedback 列表（L3 行为反馈）；
画像 weight 回写属 V2（docs/04 §反馈回写），MVP 只落档。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from yk_agent.api.deps import get_state
from yk_agent.api.state import AppState

router = APIRouter(prefix="/trips")


class FeedbackRequest(BaseModel):
    action: Literal["accept", "modify", "reject"]
    detail: str = ""


def _summary(record) -> dict:
    return {
        "trip_id": record.trip_id,
        "status": record.status,
        "answer_head": record.final_answer[:100],
        "created_snapshot_prefs": len(record.profile_snapshot.get("preferences", [])),
    }


@router.get("")
async def list_trips(
    state: AppState = Depends(get_state), x_user_id: str = Header(...)
) -> list[dict]:
    return [_summary(r) for r in state.trips.values() if r.user_id == x_user_id]


@router.get("/{trip_id}")
async def get_trip(
    trip_id: str, state: AppState = Depends(get_state), x_user_id: str = Header(...)
):
    record = state.trips.get(trip_id)
    if record is None or record.user_id != x_user_id:
        raise HTTPException(status_code=404, detail="trip not found")
    return {
        "trip_id": record.trip_id,
        "session_id": record.session_id,
        "status": record.status,
        "final_answer": record.final_answer,
        "findings": record.findings,
        "profile_snapshot": record.profile_snapshot,
        "feedback": record.feedback,
    }


@router.post("/{trip_id}/feedback")
async def post_feedback(
    trip_id: str,
    req: FeedbackRequest,
    state: AppState = Depends(get_state),
    x_user_id: str = Header(...),
) -> dict:
    record = state.trips.get(trip_id)
    if record is None or record.user_id != x_user_id:
        raise HTTPException(status_code=404, detail="trip not found")
    record.status = {"accept": "accepted", "modify": "modified", "reject": "rejected"}[req.action]
    record.feedback.append({"action": req.action, "detail": req.detail})
    return {"trip_id": record.trip_id, "status": record.status}
