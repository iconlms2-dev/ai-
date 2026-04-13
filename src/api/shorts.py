"""숏츠 제작 — 주제·대본·훅·TTS·자막"""
import os
import re
import json
import asyncio
import base64
from datetime import datetime

import requests as req
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, FileResponse

from src.services.config import executor, ELEVENLABS_API_KEY, SHORTS_DIR
from src.services.sse_helper import sse_dict, SSEResponse
from src.services.ai_client import call_claude
from src.services.review_service import review_and_save
from src.pipeline_v2.workflow import WorkflowConfig
from src.pipeline_v2.shorts import ShortsPipeline

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

    _sse = sse_dict

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

    return SSEResponse(generate())


@router.post("/script")
async def shorts_script(request: Request):
    """숏츠 대본 생성"""
    body = await request.json()
    material = body.get("material", {})
    content_type = body.get("type", "썰형")
    topic = body.get("topic", "")
    length = body.get("length", 600)

    _sse = sse_dict

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
        # ── 검수 단계 ──
        yield _sse({"type": "progress", "msg": "대본 검수 중..."})
        review_result = await loop.run_in_executor(
            executor, review_and_save, "shorts", {"script": result}, "",
        )
        for ev in review_result.get("events", []):
            yield _sse(ev)

        yield _sse({"type": "script", "text": result, "review_status": review_result["status"], "review_passed": review_result["passed"]})
        yield _sse({"type": "complete"})
      except Exception as e:
        print(f"[shorts_script] 에러: {e}")
        yield _sse({"type": "error", "message": f"대본 생성 중 오류: {e}"})

    return SSEResponse(generate())


@router.post("/hooks")
async def shorts_hooks(request: Request):
    """썸네일 훅(제목) 10개 생성"""
    body = await request.json()
    script = body.get("script", "")

    _sse = sse_dict

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

    return SSEResponse(generate())


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

    _sse = sse_dict

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

        # Google Drive 업로드
        drive_result = {}
        try:
            from src.services.google_drive import is_configured, upload_shorts_files
            if is_configured():
                yield _sse({"type": "progress", "msg": "Google Drive 업로드 중..."})
                drive_result = await loop.run_in_executor(
                    executor, upload_shorts_files, audio_path, srt_path, txt_path, True
                )
        except Exception as e:
            print(f"[shorts_tts] Drive 업로드 실패 (로컬 파일 유지): {e}")

        complete_data = {
            "type": "complete",
            "audio_url": f"/api/shorts/download/{audio_filename}",
            "srt_url": f"/api/shorts/download/{srt_filename}",
            "txt_url": f"/api/shorts/download/{txt_filename}",
            "srt_preview": srt_content[:500],
        }
        if drive_result:
            complete_data["drive"] = drive_result
            if drive_result.get("audio", {}).get("url"):
                complete_data["drive_audio_url"] = drive_result["audio"]["url"]
            if drive_result.get("srt", {}).get("url"):
                complete_data["drive_srt_url"] = drive_result["srt"]["url"]
            if drive_result.get("txt", {}).get("url"):
                complete_data["drive_txt_url"] = drive_result["txt"]["url"]

        yield _sse(complete_data)

      except Exception as e:
        print(f"[shorts_tts] 에러: {e}")
        yield _sse({"type": "error", "message": f"TTS 생성 중 오류: {e}"})

    return SSEResponse(generate())


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


# ── 풀 자동화 파이프라인 엔드포인트 ──────────────────────────

@router.post("/run-pipeline")
async def shorts_run_pipeline(request: Request):
    """숏츠 풀 자동화 파이프라인 실행 (대시보드/API용).

    body: {material, mode, benchmark_urls, voice_id, type, length}
    SSE로 단계별 진행상황 스트림.
    """
    body = await request.json()
    material = body.get("material", {})
    mode = body.get("mode", "auto")
    benchmark_urls = body.get("benchmark_urls", [])
    voice_id = body.get("voice_id", "")
    content_type = body.get("type", "썰형")
    length = body.get("length", 600)

    _sse = sse_dict

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        yield _sse({"type": "progress", "step": "init", "msg": "파이프라인 초기화..."})

        # argparse.Namespace 모방
        class Args:
            pass
        args = Args()
        args.product = material.get("product", "")
        args.target = material.get("target", "")
        args.problem = material.get("problem", "")
        args.emotion = material.get("emotion", "")
        args.trust = material.get("trust", "")
        args.cta = material.get("cta", "")
        args.type = content_type
        args.length = length
        args.mode = mode
        args.urls = benchmark_urls
        args.voice_id = voice_id
        args.resume = False

        workflow = WorkflowConfig(
            mode=mode,
            voice_id=voice_id,
            benchmark_urls=benchmark_urls,
        )

        def _run():
            pipeline = ShortsPipeline(workflow=workflow)
            return pipeline.run(args)

        yield _sse({"type": "progress", "step": "running", "msg": "파이프라인 실행 중..."})
        project = await loop.run_in_executor(executor, _run)

        # 결과 수집
        script = project.load_step_file("04_script", "script.json") or {}
        review = project.load_step_file("05_review", "review.json") or {}
        audio_meta = project.load_step_file("06_audio", "audio_meta.json") or {}
        edit_meta = project.load_step_file("08_edit", "edit_meta.json") or {}
        upload = project.load_step_file("09_upload", "upload.json") or {}

        yield _sse({
            "type": "result",
            "project_id": project.project_id,
            "project_dir": project.root,
            "script_chars": script.get("char_count", 0),
            "review_score": review.get("score", 0),
            "review_passed": review.get("pass", False),
            "duration": audio_meta.get("duration", 0),
            "scene_count": edit_meta.get("scene_count", 0),
            "youtube_url": upload.get("url", ""),
            "status": project.get("status"),
        })
        yield _sse({"type": "complete"})

      except Exception as e:
        print(f"[shorts_run_pipeline] 에러: {e}")
        yield _sse({"type": "error", "message": f"파이프라인 오류: {e}"})

    return SSEResponse(generate())


@router.post("/brief")
async def shorts_brief(request: Request):
    """상세 기획서 생성"""
    body = await request.json()
    material = body.get("material", {})
    concept = body.get("concept", {})
    content_type = body.get("content_type", "썰형")
    patterns = body.get("patterns", {})

    _sse = sse_dict

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        yield _sse({"type": "progress", "msg": "기획서 생성 중..."})

        pattern_section = ""
        if patterns and not patterns.get("skipped"):
            hooks = patterns.get("common_hooks", [])
            if hooks:
                pattern_section = f"\n\n벤치마킹에서 발견된 성공 훅 패턴:\n" + "\n".join(f"- {h}" for h in hooks[:5])

        sys_p = f"""너는 숏츠 영상 기획 전문가다.

주어진 컨셉과 소재를 바탕으로 상세 기획서를 작성하라.
기획서에는 다음이 포함되어야 한다:
- 주제 및 핵심 메시지
- 타겟 감정선 (시청 전→시청 후)
- 구조 (훅→공감→전환→증거→결과→CTA)
- 각 파트별 핵심 포인트
- 톤앤매너 가이드{pattern_section}"""

        usr_p = f"""컨셉: {concept.get('topic', '')}
매력: {concept.get('appeal', '')}
유형: {content_type}
제품: {material.get('product', '')}
타겟: {material.get('target', '')}
문제: {material.get('problem', '')}
감정: {material.get('emotion', '')}
신뢰근거: {material.get('trust', '')}
CTA: {material.get('cta', '')}"""

        result = await loop.run_in_executor(executor, call_claude, sys_p, usr_p)
        result = result.strip()

        yield _sse({"type": "brief", "text": result})
        yield _sse({"type": "complete"})
      except Exception as e:
        yield _sse({"type": "error", "message": str(e)})

    return SSEResponse(generate())


@router.post("/analyze-refs")
async def shorts_analyze_refs(request: Request):
    """레퍼런스 영상 AI 분석"""
    body = await request.json()
    references_text = body.get("references_text", "")

    _sse = sse_dict

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        yield _sse({"type": "progress", "msg": "레퍼런스 분석 중..."})

        sys_p = """너는 숏츠 영상 분석 전문가다.
주어진 레퍼런스 영상들을 분석하여 다음을 JSON으로 출력하라:
{
  "success_factors": ["성공 요인 1", "성공 요인 2", ...],
  "hook_patterns": ["훅 패턴 1", "훅 패턴 2", ...],
  "structure_patterns": ["구조 패턴 1", ...],
  "tone": "전체적인 톤 설명"
}"""

        result = await loop.run_in_executor(executor, call_claude, sys_p, references_text)
        result = result.strip()

        # JSON 파싱 시도
        try:
            import re as _re
            json_match = _re.search(r'\{[\s\S]*\}', result)
            if json_match:
                parsed = json.loads(json_match.group())
                yield _sse({"type": "analysis", "text": result, **parsed})
            else:
                yield _sse({"type": "analysis", "text": result})
        except (json.JSONDecodeError, ValueError):
            yield _sse({"type": "analysis", "text": result})

        yield _sse({"type": "complete"})
      except Exception as e:
        yield _sse({"type": "error", "message": str(e)})

    return SSEResponse(generate())


@router.post("/extract-patterns")
async def shorts_extract_patterns(request: Request):
    """분석 결과에서 공통 패턴 추출"""
    body = await request.json()
    analyses_text = body.get("analyses_text", "")

    _sse = sse_dict

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        sys_p = """분석 결과들에서 공통 패턴을 추출하여 JSON으로 출력하라:
{
  "common_hooks": ["공통 훅 1", ...],
  "common_structure": "공통 구조 설명",
  "tone_guide": "톤 가이드",
  "key_elements": ["핵심 요소 1", ...]
}"""
        result = await loop.run_in_executor(executor, call_claude, sys_p, analyses_text)
        result = result.strip()

        try:
            import re as _re
            json_match = _re.search(r'\{[\s\S]*\}', result)
            if json_match:
                parsed = json.loads(json_match.group())
                yield _sse({"type": "patterns", **parsed})
            else:
                yield _sse({"type": "patterns", "raw": result})
        except (json.JSONDecodeError, ValueError):
            yield _sse({"type": "patterns", "raw": result})

        yield _sse({"type": "complete"})
      except Exception as e:
        yield _sse({"type": "error", "message": str(e)})

    return SSEResponse(generate())


@router.post("/storyboard")
async def shorts_storyboard(request: Request):
    """스토리보드 (씬 설계)"""
    body = await request.json()

    _sse = sse_dict

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        yield _sse({"type": "progress", "msg": "스토리보드 설계 중..."})

        brief = body.get("brief", "")
        script = body.get("script", "")
        sentences = body.get("sentences", [])
        expected_scenes = body.get("expected_scenes", 8)
        total_duration = body.get("total_duration", 60)

        sys_p = f"""너는 숏츠 영상 스토리보드 전문가다.
대본과 문장 타이밍을 기반으로 {expected_scenes}개 내외의 씬을 설계하라.
각 씬은 6~7초 단위로 나누되, 문장 경계에 맞춰야 한다.
전체 영상 길이: {total_duration:.1f}초

출력 형식 (JSON):
{{
  "scenes": [
    {{
      "start": 0.0,
      "end": 6.5,
      "description": "씬 설명",
      "mood": "dramatic/hopeful/neutral/tense/warm",
      "camera": "zoom_in/zoom_out/pan_left/pan_right/static",
      "text_overlay": "화면에 표시할 텍스트 (없으면 빈 문자열)"
    }},
    ...
  ]
}}"""

        sentences_text = "\n".join(
            f"[{s.get('start', 0):.1f}~{s.get('end', 0):.1f}] {s.get('text', '')}"
            for s in sentences
        )
        usr_p = f"기획서:\n{brief[:500]}\n\n대본:\n{script[:1000]}\n\n문장 타이밍:\n{sentences_text}"

        result = await loop.run_in_executor(executor, call_claude, sys_p, usr_p)
        result = result.strip()

        try:
            import re as _re
            json_match = _re.search(r'\{[\s\S]*\}', result)
            if json_match:
                parsed = json.loads(json_match.group())
                yield _sse({"type": "storyboard", **parsed})
            else:
                yield _sse({"type": "storyboard", "raw": result})
        except (json.JSONDecodeError, ValueError):
            yield _sse({"type": "storyboard", "raw": result})

        yield _sse({"type": "complete"})
      except Exception as e:
        yield _sse({"type": "error", "message": str(e)})

    return SSEResponse(generate())


@router.post("/image-prompts")
async def shorts_image_prompts(request: Request):
    """씬별 이미지 생성 프롬프트"""
    body = await request.json()

    _sse = sse_dict

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        scenes = body.get("scenes", [])
        brief = body.get("brief", "")
        art_style = body.get("art_style", "realistic")

        scenes_desc = "\n".join(
            f"씬 {s['index']}: [{s.get('mood', '')}] {s.get('description', '')[:100]}"
            for s in scenes
        )

        sys_p = f"""너는 AI 이미지 생성 프롬프트 전문가다.
각 씬에 맞는 이미지 생성 프롬프트를 영어로 작성하라.
아트 스타일: {art_style}
형식: 9:16 세로 (숏츠)
출력: JSON 배열 ["prompt1", "prompt2", ...]"""

        usr_p = f"기획서:\n{brief[:300]}\n\n씬 목록:\n{scenes_desc}"

        result = await loop.run_in_executor(executor, call_claude, sys_p, usr_p)
        result = result.strip()

        try:
            import re as _re
            json_match = _re.search(r'\[[\s\S]*\]', result)
            if json_match:
                prompts = json.loads(json_match.group())
                yield _sse({"type": "prompts", "prompts": prompts})
            else:
                yield _sse({"type": "prompts", "raw": result})
        except (json.JSONDecodeError, ValueError):
            yield _sse({"type": "prompts", "raw": result})

        yield _sse({"type": "complete"})
      except Exception as e:
        yield _sse({"type": "error", "message": str(e)})

    return SSEResponse(generate())


@router.post("/youtube-meta")
async def shorts_youtube_meta(request: Request):
    """YouTube 업로드 메타데이터 생성"""
    body = await request.json()

    _sse = sse_dict

    async def generate():
      try:
        loop = asyncio.get_running_loop()
        brief = body.get("brief", "")
        script = body.get("script", "")
        hooks = body.get("hooks", [])

        sys_p = """숏츠 영상의 YouTube 메타데이터를 생성하라.
JSON 형식:
{
  "title": "영상 제목 (60자 이내, 매력적인 훅)",
  "description": "설명 (해시태그 포함)",
  "tags": ["태그1", "태그2", ...],
  "category_id": "22"
}"""

        hooks_text = "\n".join(hooks[:5]) if hooks else ""
        usr_p = f"기획서:\n{brief[:300]}\n\n대본:\n{script[:300]}\n\n훅 후보:\n{hooks_text}"

        result = await loop.run_in_executor(executor, call_claude, sys_p, usr_p)
        result = result.strip()

        try:
            import re as _re
            json_match = _re.search(r'\{[\s\S]*\}', result)
            if json_match:
                parsed = json.loads(json_match.group())
                yield _sse({"type": "meta", **parsed})
            else:
                yield _sse({"type": "meta", "raw": result})
        except (json.JSONDecodeError, ValueError):
            yield _sse({"type": "meta", "raw": result})

        yield _sse({"type": "complete"})
      except Exception as e:
        yield _sse({"type": "error", "message": str(e)})

    return SSEResponse(generate())
