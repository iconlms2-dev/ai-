"""숏츠 제작 — 주제·대본·훅·TTS·자막"""
import os
import re
import json
import asyncio
import base64
from datetime import datetime

import requests as req
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse

from src.services.config import executor, ELEVENLABS_API_KEY, SHORTS_DIR
from src.services.ai_client import call_claude

router = APIRouter()


# ── helpers ──────────────────────────────────────────────────────────

def _build_shorts_topics_prompt(material, content_type):
    """숏츠 주제 5개 제안 프롬프트"""
    style_guide = ""
    if content_type == "썰형":
        style_guide = """'썰형' 스타일:
1. 강력한 훅 (갈등/좌절): 이혼, 이별, 자존감 바닥, 관계 파탄 등 인생 최악의 순간을 제시.
2. 감정적 고통 (상황 묘사): 상대방의 경멸, 무시, 혹은 자신의 비참함을 구체적으로 묘사.
3. 탐색 (절박함): '이대로 살 수 없다'는 절박함으로 방법을 찾기 시작.
4. 발견 (사회적 증거): 리뷰, 후기 등 신뢰할 만한 근거를 보고 제품을 알게 됨.
5. 극적인 반전 (결과): 상상 이상으로 과장되고 극적인 결과.
6. 행동 유도 (CTA): 명확한 검색/터치 지시."""
    else:
        style_guide = """'정보형' 스타일:
- 잘못된 상식 지적, 전문가 비밀 폭로, 자가 진단 체크리스트 등
- 정보가치가 높아 자연스럽게 시청하게 되는 구조
- 권위/데이터를 활용한 신뢰 확보"""

    system = f"""너는 숏츠 영상 대본을 전문적으로 작성하는 마케팅 어시스턴트다.

[기본 재료]
- 제품명: {material.get('product', '')}
- 타겟 고객: {material.get('target', '')}
- 타겟의 핵심 문제: {material.get('problem', '')}
- 문제가 유발하는 감정: {material.get('emotion', '')}
- 신뢰 근거: {material.get('trust', '')}
- CTA: {material.get('cta', '')}

[유형: {content_type}]
{style_guide}

임무: 위 기본 재료를 활용하여 '{content_type}' 유형에 맞는 창의적이고 매력적인 주제(앵글) 5가지를 새롭게 창작하여 제안하라.
각 주제가 왜 타겟에게 매력적일지 1줄 요약 이유를 포함해야 한다.

출력 형식 (정확히 따를 것):
1. [주제 제목] — [매력 포인트 1줄]
2. [주제 제목] — [매력 포인트 1줄]
3. [주제 제목] — [매력 포인트 1줄]
4. [주제 제목] — [매력 포인트 1줄]
5. [주제 제목] — [매력 포인트 1줄]"""

    return system, f"'{content_type}' 유형으로 주제 5가지를 제안해줘."


def _build_shorts_script_prompt(material, content_type, topic, length):
    """숏츠 대본 생성 프롬프트"""
    style_guide = ""
    if content_type == "썰형":
        style_guide = """[핵심 공식]
1. 강력한 훅 (갈등/좌절): 이혼, 이별, 자존감 바닥, 관계 파탄 등 인생 최악의 순간을 제시.
2. 감정적 고통 (상황 묘사): 상대방의 경멸, 무시, 혹은 자신의 비참함을 구체적으로 묘사. (예: 눈도 안 마주침, 도망침, 우울증)
3. 탐색 (절박함): '이대로 살 수 없다', '너무 창피하다'는 절박함으로 방법을 찾기 시작.
4. 발견 (사회적 증거): 리뷰, 틱톡 후기 등 신뢰할 만한 근거를 보고 제품을 알게 됨.
5. 극적인 반전 (결과): 상상 이상으로 과장되고 극적인 결과. (예: 구체적 숫자 곁들이기)
6. 행동 유도 (CTA): 명확한 지시.
7. 말투는 ~네요. ~다. ~고요 등으로 화자가 직접 이야기를 전달하는 형태. ('' 대사표현 금지)"""
    else:
        style_guide = """[핵심 공식]
초반 3초 - 결핍 강조 또는 잘못된 상식 지적
정보 제공 → 한계 제시
제품 소개 + 권위 부여 + 효과 제시 (구체적 숫자 곁들이기)
CTA"""

    system = f"""너는 숏츠 영상 대본을 전문적으로 작성하는 마케팅 어시스턴트다.

[기본 재료]
- 제품명: {material.get('product', '')}
- 타겟 고객: {material.get('target', '')}
- 타겟의 핵심 문제: {material.get('problem', '')}
- 문제가 유발하는 감정: {material.get('emotion', '')}
- 신뢰 근거: {material.get('trust', '')}
- CTA: {material.get('cta', '')}

[유형: {content_type}]
{style_guide}

작성 규칙:
- 약 {length}자 분량의 숏츠 대본을 작성한다.
- 이 대본은 그대로 TTS 음성으로 읽히므로, 읽었을 때 자연스러워야 한다.
- 이모지, 해시태그, 특수기호 사용 금지 (TTS가 읽을 수 없음)
- [연출], [자막], [장면] 같은 메타 표기 금지 — 순수 나레이션 텍스트만 출력
- 문장은 짧게 끊어서. 줄바꿈으로 문장을 구분.

주의사항: 대본 출력시 오로지 대본 내용만 출력. 다른 설명 없이."""

    return system, f"다음 주제로 대본을 작성해줘: {topic}"


def _build_shorts_hooks_prompt():
    """썸네일 훅(제목) 생성 프롬프트"""
    return """당신은 칩 히스의 '스틱(Stick!)' 원칙과 '자청' 스타일의 욕망/결핍 기반 카피라이팅 원칙을 모두 마스터한, 숏폼 비디오 전문 바이럴 마케터입니다.
당신의 임무는 초반 2초 이탈률을 0%에 가깝게 만드는 '스크롤 스토퍼(Scroll-stopper)' 훅(제목)을 생성하는 것입니다.

# 작업 프로세스
1. 1단계 (분석): 스크립트를 읽고, [핵심 메시지], [핵심 타겟 고객], [타겟의 결핍 또는 욕망]을 내부적으로 정의합니다.
2. 2단계 (생성): 아래 7가지 원칙을 창의적으로 조합하여 훅(제목) 카피 10개를 생성합니다.

# 생성 원칙 (스틱! + 자청 결합)
1. 단순성 (Simple): 핵심을 하나의 강력하고 짧은 문장으로 압축.
2. 의외성 (Unexpected): 타겟의 통념이나 예상을 깨뜨림. (예: "OOO, 사기였습니다.")
3. 구체성 (Concrete): 감각적이고 구체적인 단어, 숫자, 고유명사 사용.
4. 권위/신뢰 (Authority): 전문가, 데이터, 연구 결과를 암시.
5. 스토리 (Story): 극적인 변화나 경험을 암시.
6. 금지/위협 (Prohibition): 손실 회피 심리 자극. "하지 마라", "이거 모르면 손해".
7. 자아 흠집 (Ego Scratch): 자존심, 우월감, 불안감을 건드림.

# 산출물
- 2~3초 이내 인지 가능한 매우 짧고 간결한 훅 카피 10개
- 각 카피 뒤에 사용한 핵심 원칙을 괄호 안에 명시 (예: (의외성, 구체성))
- 번호를 매겨 출력"""


def _elevenlabs_tts_with_timestamps(text, voice_id, model_id="eleven_multilingual_v2"):
    """ElevenLabs TTS 호출 — 음성 + 캐릭터별 타임스탬프 반환"""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    r = req.post(url, headers=headers, json=payload, timeout=120)
    if r.status_code != 200:
        raise Exception(f"ElevenLabs API 에러 ({r.status_code}): {r.text[:300]}")
    return r.json()


def _generate_srt_from_alignment(text, alignment, words_per_segment=3):
    """캐릭터 타임스탬프로부터 SRT 자막 파일 생성"""
    chars = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])

    words = []
    current_word = ""
    word_start = None
    word_end = None
    for i, ch in enumerate(chars):
        if ch.strip() == "" or ch in ("\n", "\r"):
            if current_word:
                words.append({"text": current_word, "start": word_start, "end": word_end})
                current_word = ""
                word_start = None
        else:
            if word_start is None:
                word_start = starts[i] if i < len(starts) else 0
            word_end = ends[i] if i < len(ends) else word_start
            current_word += ch
    if current_word:
        words.append({"text": current_word, "start": word_start, "end": word_end})

    segments = []
    for i in range(0, len(words), words_per_segment):
        group = words[i:i + words_per_segment]
        seg_text = " ".join(w["text"] for w in group)
        seg_start = group[0]["start"]
        seg_end = group[-1]["end"]
        segments.append({"start": seg_start, "end": seg_end, "text": seg_text})

    def _fmt_time(sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int((sec - int(sec)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    srt_lines = []
    for idx, seg in enumerate(segments, 1):
        srt_lines.append(str(idx))
        srt_lines.append(f"{_fmt_time(seg['start'])} --> {_fmt_time(seg['end'])}")
        srt_lines.append(seg["text"])
        srt_lines.append("")

    return "\n".join(srt_lines)


# ── endpoints ────────────────────────────────────────────────────────

@router.get("/voices")
async def shorts_voices():
    """ElevenLabs 사용 가능한 음성 목록"""
    if not ELEVENLABS_API_KEY:
        return JSONResponse({"error": "ELEVENLABS_API_KEY가 설정되지 않았습니다"}, 400)
    try:
        r = req.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": ELEVENLABS_API_KEY}, timeout=15)
        if r.status_code != 200:
            return JSONResponse({"error": f"API 에러: {r.status_code}"}, 500)
        voices = []
        for v in r.json().get("voices", []):
            voices.append({
                "voice_id": v["voice_id"],
                "name": v["name"],
                "category": v.get("category", ""),
                "labels": v.get("labels", {}),
                "preview_url": v.get("preview_url", ""),
            })
        return {"voices": voices}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


@router.post("/topics")
async def shorts_topics(request: Request):
    """숏츠 주제 5개 제안"""
    body = await request.json()
    material = body.get("material", {})
    content_type = body.get("type", "썰형")

    def _sse(obj):
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        yield _sse({"type": "progress", "msg": "주제 생성 중..."})
        sys_p, usr_p = _build_shorts_topics_prompt(material, content_type)
        result = await loop.run_in_executor(executor, call_claude, sys_p, usr_p)
        result = result.strip()
        if result.startswith("[ERROR]"):
            yield _sse({"type": "error", "message": result})
            return
        yield _sse({"type": "topics", "text": result})
        yield _sse({"type": "complete"})
      except Exception as e:
        print(f"[shorts_topics] 에러: {e}")
        yield _sse({"type": "error", "message": f"주제 생성 중 오류: {e}"})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/script")
async def shorts_script(request: Request):
    """숏츠 대본 생성"""
    body = await request.json()
    material = body.get("material", {})
    content_type = body.get("type", "썰형")
    topic = body.get("topic", "")
    length = body.get("length", 600)

    def _sse(obj):
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        yield _sse({"type": "progress", "msg": "대본 생성 중..."})
        sys_p, usr_p = _build_shorts_script_prompt(material, content_type, topic, length)
        result = await loop.run_in_executor(executor, call_claude, sys_p, usr_p)
        result = result.strip()
        if result.startswith("[ERROR]"):
            yield _sse({"type": "error", "message": result})
            return
        yield _sse({"type": "script", "text": result})
        yield _sse({"type": "complete"})
      except Exception as e:
        print(f"[shorts_script] 에러: {e}")
        yield _sse({"type": "error", "message": f"대본 생성 중 오류: {e}"})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/hooks")
async def shorts_hooks(request: Request):
    """썸네일 훅(제목) 10개 생성"""
    body = await request.json()
    script = body.get("script", "")

    def _sse(obj):
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        yield _sse({"type": "progress", "msg": "썸네일 훅 생성 중..."})
        sys_p = _build_shorts_hooks_prompt()
        usr_p = f"[스크립트 전문]\n{script}"
        result = await loop.run_in_executor(executor, call_claude, sys_p, usr_p)
        result = result.strip()
        if result.startswith("[ERROR]"):
            yield _sse({"type": "error", "message": result})
            return
        yield _sse({"type": "hooks", "text": result})
        yield _sse({"type": "complete"})
      except Exception as e:
        print(f"[shorts_hooks] 에러: {e}")
        yield _sse({"type": "error", "message": f"훅 생성 중 오류: {e}"})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/tts")
async def shorts_tts(request: Request):
    """TTS 음성 + SRT 자막 생성"""
    body = await request.json()
    script = body.get("script", "")
    voice_id = body.get("voice_id", "")
    words_per_seg = body.get("words_per_segment", 3)

    if not script:
        return JSONResponse({"error": "대본이 없습니다"}, 400)
    if not voice_id:
        return JSONResponse({"error": "음성을 선택하세요"}, 400)

    def _sse(obj):
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    async def generate():
      try:
        loop = asyncio.get_running_loop()

        yield _sse({"type": "progress", "msg": "음성 생성 중 (ElevenLabs)..."})
        tts_result = await loop.run_in_executor(
            executor, _elevenlabs_tts_with_timestamps, script, voice_id
        )

        audio_b64 = tts_result.get("audio_base64", "")
        if not audio_b64:
            yield _sse({"type": "error", "message": "음성 생성 실패: 오디오 데이터 없음"})
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_filename = f"shorts_{ts}.mp3"
        audio_path = os.path.join(SHORTS_DIR, audio_filename)
        with open(audio_path, "wb") as f:
            f.write(base64.b64decode(audio_b64))

        yield _sse({"type": "progress", "msg": "자막(SRT) 생성 중..."})
        alignment = tts_result.get("alignment", {})
        srt_content = _generate_srt_from_alignment(script, alignment, words_per_seg)
        srt_filename = f"shorts_{ts}.srt"
        srt_path = os.path.join(SHORTS_DIR, srt_filename)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        txt_filename = f"shorts_{ts}.txt"
        txt_path = os.path.join(SHORTS_DIR, txt_filename)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(script)

        yield _sse({
            "type": "complete",
            "audio_url": f"/api/shorts/download/{audio_filename}",
            "srt_url": f"/api/shorts/download/{srt_filename}",
            "txt_url": f"/api/shorts/download/{txt_filename}",
            "srt_preview": srt_content[:500],
        })

      except Exception as e:
        print(f"[shorts_tts] 에러: {e}")
        yield _sse({"type": "error", "message": f"TTS 생성 중 오류: {e}"})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/download/{filename}")
async def shorts_download(filename: str):
    """생성된 숏츠 파일 다운로드"""
    safe_name = os.path.basename(filename)
    if not re.match(r'^[\w\-.]+$', safe_name):
        return JSONResponse({"error": "invalid filename"}, status_code=400)
    fpath = os.path.join(SHORTS_DIR, safe_name)
    if not os.path.exists(fpath):
        return JSONResponse({"error": "파일을 찾을 수 없습니다"}, 404)
    media_types = {".mp3": "audio/mpeg", ".srt": "text/srt", ".txt": "text/plain"}
    ext = os.path.splitext(safe_name)[1]
    return FileResponse(fpath, filename=safe_name, media_type=media_types.get(ext, "application/octet-stream"))
