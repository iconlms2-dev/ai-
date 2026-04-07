"""프롬프트 테스트 전용 서버 (port 8001) — 메인 서버 없이 독립 동작"""
import json, os, sys
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import requests as req

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'), override=True)
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

# server.py에서 프롬프트 함수들 직접 import
sys.path.insert(0, os.path.dirname(__file__))
from server import (
    _build_blog_title_prompt, _build_blog_body_prompt,
    _build_cafe_title_prompt, _build_cafe_body_prompt, _build_cafe_comments_prompt,
    _build_jisikin_title_prompt, _build_jisikin_body_prompt, _build_jisikin_answers_prompt,
    _build_youtube_comment_prompt,
    _build_tiktok_prompt,
    _build_community_post_prompt,
    _build_viral_stage1_prompt, _build_viral_stage2_prompt, _build_viral_stage3_prompt,
    _build_threads_daily_prompt, _build_threads_traffic_prompt,
)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

PROMPT_OVERRIDES_FILE = os.path.join(os.path.dirname(__file__), "prompt_overrides.json")

def _load_overrides():
    if os.path.exists(PROMPT_OVERRIDES_FILE):
        try:
            with open(PROMPT_OVERRIDES_FILE, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save_overrides(data):
    with open(PROMPT_OVERRIDES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _call_claude(system_prompt, user_prompt, temperature=0.7):
    headers = {'Content-Type':'application/json','x-api-key':ANTHROPIC_API_KEY,'anthropic-version':'2023-06-01'}
    payload = {'model':'claude-sonnet-4-20250514','max_tokens':4096,'system':system_prompt,'messages':[{'role':'user','content':user_prompt}],'temperature':temperature}
    try:
        r = req.post('https://api.anthropic.com/v1/messages', headers=headers, json=payload, timeout=60)
        if r.status_code == 200:
            data = r.json()
            if data.get('content'):
                return data['content'][0]['text']
        return f'[ERROR] {r.status_code}: {r.text[:300]}'
    except Exception as e:
        return f'[ERROR] {e}'

def _get_default_prompt(channel):
    """채널별 기본 시스템 프롬프트 — server.py 함수에서 직접 추출"""
    dp = {'name':'테스트제품','brand_keyword':'테스트키워드','usp':'핵심특징','target':'타겟층','ingredients':'성분'}
    mapping = {
        '블로그_제목': lambda: _build_blog_title_prompt('테스트', dp),
        '블로그_본문': lambda: _build_blog_body_prompt('테스트', '', dp, 10, 5, '테스트 제목'),
        '카페SEO_제목': lambda: _build_cafe_title_prompt('테스트', '원본제목'),
        '카페SEO_본문': lambda: _build_cafe_body_prompt('테스트', '제목', '', {}, dp),
        '카페SEO_댓글': lambda: _build_cafe_comments_prompt('테스트', '본문', '브랜드', ''),
        '지식인_질문제목': lambda: _build_jisikin_title_prompt('테스트', dp),
        '지식인_질문본문': lambda: _build_jisikin_body_prompt('테스트', dp),
        '지식인_답변': lambda: _build_jisikin_answers_prompt('테스트', '질문제목', '질문본문', dp),
        '유튜브댓글': lambda: _build_youtube_comment_prompt('테스트 영상', '더보기 내용', '테스트키워드'),
        '틱톡': lambda: _build_tiktok_prompt('테스트', '소구점', '구매원씽', dp, ''),
        '커뮤니티': lambda: _build_community_post_prompt('뽐뿌', '1', '테스트', '소구점', '구매원씽', dp, ''),
        '카페바이럴_일상글': lambda: _build_viral_stage1_prompt('타겟층', '타겟층', '일상 주제'),
        '카페바이럴_고민글': lambda: _build_viral_stage2_prompt('타겟층', '고민키워드', '건강기능식품'),
        '카페바이럴_침투글': lambda: _build_viral_stage3_prompt('타겟층', '고민키워드', '테스트키워드', '테스트제품', '핵심특징', '성분', '건강기능식품'),
        '쓰레드_일상글': lambda: _build_threads_daily_prompt({'name':'테스트','age':'30','job':'직장인','tone':'친근','interests':['건강']}, []),
        '쓰레드_물길글_셔플': lambda: _build_threads_traffic_prompt('테스트', {'tone':'친근','job':'직장인','interests':['건강']}, dp, '', 'shuffle'),
        '쓰레드_물길글_연민': lambda: _build_threads_traffic_prompt('테스트', {'tone':'친근'}, dp, '', 'sympathy'),
        '쓰레드_물길글_후기': lambda: _build_threads_traffic_prompt('테스트', {'tone':'친근','job':'직장인','interests':['건강']}, dp, '', 'review'),
    }
    builder = mapping.get(channel)
    if builder:
        sys_p, _ = builder()
        return sys_p
    return ''

@app.get("/")
async def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "prompt-test.html"))

@app.get("/api/prompt-test/channels")
async def channels():
    return {'channels': ['블로그_제목','블로그_본문','카페SEO_제목','카페SEO_본문','카페SEO_댓글','지식인_질문제목','지식인_질문본문','지식인_답변','유튜브댓글','틱톡','커뮤니티','카페바이럴_일상글','카페바이럴_고민글','카페바이럴_침투글','쓰레드_일상글','쓰레드_물길글_셔플','쓰레드_물길글_연민','쓰레드_물길글_후기']}

@app.get("/api/prompt-test/get")
async def get_prompt(channel: str = ''):
    overrides = _load_overrides()
    if channel in overrides:
        return {'prompt': overrides[channel], 'is_override': True}
    default = _get_default_prompt(channel)
    if default:
        return {'prompt': default, 'is_override': False}
    return {'prompt': '(해당 채널의 프롬프트를 찾을 수 없습니다.)', 'is_override': False}

@app.post("/api/prompt-test/generate")
async def generate(request: Request):
    body = await request.json()
    system_prompt = body.get('system_prompt', '')
    keyword = body.get('keyword', '테스트')
    product = body.get('product', {})
    temperature = body.get('temperature', 0.7)
    if not system_prompt:
        return JSONResponse({'error': '프롬프트 필요'}, 400)
    user_prompt = f"키워드: {keyword}\n제품명: {product.get('name','')}\n나만의 키워드: {product.get('brand_keyword','')}\n핵심 특징: {product.get('usp','')}\n타겟층: {product.get('target','')}\n주요 성분: {product.get('ingredients','')}"
    result = _call_claude(system_prompt, user_prompt, temperature)
    return {'result': result, 'char_count': len(result)}

@app.post("/api/prompt-test/save")
async def save(request: Request):
    body = await request.json()
    channel = body.get('channel', '')
    prompt = body.get('prompt', '')
    if not channel or not prompt:
        return JSONResponse({'error': '채널과 프롬프트 필요'}, 400)
    overrides = _load_overrides()
    overrides[channel] = prompt
    _save_overrides(overrides)
    return {'ok': True}

@app.post("/api/prompt-test/reset")
async def reset(request: Request):
    body = await request.json()
    channel = body.get('channel', '')
    overrides = _load_overrides()
    if channel in overrides:
        del overrides[channel]
        _save_overrides(overrides)
    return {'ok': True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
