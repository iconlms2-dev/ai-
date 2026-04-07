"""작업함(Work Inbox) API — Slack 실행 결과를 대시보드에서 확인·저장"""
import json
import os
import time
from datetime import datetime, timedelta

import requests as req
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.services.config import WORK_INBOX_FILE, CONTENT_DB_ID, NOTION_TOKEN

router = APIRouter()


# ── 헬퍼 ──

def _load_inbox() -> dict:
    if os.path.exists(WORK_INBOX_FILE):
        try:
            with open(WORK_INBOX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"items": []}


def _save_inbox(data: dict):
    with open(WORK_INBOX_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_to_inbox(item: dict):
    """작업함에 항목 추가 (slack_bot.py에서 호출)."""
    data = _load_inbox()
    item.setdefault("id", f"{item.get('channel','?')}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{len(data['items'])+1:03d}")
    item.setdefault("created_at", datetime.now().isoformat())
    item.setdefault("saved_to_notion", False)
    item.setdefault("source", "slack")
    data["items"].append(item)
    _save_inbox(data)
    return item["id"]


# ── API ──

@router.get("/list")
async def inbox_list(request: Request):
    """작업함 목록 조회. ?channel=blog&status=approved&days=7"""
    params = request.query_params
    channel = params.get("channel")
    status = params.get("status")
    days = int(params.get("days", 7))

    data = _load_inbox()
    items = data.get("items", [])

    # 날짜 필터
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    items = [i for i in items if i.get("created_at", "") >= cutoff]

    # 채널 필터
    if channel:
        items = [i for i in items if i.get("channel") == channel]

    # 상태 필터
    if status == "approved":
        items = [i for i in items if i.get("review_passed") is True and not i.get("saved_to_notion")]
    elif status == "failed":
        items = [i for i in items if i.get("review_passed") is False]
    elif status == "saved":
        items = [i for i in items if i.get("saved_to_notion") is True]
    elif status == "unsaved":
        items = [i for i in items if not i.get("saved_to_notion")]

    # 최신순
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    # 요약
    all_items = data.get("items", [])
    recent = [i for i in all_items if i.get("created_at", "") >= cutoff]
    summary = {
        "total": len(recent),
        "approved": len([i for i in recent if i.get("review_passed") is True and not i.get("saved_to_notion")]),
        "failed": len([i for i in recent if i.get("review_passed") is False]),
        "saved": len([i for i in recent if i.get("saved_to_notion") is True]),
    }

    return {"items": items, "summary": summary}


@router.post("/save-notion")
async def inbox_save_notion(request: Request):
    """작업함 항목 → Notion 저장. 채널별 save-notion API를 내부 호출."""
    body = await request.json()
    item_id = body.get("id")

    data = _load_inbox()
    item = next((i for i in data["items"] if i.get("id") == item_id), None)
    if not item:
        return JSONResponse({"error": "항목을 찾을 수 없습니다"}, status_code=404)

    if item.get("saved_to_notion"):
        return JSONResponse({"error": "이미 저장된 항목입니다"}, status_code=400)

    channel = item.get("channel", "")
    content = item.get("content", {})

    # 채널별 Notion 저장 API 매핑
    save_endpoints = {
        "blog": "/api/blog/save-notion",
        "cafe-seo": "/api/cafe/save-notion",
        "cafe-viral": "/api/viral/save-notion",
        "jisikin": "/api/jisikin/save-notion",
        "youtube": "/api/youtube/save-notion",
        "tiktok": "/api/tiktok/save-notion",
        "shorts": "/api/shorts/save-notion",
        "community": "/api/community/save-notion",
        "powercontent": "/api/powercontent/save-notion",
        "threads": "/api/threads/save-notion",
    }

    endpoint = save_endpoints.get(channel)
    if not endpoint:
        return JSONResponse({"error": f"알 수 없는 채널: {channel}"}, status_code=400)

    # 내부 API 호출로 Notion 저장
    try:
        payload = {**content, "review_status": item.get("review_status", "draft")}
        r = req.post(f"http://localhost:8000{endpoint}", json=payload, timeout=30)
        if r.status_code == 200:
            item["saved_to_notion"] = True
            item["saved_at"] = datetime.now().isoformat()
            _save_inbox(data)
            return {"success": True, "message": "Notion 저장 완료"}
        else:
            return JSONResponse({"error": f"Notion 저장 실패: {r.text[:200]}"}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": f"Notion 저장 에러: {e}"}, status_code=500)


@router.post("/save-all")
async def inbox_save_all(request: Request):
    """승인됨 항목 일괄 Notion 저장."""
    data = _load_inbox()
    saved = 0
    errors = []

    for item in data["items"]:
        if item.get("review_passed") and not item.get("saved_to_notion"):
            channel = item.get("channel", "")
            content = item.get("content", {})

            save_endpoints = {
                "blog": "/api/blog/save-notion",
                "cafe-seo": "/api/cafe/save-notion",
                "cafe-viral": "/api/viral/save-notion",
                "jisikin": "/api/jisikin/save-notion",
                "youtube": "/api/youtube/save-notion",
                "tiktok": "/api/tiktok/save-notion",
                "shorts": "/api/shorts/save-notion",
                "community": "/api/community/save-notion",
                "powercontent": "/api/powercontent/save-notion",
                "threads": "/api/threads/save-notion",
            }

            endpoint = save_endpoints.get(channel)
            if not endpoint:
                errors.append(f"{item.get('id')}: 알 수 없는 채널")
                continue

            try:
                payload = {**content, "review_status": item.get("review_status", "draft")}
                r = req.post(f"http://localhost:8000{endpoint}", json=payload, timeout=30)
                if r.status_code == 200:
                    item["saved_to_notion"] = True
                    item["saved_at"] = datetime.now().isoformat()
                    saved += 1
                else:
                    errors.append(f"{item.get('id')}: {r.status_code}")
            except Exception as e:
                errors.append(f"{item.get('id')}: {e}")

    _save_inbox(data)
    return {"saved": saved, "errors": errors}


@router.post("/delete")
async def inbox_delete(request: Request):
    """항목 삭제."""
    body = await request.json()
    item_id = body.get("id")

    data = _load_inbox()
    data["items"] = [i for i in data["items"] if i.get("id") != item_id]
    _save_inbox(data)
    return {"success": True}


@router.post("/delete-saved")
async def inbox_delete_saved(request: Request):
    """저장완료 항목 일괄 삭제."""
    data = _load_inbox()
    before = len(data["items"])
    data["items"] = [i for i in data["items"] if not i.get("saved_to_notion")]
    _save_inbox(data)
    return {"deleted": before - len(data["items"])}
