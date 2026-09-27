"""
Facebook connection, groups and leads endpoints
-----------------------------------------------
  GET    /facebook/connection          status + settings + current/last agent run
  POST   /facebook/connect             {cookies} link a Facebook session
  POST   /facebook/connection/verify   re-check the stored session
  PATCH  /facebook/connection          {auto_join?, harvest_enabled?}
  DELETE /facebook/connection          unlink (removes cookies + group list)

  GET    /facebook/groups              the account's groups
  POST   /facebook/groups              {url} add a group by link
  PATCH  /facebook/groups/{group_id}   {enabled}

  POST   /facebook/agent/run           {tasks?, areas?} start the groups agent
  GET    /facebook/leads               ?status=new&limit=100
  PATCH  /facebook/leads/{lead_id}     {status}

All require the fh_token login cookie.
"""

import threading
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_current_user

router = APIRouter(prefix="/facebook", tags=["facebook"])

# user_id → {"status": "running"|"done"|"error", "started_at", "report"?}
_agent_runs: dict[str, dict] = {}
_runs_lock = threading.Lock()


class ConnectRequest(BaseModel):
    cookies: str


class ConnectionSettings(BaseModel):
    auto_join: Optional[bool] = None
    harvest_enabled: Optional[bool] = None


class AddGroupRequest(BaseModel):
    url: str


class GroupUpdate(BaseModel):
    enabled: bool


class AgentRunRequest(BaseModel):
    tasks: list[str] = ["discover", "harvest"]
    areas: list[str] = []


class LeadUpdate(BaseModel):
    status: str


def _store():
    from agents.facebook import store
    return store


def _connection_view(user_id: str, row: dict | None) -> dict:
    run = _agent_runs.get(user_id)
    if not row:
        return {"connected": False, "run": run}
    return {
        "connected": True,
        "status": row.get("status"),
        "status_detail": row.get("status_detail"),
        "fb_user_id": row.get("fb_user_id"),
        "connected_at": row.get("connected_at"),
        "verified_at": row.get("verified_at"),
        "auto_join": row.get("auto_join", False),
        "harvest_enabled": row.get("harvest_enabled", True),
        "last_run_at": row.get("last_run_at"),
        "last_run_summary": row.get("last_run_summary"),
        "run": run,
    }


def _require_connection(user_id: str) -> dict:
    row = _store().get_connection(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Facebook isn't connected yet.")
    return row


# ── Connection ────────────────────────────────────────────────────────────────

@router.get("/connection")
def get_connection(user: dict = Depends(get_current_user)):
    return _connection_view(user["user_id"], _store().get_connection(user["user_id"]))


@router.post("/connect")
def connect(req: ConnectRequest, user: dict = Depends(get_current_user)):
    from agents.facebook.session import clear_cache, parse_cookie_input, verify_cookies

    try:
        cookies = parse_cookie_input(req.cookies)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    ok, detail = verify_cookies(cookies)
    if ok is False:
        raise HTTPException(status_code=400, detail=detail)

    store = _store()
    row = store.save_connection(user["user_id"], cookies, "active" if ok else "unverified", detail)
    clear_cache(user["user_id"])
    return _connection_view(user["user_id"], row)


@router.post("/connection/verify")
def verify_connection(user: dict = Depends(get_current_user)):
    from agents.facebook.session import clear_cache, verify_cookies

    store = _store()
    row = _require_connection(user["user_id"])
    cookies = store.decrypt_cookies(row)
    if not cookies:
        raise HTTPException(status_code=409, detail="Stored session can't be read. Connect again.")
    ok, detail = verify_cookies(cookies)
    fields = {"status_detail": detail}
    if ok:
        fields.update(status="active", verified_at=datetime.now(timezone.utc).isoformat())
    elif ok is False:
        fields["status"] = "expired"
    store.update_connection(user["user_id"], **fields)
    clear_cache(user["user_id"])
    return _connection_view(user["user_id"], store.get_connection(user["user_id"]))


@router.patch("/connection")
def update_settings(req: ConnectionSettings, user: dict = Depends(get_current_user)):
    _require_connection(user["user_id"])
    fields = req.model_dump(exclude_none=True)
    if fields:
        _store().update_connection(user["user_id"], **fields)
    return _connection_view(user["user_id"], _store().get_connection(user["user_id"]))


@router.delete("/connection")
def disconnect(user: dict = Depends(get_current_user)):
    from agents.facebook.session import clear_cache

    _store().delete_connection(user["user_id"])
    clear_cache(user["user_id"])
    _agent_runs.pop(user["user_id"], None)
    return {"connected": False}


# ── Groups ────────────────────────────────────────────────────────────────────

@router.get("/groups")
def list_groups(user: dict = Depends(get_current_user)):
    return {"groups": _store().list_user_groups(user["user_id"])}


@router.post("/groups")
def add_group(req: AddGroupRequest, user: dict = Depends(get_current_user)):
    try:
        row = _store().add_group_by_url(user["user_id"], req.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"group": row}


@router.patch("/groups/{group_id}")
def update_group(group_id: str, req: GroupUpdate, user: dict = Depends(get_current_user)):
    _store().update_user_group(user["user_id"], group_id, enabled=req.enabled)
    return {"ok": True}


# ── Agent ─────────────────────────────────────────────────────────────────────

def _run_agent_job(user_id: str, tasks: list[str], areas: list[str]) -> None:
    from agents.fb_groups_agent import run_agent

    try:
        report = run_agent(user_id, tasks, {"areas": areas})
        state = {"status": "error" if report["session_expired"] else "done", "report": report}
    except Exception as e:
        state = {"status": "error", "report": {"errors": [f"{e!r}"]}}
    with _runs_lock:
        _agent_runs[user_id] = {**_agent_runs.get(user_id, {}), **state,
                                "finished_at": datetime.now(timezone.utc).isoformat()}


@router.post("/agent/run")
def start_agent(req: AgentRunRequest, background: BackgroundTasks, user: dict = Depends(get_current_user)):
    from agents.fb_groups_agent import TASKS

    user_id = user["user_id"]
    row = _require_connection(user_id)
    if row.get("status") == "expired":
        raise HTTPException(status_code=409, detail="Your Facebook session expired. Reconnect first.")
    tasks = [t for t in req.tasks if t in TASKS]
    if not tasks:
        raise HTTPException(status_code=400, detail=f"tasks must be some of: {', '.join(TASKS)}")

    with _runs_lock:
        if (_agent_runs.get(user_id) or {}).get("status") == "running":
            raise HTTPException(status_code=409, detail="The agent is already running for your account.")
        _agent_runs[user_id] = {
            "status": "running",
            "tasks": tasks,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
    background.add_task(_run_agent_job, user_id, tasks, req.areas)
    return {"run": _agent_runs[user_id]}


# ── Leads ─────────────────────────────────────────────────────────────────────

@router.get("/leads")
def list_leads(status: Optional[str] = None, limit: int = 100, user: dict = Depends(get_current_user)):
    store = _store()
    if status and status not in store.LEAD_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of: {', '.join(store.LEAD_STATUSES)}")
    return {"leads": store.list_leads(user["user_id"], status, min(max(limit, 1), 500))}


@router.patch("/leads/{lead_id}")
def update_lead(lead_id: str, req: LeadUpdate, user: dict = Depends(get_current_user)):
    store = _store()
    if req.status not in store.LEAD_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of: {', '.join(store.LEAD_STATUSES)}")
    lead = store.update_lead(user["user_id"], lead_id, status=req.status)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")
    return {"lead": lead}
