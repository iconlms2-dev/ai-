"""프롬프트 테스트 — 채널별 프롬프트 조회/수정/테스트 생성"""
import json
import os
import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.services.config import executor, BASE_DIR
from src.services.ai_client import call_claude

router = APIRouter()

PROMPT_OVERRIDES_FILE = os.path.join(BASE_DIR, "prompt_overrides.json")


# ── helpers ────────────────────────────────────────────────────────

def _prompt_load_overrides():
    if os.path.exists(PROMPT_OVERRIDES_FILE):
        try:
            with open(PROMPT_OVERRIDES_FILE, encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _prompt_save_overrides(data):
    with open(PROMPT_OVERRIDES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get_default_prompt(channel):
    """채널별 기본 시스템 프롬프트 반환"""
    # 각 채널 모듈에서 프롬프트 빌더를 lazy import
    dummy_product = {'name': '테스트제품', 'brand_keyword': '테스트키워드', 'usp': '핵심특징', 'target': '타겟층', 'ingredients': '성분'}

    if channel == '블로그_제목':
        from src.api.blog import _build_blog_title_prompt
        sys_p, _ = _build_blog_title_prompt('테스트', dummy_product)
        return sys_p
    elif channel == '블로그_본문':
        from src.api.blog import _build_blog_body_prompt
        sys_p, _ = _build_blog_body_prompt('테스트', '', dummy_product, 10, 5, '테스트 제목')
        return sys_p
    elif channel == '카페SEO_제목':
        from src.api.cafe import _build_cafe_title_prompt
        sys_p, _ = _build_cafe_title_prompt('테스트', '원본제목')
        return sys_p
    elif channel == '카페SEO_본문':
        from src.api.cafe import _build_cafe_body_prompt
        sys_p, _ = _build_cafe_body_prompt('테스트', '제목', '', {}, dummy_product)
        return sys_p
    elif channel == '카페SEO_댓글':
        from src.api.cafe import _build_cafe_comments_prompt
        sys_p, _ = _build_cafe_comments_prompt('테스트', '본문', '브랜드', '')
        return sys_p
    elif channel == '지식인_질문제목':
        from src.api.jisikin import _build_jisikin_title_prompt
        sys_p, _ = _build_jisikin_title_prompt('테스트', dummy_product)
        return sys_p
    elif channel == '지식인_질문본문':
        from src.api.jisikin import _build_jisikin_body_prompt
        sys_p, _ = _build_jisikin_body_prompt('테스트', dummy_product)
        return sys_p
    elif channel == '지식인_답변':
        from src.api.jisikin import _build_jisikin_answers_prompt
        sys_p, _ = _build_jisikin_answers_prompt('테스트', '질문제목', '질문본문', dummy_product)
        return sys_p
    elif channel == '틱톡':
        from src.api.tiktok import _build_tiktok_prompt
        sys_p, _ = _build_tiktok_prompt('테스트', '소구점', '구매원씽', dummy_product, '')
        return sys_p
    elif channel == '커뮤니티':
        from src.api.community import _build_community_post_prompt
        sys_p, _ = _build_community_post_prompt('뽐뿌', '1', '테스트', '소구점', '구매원씽', dummy_product, '')
        return sys_p
    elif channel == '쓰레드_일상글':
        from src.api.threads import _build_threads_daily_prompt
        sys_p, _ = _build_threads_daily_prompt({'name': '테스트', 'age': '30', 'job': '직장인', 'tone': '친근', 'interests': ['건강']}, [])
        return sys_p
    elif channel == '쓰레드_물길글_셔플':
        from src.api.threads import _build_threads_traffic_prompt
        sys_p, _ = _build_threads_traffic_prompt('테스트', {'tone': '친근', 'job': '직장인', 'interests': ['건강']}, dummy_product, '', 'shuffle')
        return sys_p
    elif channel == '쓰레드_물길글_연민':
        from src.api.threads import _build_threads_traffic_prompt
        sys_p, _ = _build_threads_traffic_prompt('테스트', {'tone': '친근'}, dummy_product, '', 'sympathy')
        return sys_p
    elif channel == '쓰레드_물길글_후기':
        from src.api.threads import _build_threads_traffic_prompt
        sys_p, _ = _build_threads_traffic_prompt('테스트', {'tone': '친근', 'job': '직장인', 'interests': ['건강']}, dummy_product, '', 'review')
        return sys_p
    elif channel == '유튜브댓글':
        from src.api.youtube import _build_youtube_comment_prompt
        sys_p, _ = _build_youtube_comment_prompt('테스트 영상', '더보기 내용', '테스트키워드')
        return sys_p
    elif channel == '카페바이럴_일상글':
        from src.api.viral import _build_viral_stage1_prompt
        sys_p, _ = _build_viral_stage1_prompt('타겟층', '타겟층', '일상 주제')
        return sys_p
    elif channel == '카페바이럴_고민글':
        from src.api.viral import _build_viral_stage2_prompt
        sys_p, _ = _build_viral_stage2_prompt('타겟층', '고민키워드', '건강기능식품')
        return sys_p
    elif channel == '카페바이럴_침투글':
        from src.api.viral import _build_viral_stage3_prompt
        sys_p, _ = _build_viral_stage3_prompt('타겟층', '고민키워드', '테스트키워드', '테스트제품', '핵심특징', '성분', '건강기능식품')
        return sys_p
    elif channel == '파워컨텐츠_광고소재':
        from src.api.powercontent import _build_pc_ad_prompt
        sys_p, _ = _build_pc_ad_prompt('테스트', '소구점', '구매원씽', dummy_product, '부정편향', '')
        return sys_p
    elif channel == '파워컨텐츠_본문':
        from src.api.powercontent import _build_pc_body_prompt
        sys_p, _ = _build_pc_body_prompt('테스트', '3_정보습득', '소구점', '구매원씽', '-4', dummy_product, '광고제목', '광고설명', '{}')
        return sys_p
    elif channel == '파워컨텐츠_분석':
        from src.api.powercontent import _build_pc_analysis_prompt
        sys_p, _ = _build_pc_analysis_prompt('레퍼런스 본문 텍스트')
        return sys_p
    return ''


def _get_full_prompt(channel):
    """채널별 시스템+유저 프롬프트 쌍 반환"""
    dummy_product = {'name': '테스트제품', 'brand_keyword': '테스트키워드', 'usp': '핵심특징', 'target': '타겟층', 'ingredients': '성분'}

    try:
        if channel == '블로그_제목':
            from src.api.blog import _build_blog_title_prompt
            return _build_blog_title_prompt('테스트', dummy_product)
        elif channel == '블로그_본문':
            from src.api.blog import _build_blog_body_prompt
            return _build_blog_body_prompt('테스트', '3_정보습득', dummy_product, 5, 4, '테스트 제목')
        elif channel == '카페SEO_제목':
            from src.api.cafe import _build_cafe_title_prompt
            return _build_cafe_title_prompt('테스트', '원본제목')
        elif channel == '카페SEO_본문':
            from src.api.cafe import _build_cafe_body_prompt
            return _build_cafe_body_prompt('테스트', '제목', '', {}, dummy_product)
        elif channel == '카페SEO_댓글':
            from src.api.cafe import _build_cafe_comments_prompt
            return _build_cafe_comments_prompt('테스트', '본문', '브랜드', '')
        elif channel == '지식인_질문제목':
            from src.api.jisikin import _build_jisikin_title_prompt
            return _build_jisikin_title_prompt('테스트', dummy_product)
        elif channel == '지식인_질문본문':
            from src.api.jisikin import _build_jisikin_body_prompt
            return _build_jisikin_body_prompt('테스트', dummy_product)
        elif channel == '지식인_답변':
            from src.api.jisikin import _build_jisikin_answers_prompt
            return _build_jisikin_answers_prompt('테스트', '질문제목', '질문본문', dummy_product)
        elif channel == '틱톡':
            from src.api.tiktok import _build_tiktok_prompt
            return _build_tiktok_prompt('테스트', '소구점', '구매원씽', dummy_product, '')
        elif channel == '커뮤니티':
            from src.api.community import _build_community_post_prompt
            return _build_community_post_prompt('뽐뿌', '1', '테스트', '소구점', '구매원씽', dummy_product, '')
        elif channel == '쓰레드_일상글':
            from src.api.threads import _build_threads_daily_prompt
            return _build_threads_daily_prompt({'name': '테스트', 'age': '30', 'job': '직장인', 'tone': '친근', 'interests': ['건강']}, [])
        elif channel == '쓰레드_물길글_셔플':
            from src.api.threads import _build_threads_traffic_prompt
            return _build_threads_traffic_prompt('테스트', {'tone': '친근', 'job': '직장인', 'interests': ['건강']}, dummy_product, '', 'shuffle')
        elif channel == '쓰레드_물길글_연민':
            from src.api.threads import _build_threads_traffic_prompt
            return _build_threads_traffic_prompt('테스트', {'tone': '친근'}, dummy_product, '', 'sympathy')
        elif channel == '쓰레드_물길글_후기':
            from src.api.threads import _build_threads_traffic_prompt
            return _build_threads_traffic_prompt('테스트', {'tone': '친근', 'job': '직장인', 'interests': ['건강']}, dummy_product, '', 'review')
        elif channel == '유튜브댓글':
            from src.api.youtube import _build_youtube_comment_prompt
            return _build_youtube_comment_prompt('테스트 영상', '더보기 내용', '테스트키워드')
        elif channel == '카페바이럴_일상글':
            from src.api.viral import _build_viral_stage1_prompt
            return _build_viral_stage1_prompt('타겟층', '타겟층', '일상 주제')
        elif channel == '카페바이럴_고민글':
            from src.api.viral import _build_viral_stage2_prompt
            return _build_viral_stage2_prompt('타겟층', '고민키워드', '건강기능식품')
        elif channel == '카페바이럴_침투글':
            from src.api.viral import _build_viral_stage3_prompt
            return _build_viral_stage3_prompt('타겟층', '고민키워드', '테스트키워드', '테스트제품', '핵심특징', '성분', '건강기능식품')
        elif channel == '카페SEO_답글':
            from src.api.cafe import _build_cafe_replies_prompt
            return _build_cafe_replies_prompt('테스트', '본문 텍스트', '댓글 텍스트', '브랜드키워드')
        elif channel == '카페SEO_Polish':
            from src.api.cafe import _build_cafe_polish_prompt
            return _build_cafe_polish_prompt('테스트', '제목', '본문', '댓글', '브랜드키워드', '병원,가격')
        elif channel == '파워컨텐츠_광고소재':
            from src.api.powercontent import _build_pc_ad_prompt
            return _build_pc_ad_prompt('테스트', '소구점', '구매원씽', dummy_product, '부정편향', '')
        elif channel == '파워컨텐츠_본문':
            from src.api.powercontent import _build_pc_body_prompt
            return _build_pc_body_prompt('테스트', '3_정보습득', '소구점', '구매원씽', '-4', dummy_product, '광고제목', '광고설명', '{}')
        elif channel == '파워컨텐츠_분석':
            from src.api.powercontent import _build_pc_analysis_prompt
            return _build_pc_analysis_prompt('레퍼런스 본문 텍스트')
    except Exception as e:
        raise e
    return '', ''


# ── endpoints ──────────────────────────────────────────────────────

@router.get("/channels")
async def prompt_test_channels():
    """테스트 가능한 채널 목록"""
    channels = [
        '블로그_제목', '블로그_본문',
        '카페SEO_제목', '카페SEO_본문', '카페SEO_댓글', '카페SEO_답글', '카페SEO_Polish',
        '지식인_질문제목', '지식인_질문본문', '지식인_답변',
        '유튜브댓글', '틱톡', '커뮤니티',
        '카페바이럴_일상글', '카페바이럴_고민글', '카페바이럴_침투글',
        '파워컨텐츠_광고소재', '파워컨텐츠_본문', '파워컨텐츠_분석',
        '쓰레드_일상글', '쓰레드_물길글_셔플', '쓰레드_물길글_연민', '쓰레드_물길글_후기',
    ]
    return {'channels': channels}


@router.get("/get")
async def prompt_test_get(channel: str = ''):
    """채널의 현재 프롬프트 반환 (오버라이드 있으면 오버라이드, 없으면 기본)"""
    overrides = _prompt_load_overrides()
    if channel in overrides:
        return {'prompt': overrides[channel], 'is_override': True}
    default = _get_default_prompt(channel)
    return {'prompt': default, 'is_override': False}


@router.get("/get-full")
async def prompt_test_get_full(channel: str = ''):
    """채널의 시스템+유저 프롬프트 쌍 반환"""
    if not channel:
        return JSONResponse({'error': '채널 필요'}, 400)
    try:
        overrides = _prompt_load_overrides()
        sys_p, user_p = _get_full_prompt(channel)
        if not sys_p and not user_p:
            return JSONResponse({'error': f'알 수 없는 채널: {channel}'}, 404)
        if channel in overrides:
            sys_p = overrides[channel]
        return {'system_prompt': sys_p, 'user_prompt': user_p, 'is_override': channel in overrides}
    except Exception as e:
        return JSONResponse({'error': f'프롬프트 로드 실패: {e}'}, 500)


@router.post("/generate")
async def prompt_test_generate(request: Request):
    """커스텀 프롬프트로 테스트 생성"""
    body = await request.json()
    system_prompt = body.get('system_prompt', '')
    keyword = body.get('keyword', '테스트')
    product = body.get('product', {})
    temperature = body.get('temperature', 0.7)
    if not system_prompt:
        return JSONResponse({'error': '시스템 프롬프트 필요'}, 400)

    # user 프롬프트 구성
    user_prompt = f"키워드: {keyword}\n제품명: {product.get('name','')}\n나만의 키워드: {product.get('brand_keyword','')}\n핵심 특징: {product.get('usp','')}\n타겟층: {product.get('target','')}\n주요 성분: {product.get('ingredients','')}"

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, call_claude, system_prompt, user_prompt, temperature)
    return {'result': result, 'char_count': len(result)}


@router.post("/save")
async def prompt_test_save(request: Request):
    """수정된 프롬프트를 오버라이드로 저장"""
    body = await request.json()
    channel = body.get('channel', '')
    prompt = body.get('prompt', '')
    if not channel or not prompt:
        return JSONResponse({'error': '채널과 프롬프트 필요'}, 400)
    overrides = _prompt_load_overrides()
    overrides[channel] = prompt
    _prompt_save_overrides(overrides)
    return {'ok': True, 'channel': channel}


@router.post("/reset")
async def prompt_test_reset(request: Request):
    """오버라이드 삭제 (기본 프롬프트로 복원)"""
    body = await request.json()
    channel = body.get('channel', '')
    overrides = _prompt_load_overrides()
    if channel in overrides:
        del overrides[channel]
        _prompt_save_overrides(overrides)
    return {'ok': True}
