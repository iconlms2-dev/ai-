"""Notion API 래퍼 — notion-sdk-py 기반.

기존 함수 시그니처 100% 호환. 내부만 SDK로 교체.
SDK 장점: 내장 재시도, 429 Rate Limit 자동 처리, 타입 안전성.
"""
import json
import logging
import os
from datetime import datetime

from notion_client import Client
from notion_client.errors import APIResponseError

from src.services.config import NOTION_TOKEN, KEYWORD_DB_ID, PROGRESS_FILE, EXPAND_PROGRESS_FILE

logger = logging.getLogger(__name__)

# ── SDK 클라이언트 싱글턴 ──
# notion-sdk-py의 Client는 내부적으로 httpx.Client를 사용.
# httpx.Client는 connection pooling과 스레드 안전성을 보장하므로
# 단일 인스턴스를 여러 라우터에서 공유해도 안전.
notion = Client(auth=NOTION_TOKEN) if NOTION_TOKEN else None


def save_keyword_to_notion(keyword_data):
    """키워드 데이터를 Notion DB에 저장"""
    if not notion:
        logger.error("NOTION_TOKEN 미설정")
        return False

    props = {
        '키워드': {'title': [{'text': {'content': keyword_data['keyword']}}]},
        '상태': {'select': {'name': '미사용'}},
    }
    if keyword_data.get('competition') and keyword_data['competition'] != '-':
        props['경쟁 강도'] = {'select': {'name': keyword_data['competition']}}
    if keyword_data.get('contact_point'):
        props['구매여정_단계'] = {'select': {'name': keyword_data['contact_point']}}

    try:
        notion.pages.create(parent={'database_id': KEYWORD_DB_ID}, properties=props)
        return True
    except APIResponseError as e:
        logger.error("Notion 저장 실패 [%s]: %s", e.code, e.message)
        return False
    except Exception as e:
        logger.error("Notion 저장 실패: %s", e)
        return False


def notion_query_all(db_id, filter_obj=None):
    """노션 DB 전체 페이지 조회 (페이지네이션 포함)"""
    if not notion:
        logger.error("NOTION_TOKEN 미설정")
        return []

    all_results = []
    has_more = True
    start_cursor = None
    while has_more:
        try:
            kwargs = {'database_id': db_id, 'page_size': 100}
            if filter_obj:
                kwargs['filter'] = filter_obj
            if start_cursor:
                kwargs['start_cursor'] = start_cursor
            data = notion.databases.query(**kwargs)
            all_results.extend(data.get('results', []))
            has_more = data.get('has_more', False)
            start_cursor = data.get('next_cursor')
        except APIResponseError as e:
            logger.error("Notion query 실패 [%s]: %s", e.code, e.message)
            break
        except Exception as e:
            logger.error("Notion query 실패: %s", e)
            break
    return all_results


def extract_prop(props, name, prop_type):
    """노션 property에서 값 추출"""
    p = props.get(name, {})
    if prop_type == 'title':
        t = p.get('title', [])
        return t[0]['text']['content'] if t else ''
    elif prop_type == 'rich_text':
        t = p.get('rich_text', [])
        return t[0]['text']['content'] if t else ''
    elif prop_type == 'select':
        s = p.get('select')
        return s.get('name', '') if s else ''
    elif prop_type == 'multi_select':
        ms = p.get('multi_select', [])
        return [x.get('name', '') for x in ms]
    elif prop_type == 'number':
        return p.get('number') or 0
    elif prop_type == 'relation':
        return [x.get('id', '') for x in p.get('relation', [])]
    elif prop_type == 'date':
        d = p.get('date')
        return d.get('start', '') if d else ''
    elif prop_type == 'url':
        return p.get('url', '') or ''
    return ''


def notion_headers():
    """Notion API 공통 헤더 — 직접 requests 호출이 필요한 곳용 (하위호환)"""
    return {
        'Authorization': f'Bearer {NOTION_TOKEN}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }


# ── SDK 래퍼 함수 (라우터의 직접 호출을 대체) ──

def create_page(database_id, properties, children=None):
    """Notion 페이지 생성 — SDK 래퍼"""
    if not notion:
        return {'success': False, 'error': 'NOTION_TOKEN 미설정'}
    try:
        kwargs = {'parent': {'database_id': database_id}, 'properties': properties}
        if children:
            kwargs['children'] = children[:100]
        result = notion.pages.create(**kwargs)
        return {'success': True, 'id': result['id'], 'data': result}
    except APIResponseError as e:
        logger.error("Notion 페이지 생성 실패 [%s]: %s", e.code, e.message)
        return {'success': False, 'error': f"[{e.code}] {e.message}"}
    except Exception as e:
        logger.error("Notion 페이지 생성 실패: %s", e)
        return {'success': False, 'error': str(e)}


def update_page(page_id, properties):
    """Notion 페이지 업데이트 — SDK 래퍼"""
    if not notion:
        return {'success': False, 'error': 'NOTION_TOKEN 미설정'}
    try:
        result = notion.pages.update(page_id=page_id, properties=properties)
        return {'success': True, 'data': result}
    except APIResponseError as e:
        logger.error("Notion 페이지 업데이트 실패 [%s]: %s", e.code, e.message)
        return {'success': False, 'error': f"[{e.code}] {e.message}"}
    except Exception as e:
        logger.error("Notion 페이지 업데이트 실패: %s", e)
        return {'success': False, 'error': str(e)}


def query_database(db_id, filter_obj=None, page_size=100, start_cursor=None):
    """Notion DB 단일 쿼리 — SDK 래퍼 (페이지네이션 1회)"""
    if not notion:
        return {'results': [], 'has_more': False}
    try:
        kwargs = {'database_id': db_id, 'page_size': page_size}
        if filter_obj:
            kwargs['filter'] = filter_obj
        if start_cursor:
            kwargs['start_cursor'] = start_cursor
        return notion.databases.query(**kwargs)
    except APIResponseError as e:
        logger.error("Notion DB 쿼리 실패 [%s]: %s", e.code, e.message)
        return {'results': [], 'has_more': False}
    except Exception as e:
        logger.error("Notion DB 쿼리 실패: %s", e)
        return {'results': [], 'has_more': False}


# ── 진행 상태 저장 (로컬 파일) ──

def save_progress(results, remaining):
    try:
        with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump({'results': results, 'remaining': remaining, 'ts': datetime.now().isoformat()}, f, ensure_ascii=False)
    except Exception as e:
        logger.error("save_progress 저장 실패: %s", e)


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_expand_progress(all_kws, visited, remaining_seeds, mode, queue=None, round_num=0):
    """키워드 확장 중간 진행 저장"""
    try:
        data = {
            'all_kws': dict(all_kws),
            'visited': list(visited),
            'remaining_seeds': remaining_seeds,
            'mode': mode,
            'queue': queue or [],
            'round_num': round_num,
            'ts': datetime.now().isoformat(),
        }
        with open(EXPAND_PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.error("save_expand_progress 저장 실패: %s", e)


def load_expand_progress():
    """키워드 확장 진행 복구"""
    if os.path.exists(EXPAND_PROGRESS_FILE):
        try:
            with open(EXPAND_PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error("load_expand_progress 로드 실패: %s", e)
    return None


def clear_expand_progress():
    """키워드 확장 진행 파일 삭제"""
    try:
        if os.path.exists(EXPAND_PROGRESS_FILE):
            os.remove(EXPAND_PROGRESS_FILE)
    except Exception as e:
        logger.error("clear_expand_progress 삭제 실패: %s", e)
