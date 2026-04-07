"""카페24 연동"""
import os
import json
import time
import base64

import requests as req
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.services.config import (
    BASE_DIR, CAFE24_CLIENT_ID, CAFE24_CLIENT_SECRET, CAFE24_MALL_ID, CAFE24_TOKEN_FILE,
)

router = APIRouter()


def _cafe24_load_token():
    if os.path.exists(CAFE24_TOKEN_FILE):
        with open(CAFE24_TOKEN_FILE, 'r') as f:
            return json.load(f)
    return {}


def _cafe24_save_token(token_data):
    with open(CAFE24_TOKEN_FILE, 'w') as f:
        json.dump(token_data, f, ensure_ascii=False)


def _cafe24_refresh_token():
    token = _cafe24_load_token()
    if not token.get('refresh_token'):
        return None
    auth = base64.b64encode(f'{CAFE24_CLIENT_ID}:{CAFE24_CLIENT_SECRET}'.encode()).decode()
    r = req.post(f'https://{CAFE24_MALL_ID}.cafe24api.com/api/v2/oauth/token',
                 headers={'Authorization': f'Basic {auth}', 'Content-Type': 'application/x-www-form-urlencoded'},
                 data={'grant_type': 'refresh_token', 'refresh_token': token['refresh_token']}, timeout=10)
    if r.status_code == 200:
        new_token = r.json()
        new_token['refresh_token'] = new_token.get('refresh_token', token['refresh_token'])
        _cafe24_save_token(new_token)
        return new_token
    return None


def _cafe24_api(endpoint):
    token = _cafe24_load_token()
    if not token.get('access_token'):
        token = _cafe24_refresh_token()
    if not token:
        return None
    headers = {'Authorization': f'Bearer {token["access_token"]}', 'Content-Type': 'application/json',
               'X-Cafe24-Api-Version': '2024-03-01'}
    r = req.get(f'https://{CAFE24_MALL_ID}.cafe24api.com/api/v2/{endpoint}', headers=headers, timeout=15)
    if r.status_code == 401:
        token = _cafe24_refresh_token()
        if token:
            headers['Authorization'] = f'Bearer {token["access_token"]}'
            r = req.get(f'https://{CAFE24_MALL_ID}.cafe24api.com/api/v2/{endpoint}', headers=headers, timeout=15)
    if r.status_code == 200:
        return r.json()
    return None


@router.get("/auth-url")
async def cafe24_auth_url():
    """카페24 OAuth 인증 URL 생성"""
    scope = 'mall.read_salesreport,mall.read_order,mall.read_analytics'
    redirect_uri = os.environ.get('CAFE24_REDIRECT_URI', '')
    url = f'https://{CAFE24_MALL_ID}.cafe24api.com/api/v2/oauth/authorize?response_type=code&client_id={CAFE24_CLIENT_ID}&scope={scope}&redirect_uri={redirect_uri}'
    return {'url': url}


@router.post("/auth-callback")
async def cafe24_auth_callback(request: Request):
    """인증코드로 토큰 발급"""
    body = await request.json()
    code = body.get('code', '')
    if not code:
        return JSONResponse({'error': 'code 필요'}, 400)
    auth = base64.b64encode(f'{CAFE24_CLIENT_ID}:{CAFE24_CLIENT_SECRET}'.encode()).decode()
    try:
        r = req.post(f'https://{CAFE24_MALL_ID}.cafe24api.com/api/v2/oauth/token',
                     headers={'Authorization': f'Basic {auth}', 'Content-Type': 'application/x-www-form-urlencoded'},
                     data={'grant_type': 'authorization_code', 'code': code,
                           'redirect_uri': os.environ.get('CAFE24_REDIRECT_URI', '')}, timeout=10)
        if r.status_code == 200:
            _cafe24_save_token(r.json())
            return {'ok': True}
        return JSONResponse({'ok': False, 'error': r.text[:300]}, 400)
    except Exception as e:
        return JSONResponse({'ok': False, 'error': str(e)}, 500)


@router.get("/status")
async def cafe24_status():
    """카페24 연동 상태 확인"""
    token = _cafe24_load_token()
    return {'connected': bool(token.get('access_token')), 'mall_id': CAFE24_MALL_ID}


@router.get("/sales")
async def cafe24_sales(start: str = '', end: str = ''):
    """매출/주문 데이터 조회"""
    if not start or not end:
        today = time.strftime('%Y-%m-%d')
        start = start or today
        end = end or today
    data = _cafe24_api(f'admin/orders/count?start_date={start}&end_date={end}')
    sales = _cafe24_api(f'admin/salesreport?start_date={start}&end_date={end}')
    return {'orders': data, 'sales': sales, 'period': f'{start} ~ {end}'}


@router.get("/analytics")
async def cafe24_analytics(start: str = '', end: str = ''):
    """접속/유입 통계 조회"""
    if not start or not end:
        today = time.strftime('%Y-%m-%d')
        start = start or today
        end = end or today
    data = _cafe24_api(f'admin/analytics/dailyvisits?start_date={start}&end_date={end}')
    return {'analytics': data, 'period': f'{start} ~ {end}'}
