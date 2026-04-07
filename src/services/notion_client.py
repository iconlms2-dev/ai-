"""Notion API 래퍼"""
import json
import os
from datetime import datetime

import requests as req

from src.services.config import NOTION_TOKEN, KEYWORD_DB_ID, PROGRESS_FILE


def save_keyword_to_notion(keyword_data):
    """키워드 데이터를 Notion DB에 저장"""
    headers = {
        'Authorization': f'Bearer {NOTION_TOKEN}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    props = {
        '키워드': {'title': [{'text': {'content': keyword_data['keyword']}}]},
        '상태': {'select': {'name': '미사용'}},
    }
    if keyword_data.get('competition') and keyword_data['competition'] != '-':
        props['경쟁 강도'] = {'select': {'name': keyword_data['competition']}}
    if keyword_data.get('contact_point'):
        props['구매여정_단계'] = {'select': {'name': keyword_data['contact_point']}}

    payload = {'parent': {'database_id': KEYWORD_DB_ID}, 'properties': props}
    try:
        r = req.post('https://api.notion.com/v1/pages', headers=headers, json=payload, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def notion_query_all(db_id, filter_obj=None):
    """노션 DB 전체 페이지 조회 (페이지네이션 포함)"""
    headers = {
        'Authorization': 'Bearer %s' % NOTION_TOKEN,
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }
    all_results = []
    has_more = True
    start_cursor = None
    while has_more:
        payload = {'page_size': 100}
        if filter_obj:
            payload['filter'] = filter_obj
        if start_cursor:
            payload['start_cursor'] = start_cursor
        try:
            r = req.post('https://api.notion.com/v1/databases/%s/query' % db_id, headers=headers, json=payload, timeout=30)
            if r.status_code != 200:
                print("Notion query error: %s" % r.text[:200])
                break
            data = r.json()
            all_results.extend(data.get('results', []))
            has_more = data.get('has_more', False)
            start_cursor = data.get('next_cursor')
        except Exception as e:
            print("Notion query error: %s" % e)
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
    """Notion API 공통 헤더"""
    return {
        'Authorization': f'Bearer {NOTION_TOKEN}',
        'Content-Type': 'application/json',
        'Notion-Version': '2022-06-28',
    }


def save_progress(results, remaining):
    try:
        with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump({'results': results, 'remaining': remaining, 'ts': datetime.now().isoformat()}, f, ensure_ascii=False)
    except Exception as e:
        print(f"[save_progress] 저장 실패: {e}")


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None
