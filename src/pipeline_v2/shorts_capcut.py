"""숏츠 CapCut 편집 JSON 자동 생성.

CapCut draft_content.json 구조를 프로그래밍으로 생성.
이미지/영상/음성/자막 트랙을 타이밍에 맞춰 배치.
"""
import json
import os
import shutil
import uuid
from datetime import datetime
from typing import Optional

from src.services.config import CAPCUT_DRAFTS_DIR


# ── CapCut 타임 유닛 (마이크로초) ──
MICROSECOND = 1
MILLISECOND = 1000
SECOND = 1_000_000


def _uid() -> str:
    return uuid.uuid4().hex[:16].upper()


def _time_to_us(seconds: float) -> int:
    """초 → 마이크로초."""
    return int(seconds * SECOND)


def _build_image_segment(image_path: str, start: float, end: float,
                         effect: str = "ken_burns") -> dict:
    """이미지 트랙 세그먼트."""
    duration = _time_to_us(end - start)
    seg = {
        "id": _uid(),
        "type": "image",
        "material_id": _uid(),
        "target_timerange": {
            "start": _time_to_us(start),
            "duration": duration,
        },
        "source_timerange": {
            "start": 0,
            "duration": duration,
        },
        "extra_material_refs": [],
        "speed": 1.0,
    }

    # Ken Burns 효과 (줌인/아웃)
    if effect == "ken_burns":
        seg["animations"] = [{
            "type": "ken_burns",
            "start_scale": 1.0,
            "end_scale": 1.15,
            "duration": duration,
        }]

    return seg, {
        "id": seg["material_id"],
        "type": "photo",
        "path": os.path.abspath(image_path),
        "duration": duration,
    }


def _build_audio_segment(audio_path: str, total_duration: float) -> tuple[dict, dict]:
    """오디오 트랙 세그먼트."""
    dur = _time_to_us(total_duration)
    material_id = _uid()
    seg = {
        "id": _uid(),
        "type": "audio",
        "material_id": material_id,
        "target_timerange": {
            "start": 0,
            "duration": dur,
        },
        "source_timerange": {
            "start": 0,
            "duration": dur,
        },
        "speed": 1.0,
        "volume": 1.0,
    }
    material = {
        "id": material_id,
        "type": "audio",
        "path": os.path.abspath(audio_path),
        "duration": dur,
    }
    return seg, material


def _build_subtitle_segments(segments: list[dict]) -> tuple[list[dict], list[dict]]:
    """자막 트랙 세그먼트들."""
    subs = []
    materials = []

    for seg_data in segments:
        material_id = _uid()
        start = seg_data["start"]
        end = seg_data["end"]
        dur = _time_to_us(end - start)

        sub_seg = {
            "id": _uid(),
            "type": "subtitle",
            "material_id": material_id,
            "target_timerange": {
                "start": _time_to_us(start),
                "duration": dur,
            },
        }
        sub_mat = {
            "id": material_id,
            "type": "text",
            "content": seg_data["text"],
            "font": {
                "name": "NanumSquareRoundEB",
                "size": 60,
                "color": [1, 1, 1, 1],
                "bold": True,
            },
            "background": {
                "color": [0, 0, 0, 0.7],
                "corner_radius": 8,
            },
            "position": {"x": 0.5, "y": 0.85},
        }

        subs.append(sub_seg)
        materials.append(sub_mat)

    return subs, materials


def _build_transition(duration_sec: float = 0.5) -> dict:
    """기본 페이드 전환 효과."""
    return {
        "id": _uid(),
        "type": "fade",
        "duration": _time_to_us(duration_sec),
    }


def generate_capcut_project(
    project_name: str,
    scenes: list[dict],
    audio_path: str,
    subtitle_segments: list[dict],
    image_paths: list[str],
    total_duration: float,
    intro_video_path: Optional[str] = None,
) -> str:
    """CapCut draft_content.json 생성.

    Args:
        project_name: 프로젝트 이름
        scenes: 씬 리스트 [{index, start, end, ...}, ...]
        audio_path: TTS 음성 파일 경로
        subtitle_segments: 자막 세그먼트 [{start, end, text}, ...]
        image_paths: 씬별 이미지 경로 리스트
        total_duration: 전체 길이 (초)
        intro_video_path: 훅/인트로 비디오 경로 (선택)

    Returns: draft 폴더 경로
    """
    # 드래프트 폴더 생성
    if CAPCUT_DRAFTS_DIR:
        draft_root = CAPCUT_DRAFTS_DIR
    else:
        draft_root = os.path.join(os.path.expanduser("~"),
                                  "Movies", "CapCut", "User Data",
                                  "Projects", "com.lemon.lv", "drafts")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    draft_name = f"{project_name}_{ts}"
    draft_dir = os.path.join(draft_root, draft_name)
    os.makedirs(draft_dir, exist_ok=True)

    # 트랙 구성
    video_track_segments = []
    all_materials = []
    transitions = []

    # 이미지 트랙
    for i, scene in enumerate(scenes):
        img_path = image_paths[i] if i < len(image_paths) else ""
        if not img_path or not os.path.exists(img_path):
            continue

        seg, mat = _build_image_segment(
            img_path, scene["start"], scene["end"],
            effect="ken_burns",
        )
        video_track_segments.append(seg)
        all_materials.append(mat)

        # 전환 효과 (첫 씬 제외)
        if i > 0:
            transitions.append(_build_transition(0.3))

    # 오디오 트랙
    audio_seg, audio_mat = _build_audio_segment(audio_path, total_duration)
    all_materials.append(audio_mat)

    # 자막 트랙
    sub_segs, sub_mats = _build_subtitle_segments(subtitle_segments)
    all_materials.extend(sub_mats)

    # draft_content.json 구성
    draft_content = {
        "id": _uid(),
        "name": project_name,
        "create_time": int(datetime.now().timestamp()),
        "update_time": int(datetime.now().timestamp()),
        "canvas_config": {
            "width": 1080,
            "height": 1920,
            "ratio": "9:16",
        },
        "duration": _time_to_us(total_duration),
        "tracks": [
            {
                "id": _uid(),
                "type": "video",
                "segments": video_track_segments,
                "transitions": transitions,
            },
            {
                "id": _uid(),
                "type": "audio",
                "segments": [audio_seg],
            },
            {
                "id": _uid(),
                "type": "subtitle",
                "segments": sub_segs,
            },
        ],
        "materials": all_materials,
        "platform": "shorts",
        "version": "1.0",
    }

    # 파일 저장
    content_path = os.path.join(draft_dir, "draft_content.json")
    with open(content_path, "w", encoding="utf-8") as f:
        json.dump(draft_content, f, ensure_ascii=False, indent=2)

    # 미디어 파일 복사 (CapCut이 찾을 수 있도록)
    media_dir = os.path.join(draft_dir, "media")
    os.makedirs(media_dir, exist_ok=True)

    if os.path.exists(audio_path):
        shutil.copy2(audio_path, os.path.join(media_dir, "audio.mp3"))

    for i, img_path in enumerate(image_paths):
        if os.path.exists(img_path) and os.path.getsize(img_path) > 0:
            ext = os.path.splitext(img_path)[1] or ".png"
            shutil.copy2(img_path, os.path.join(media_dir, f"scene_{i:02d}{ext}"))

    print(f"  CapCut 프로젝트: {draft_dir}")
    return draft_dir


def generate_youtube_meta(brief: str, script: str, hooks: list[str]) -> dict:
    """YouTube 업로드용 메타데이터 생성.

    Returns: {title, description, tags, category_id}
    """
    from .common import call_api, get_event

    results = call_api("/api/shorts/youtube-meta", {
        "brief": brief,
        "script": script[:500],
        "hooks": hooks[:5],
    }, timeout=60)

    meta_d = get_event(results, "meta")
    if meta_d:
        return {
            "title": meta_d.get("title", ""),
            "description": meta_d.get("description", ""),
            "tags": meta_d.get("tags", []),
            "category_id": meta_d.get("category_id", "22"),
        }

    # fallback: 훅에서 제목 추출
    title = hooks[0] if hooks else brief[:60]
    return {
        "title": title,
        "description": f"{script[:200]}...\n\n#shorts",
        "tags": ["shorts"],
        "category_id": "22",
    }
