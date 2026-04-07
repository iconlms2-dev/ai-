"""
카페 댓글 자동 등록 안전 규칙

멘토님 원칙:
- 1계정당 하루 최대 댓글 5개
- 같은 게시글에 같은 계정 중복 금지
- 댓글 간 최소 30초~3분 랜덤 대기
- 같은 카페 주 1~2회 제한
"""

import json
import os
import random
import time
from datetime import datetime, timedelta
from threading import Lock

_HISTORY_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cafe_comment_history.json")
_lock = Lock()


def _load_history():
    if os.path.exists(_HISTORY_FILE):
        try:
            with open(_HISTORY_FILE, encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {'records': []}


def _save_history(data):
    with _lock:
        tmp = _HISTORY_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _HISTORY_FILE)


def check_rules(account_id, cafe_url, post_url):
    """
    안전 규칙 체크. 통과하면 (True, ''), 실패하면 (False, '사유')
    """
    history = _load_history()
    records = history.get('records', [])
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')

    # 카페 URL에서 카페 이름 추출
    cafe_name = ''
    if 'cafe.naver.com/' in (cafe_url or post_url or ''):
        parts = (cafe_url or post_url).split('cafe.naver.com/')
        if len(parts) > 1:
            cafe_name = parts[1].split('/')[0].split('?')[0]

    # 1. 1계정당 하루 최대 댓글 5개
    today_count = sum(1 for r in records
                      if r.get('account_id') == account_id
                      and r.get('date') == today)
    if today_count >= 5:
        return False, f'하루 한도 초과 (오늘 {today_count}/5개)'

    # 2. 같은 게시글에 같은 계정 중복 금지
    for r in records:
        if r.get('account_id') == account_id and r.get('post_url') == post_url:
            return False, '이미 이 게시글에 댓글을 단 계정'

    # 3. 같은 카페 주 1~2회 제한
    week_ago = (now - timedelta(days=7)).isoformat()
    cafe_week_count = sum(1 for r in records
                          if r.get('account_id') == account_id
                          and r.get('cafe_name') == cafe_name
                          and r.get('timestamp', '') > week_ago)
    if cafe_week_count >= 2:
        return False, f'이 카페 주간 한도 초과 ({cafe_name}: {cafe_week_count}/2회)'

    return True, ''


def record_comment(account_id, cafe_name, post_url, comment_text, success=True):
    """댓글 등록 기록 저장"""
    history = _load_history()
    history['records'].append({
        'account_id': account_id,
        'cafe_name': cafe_name,
        'post_url': post_url,
        'comment_preview': comment_text[:50],
        'success': success,
        'date': datetime.now().strftime('%Y-%m-%d'),
        'timestamp': datetime.now().isoformat(),
    })
    # 최근 1000개만 유지
    if len(history['records']) > 1000:
        history['records'] = history['records'][-1000:]
    _save_history(history)


def get_random_delay():
    """댓글 간 랜덤 대기 시간 (30초~3분)"""
    return random.uniform(30, 180)


def get_account_stats(account_id):
    """계정별 오늘 사용량 조회"""
    history = _load_history()
    today = datetime.now().strftime('%Y-%m-%d')
    today_count = sum(1 for r in history.get('records', [])
                      if r.get('account_id') == account_id
                      and r.get('date') == today)
    total_count = sum(1 for r in history.get('records', [])
                      if r.get('account_id') == account_id)
    return {
        'today': today_count,
        'remaining': max(0, 5 - today_count),
        'total': total_count,
    }


def get_history(limit=50):
    """최근 등록 이력"""
    history = _load_history()
    return history.get('records', [])[-limit:]
