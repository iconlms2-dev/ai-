"""AI API 클라이언트 — Claude, Gemini 멀티 LLM 라우팅"""
import json
import time
import os
import threading
from datetime import datetime

import requests as req

from src.services.config import ANTHROPIC_API_KEY, GEMINI_API_KEY, API_USAGE_FILE

_usage_lock = threading.Lock()

PRICING = {
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
}

# ── 용도별 LLM 라우팅 설정 ──
# channel 파라미터 또는 명시적 purpose로 최적 모델 자동 선택
LLM_ROUTING = {
    "content_generation": "claude",   # 콘텐츠 집필 — 품질 최우선
    "review": "gemini",               # AI 검수 — 저가
    "analysis": "gemini",             # 벤치마킹/분석 — 저가+빠름
    "benchmark": "gemini",            # 키워드/접점 분석
    "image_prompt": "gemini",         # 이미지 프롬프트 생성
}


def track_usage(model, input_tokens, output_tokens, channel="unknown"):
    """API 사용량을 파일에 기록."""
    try:
        with _usage_lock:
            if os.path.exists(API_USAGE_FILE):
                with open(API_USAGE_FILE, "r") as f:
                    usage = json.load(f)
            else:
                usage = {"records": []}

            pricing = PRICING.get(model, {"input": 3.0, "output": 15.0})
            cost = (input_tokens / 1_000_000 * pricing["input"]) + (output_tokens / 1_000_000 * pricing["output"])

            usage["records"].append({
                "timestamp": datetime.now().isoformat(),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(cost, 6),
                "channel": channel,
            })

            with open(API_USAGE_FILE, "w") as f:
                json.dump(usage, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Usage tracking] 기록 실패: {e}")


def call_claude(system_prompt, user_prompt, temperature=None, max_tokens=4096, channel="unknown"):
    """Claude API 호출 (비스트리밍). temperature: 0.0~1.0 (None이면 기본값). 429/5xx 시 최대 3회 재시도."""
    if not ANTHROPIC_API_KEY:
        return '[ERROR] ANTHROPIC_API_KEY가 설정되지 않았습니다.'
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
    }
    model = 'claude-sonnet-4-20250514'
    payload = {
        'model': model,
        'max_tokens': max_tokens,
        'system': system_prompt,
        'messages': [{'role': 'user', 'content': user_prompt}],
    }
    if temperature is not None:
        payload['temperature'] = temperature
    max_retries = 3
    for attempt in range(max_retries):
        try:
            r = req.post('https://api.anthropic.com/v1/messages', headers=headers, json=payload, timeout=60)
            if r.status_code == 200:
                data = r.json()
                usage = data.get('usage', {})
                track_usage(model, usage.get('input_tokens', 0), usage.get('output_tokens', 0), channel)
                if data.get('content') and len(data['content']) > 0:
                    return data['content'][0]['text']
                return '[ERROR] Claude API 빈 응답'
            if r.status_code == 429 or r.status_code >= 500:
                wait = min(2 ** attempt * 5, 30)
                print(f"[Claude API] {r.status_code} 재시도 {attempt+1}/{max_retries} ({wait}초 대기)")
                time.sleep(wait)
                continue
            return f'[ERROR] Claude API {r.status_code}: {r.text[:300]}'
        except req.exceptions.Timeout:
            if attempt < max_retries - 1:
                print(f"[Claude API] 타임아웃 재시도 {attempt+1}/{max_retries}")
                time.sleep(3)
                continue
            return '[ERROR] Claude API 타임아웃 (60초 초과)'
        except Exception as e:
            return f'[ERROR] Claude API 호출 실패: {e}'
    return '[ERROR] Claude API 최대 재시도 횟수 초과'


def call_gemini(system_prompt, user_prompt, temperature=0.3, max_tokens=4096, channel="unknown"):
    """Gemini API 호출. 저가 모델로 분석/검수/보조 작업용. 429/5xx 시 최대 3회 재시도."""
    if not GEMINI_API_KEY:
        return '[ERROR] GEMINI_API_KEY가 설정되지 않았습니다.'

    model = "gemini-2.0-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"

    # Gemini는 system instruction + user content 분리
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            r = req.post(url, json=payload, timeout=60)
            if r.status_code == 200:
                data = r.json()
                candidates = data.get("candidates", [])
                if not candidates or "content" not in candidates[0]:
                    return "[ERROR] Gemini API 응답 차단 (safety filter 또는 빈 응답)"
                text = candidates[0]["content"]["parts"][0]["text"]
                # Gemini 토큰 추적 (usageMetadata)
                usage_meta = data.get("usageMetadata", {})
                input_tokens = usage_meta.get("promptTokenCount", 0)
                output_tokens = usage_meta.get("candidatesTokenCount", 0)
                track_usage(model, input_tokens, output_tokens, channel)
                return text
            if r.status_code == 429 or r.status_code >= 500:
                wait = min(2 ** attempt * 5, 30)
                print(f"[Gemini API] {r.status_code} 재시도 {attempt+1}/{max_retries} ({wait}초 대기)")
                time.sleep(wait)
                continue
            return f'[ERROR] Gemini API {r.status_code}: {r.text[:300]}'
        except req.exceptions.Timeout:
            if attempt < max_retries - 1:
                print(f"[Gemini API] 타임아웃 재시도 {attempt+1}/{max_retries}")
                time.sleep(3)
                continue
            return '[ERROR] Gemini API 타임아웃 (60초 초과)'
        except Exception as e:
            return f'[ERROR] Gemini API 호출 실패: {e}'
    return '[ERROR] Gemini API 최대 재시도 횟수 초과'


def call_llm(system_prompt, user_prompt, purpose="content_generation",
             temperature=None, max_tokens=4096, channel="unknown",
             provider=None):
    """통합 LLM 호출. purpose 또는 provider로 모델 자동 선택 + Claude 실패 시 Gemini fallback.

    Args:
        purpose: LLM_ROUTING 키 (content_generation, review, analysis, benchmark, image_prompt)
        provider: 직접 지정 ("claude" 또는 "gemini"). 지정 시 purpose 무시.
    """
    target = provider or LLM_ROUTING.get(purpose, "claude")

    if target == "gemini":
        result = call_gemini(system_prompt, user_prompt,
                             temperature=temperature if temperature is not None else 0.3,
                             max_tokens=max_tokens, channel=channel)
        # Gemini 실패 시 Claude fallback
        if isinstance(result, str) and result.startswith("[ERROR]"):
            print(f"[LLM Router] Gemini 실패 → Claude fallback: {result[:80]}")
            return call_claude(system_prompt, user_prompt,
                               temperature=temperature, max_tokens=max_tokens, channel=channel)
        return result

    # Claude (기본)
    result = call_claude(system_prompt, user_prompt,
                         temperature=temperature, max_tokens=max_tokens, channel=channel)
    # Claude 실패 시 Gemini fallback
    if isinstance(result, str) and result.startswith("[ERROR]"):
        print(f"[LLM Router] Claude 실패 → Gemini fallback: {result[:80]}")
        return call_gemini(system_prompt, user_prompt,
                           temperature=temperature if temperature is not None else 0.3,
                           max_tokens=max_tokens, channel=channel)
    return result
