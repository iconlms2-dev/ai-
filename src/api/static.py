"""정적 파일 서빙 + UTM 관리"""
import os
import json
import time
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from src.services.config import BASE_DIR

router = APIRouter()
UTM_FILE = os.path.join(BASE_DIR, "utm_history.json")


@router.get("/")
async def serve_dashboard():
    return FileResponse(os.path.join(BASE_DIR, "dashboard.html"))


@router.get("/사용안내서.html")
async def serve_manual():
    return FileResponse(os.path.join(BASE_DIR, "사용안내서.html"), media_type="text/html")


@router.post("/api/utm/generate")
async def utm_generate(request: Request):
    """UTM 파라미터 생성"""
    body = await request.json()
    base_url = body.get('url', '')
    channel = body.get('channel', '')
    keyword = body.get('keyword', '')
    campaign = body.get('campaign', '')
    if not base_url:
        return JSONResponse({'error': 'URL 필요'}, 400)
    params = {
        'utm_source': channel or 'direct',
        'utm_medium': 'content',
        'utm_campaign': campaign or keyword or 'default',
        'utm_term': keyword,
        'utm_content': channel
    }
    sep = '&' if '?' in base_url else '?'
    utm_url = base_url + sep + '&'.join(f'{k}={quote(str(v))}' for k, v in params.items() if v)
    # 이력 저장
    history = []
    if os.path.exists(UTM_FILE):
        with open(UTM_FILE, 'r') as f:
            history = json.load(f)
    history.append({'url': utm_url, 'channel': channel, 'keyword': keyword, 'campaign': campaign, 'created': time.strftime('%Y-%m-%d %H:%M')})
    with open(UTM_FILE, 'w') as f:
        json.dump(history[-500:], f, ensure_ascii=False)  # 최근 500개 유지
    return {'utm_url': utm_url, 'params': params}


@router.get("/api/utm/history")
async def utm_history():
    """UTM 생성 이력 조회"""
    if os.path.exists(UTM_FILE):
        with open(UTM_FILE, 'r') as f:
            return {'history': json.load(f)}
    return {'history': []}
