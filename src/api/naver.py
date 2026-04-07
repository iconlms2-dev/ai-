"""네이버 계정 관리 API 라우터"""
import json
import os
import threading
import uuid
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.services.config import BASE_DIR

router = APIRouter()

NAVER_ACCOUNTS_FILE = os.path.join(BASE_DIR, "naver_accounts.json")
_naver_accounts_lock = threading.Lock()


# ═══════════════════════════ HELPERS ═══════════════════════════

def _naver_load_accounts():
    if os.path.exists(NAVER_ACCOUNTS_FILE):
        try:
            with open(NAVER_ACCOUNTS_FILE, encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[naver_accounts] 로드 오류: {e}")
    return []


def _naver_save_accounts(accounts):
    with _naver_accounts_lock:
        tmp = NAVER_ACCOUNTS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(accounts, f, ensure_ascii=False, indent=2)
        os.replace(tmp, NAVER_ACCOUNTS_FILE)


# ═══════════════════════════ ENDPOINTS ═══════════════════════════

@router.get("/accounts")
async def naver_accounts_list():
    accounts = _naver_load_accounts()
    safe = []
    for acc in accounts:
        safe.append({
            'id': acc.get('id', ''),
            'label': acc.get('label', ''),
            'naver_id': acc.get('naver_id', ''),
            'platform': acc.get('platform', ''),
            'purpose': acc.get('purpose', ''),
            'active_cafes': acc.get('active_cafes', []),
            'proxy': acc.get('proxy', ''),
            'status': acc.get('status', '활성'),
            'daily_limit': acc.get('daily_limit', 3),
            'min_interval_hours': acc.get('min_interval_hours', 2),
            'active_hours': acc.get('active_hours', [9, 22]),
            'total_posts': acc.get('total_posts', 0),
            'last_used_at': acc.get('last_used_at', ''),
            'created_at': acc.get('created_at', ''),
            'notes': acc.get('notes', ''),
        })
    return {'accounts': safe}


@router.post("/accounts")
async def naver_accounts_add(request: Request):
    body = await request.json()
    accounts = _naver_load_accounts()
    acc_id = 'naver_' + str(uuid.uuid4())[:8]
    account = {
        'id': acc_id,
        'label': body.get('label', ''),
        'naver_id': body.get('naver_id', ''),
        'platform': body.get('platform', '블로그'),
        'purpose': body.get('purpose', '최적화'),
        'active_cafes': body.get('active_cafes', []),
        'proxy': body.get('proxy', ''),
        'status': body.get('status', '활성'),
        'daily_limit': body.get('daily_limit', 3),
        'min_interval_hours': body.get('min_interval_hours', 2),
        'active_hours': body.get('active_hours', [9, 22]),
        'total_posts': 0,
        'last_used_at': None,
        'created_at': datetime.now().strftime('%Y-%m-%d'),
        'notes': body.get('notes', ''),
    }
    accounts.append(account)
    _naver_save_accounts(accounts)
    return {'ok': True, 'id': acc_id}


@router.patch("/accounts/{acc_id}")
async def naver_accounts_update(acc_id: str, request: Request):
    body = await request.json()
    accounts = _naver_load_accounts()
    for acc in accounts:
        if acc['id'] == acc_id:
            for key in ['label', 'naver_id', 'platform', 'purpose', 'active_cafes', 'proxy', 'status', 'daily_limit', 'min_interval_hours', 'active_hours', 'notes']:
                if key in body:
                    acc[key] = body[key]
            _naver_save_accounts(accounts)
            return {'ok': True}
    return JSONResponse({'ok': False, 'error': '계정 없음'}, 404)


@router.delete("/accounts/{acc_id}")
async def naver_accounts_delete(acc_id: str):
    accounts = _naver_load_accounts()
    accounts = [a for a in accounts if a.get('id') != acc_id]
    _naver_save_accounts(accounts)
    return {'ok': True}
