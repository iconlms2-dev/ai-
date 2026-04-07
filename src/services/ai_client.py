"""AI API 클라이언트 — Claude, Gemini"""
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
