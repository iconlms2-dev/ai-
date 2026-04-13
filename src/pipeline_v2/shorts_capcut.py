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


def render_video_ffmpeg(
    scenes: list[dict],
    audio_path: str,
    subtitle_segments: list[dict],
    image_paths: list[str],
    total_duration: float,
    output_dir: str,
    project_name: str = "shorts",
) -> Optional[str]:
    """ffmpeg로 숏츠 영상 직접 렌더링.

    CapCut 없이 이미지 + 오디오 + 자막 → 9:16 mp4 합성.
    Ken Burns 줌 효과 + 페이드 전환 + SRT 자막 오버레이.

    Returns: 생성된 mp4 파일 경로. 실패 시 None.
    """
    try:
        import ffmpeg as ffmpeg_lib
    except ImportError:
        print("  [ffmpeg] ffmpeg-python 미설치 — pip install ffmpeg-python")
        return None

    # ffmpeg 바이너리 존재 확인
    if shutil.which("ffmpeg") is None:
        print("  [ffmpeg] ffmpeg 바이너리 없음 — brew install ffmpeg")
        return None

    import subprocess
    import tempfile

    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(output_dir, f"{project_name}_{ts}.mp4")

    # 1. SRT 자막 파일 생성
    srt_path = os.path.join(output_dir, f"{project_name}_{ts}.srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(subtitle_segments, 1):
            start = seg["start"]
            end = seg["end"]
            text = seg["text"]
            f.write(f"{i}\n")
            f.write(f"{_format_srt_time(start)} --> {_format_srt_time(end)}\n")
            f.write(f"{text}\n\n")

    # 2. 각 이미지를 씬 길이만큼의 영상 클립으로 변환 + Ken Burns 줌
    clip_paths = []
    for i, scene in enumerate(scenes):
        img_path = image_paths[i] if i < len(image_paths) else None
        if not img_path or not os.path.exists(img_path):
            continue

        duration = max(scene["end"] - scene["start"], 0.5)
        clip_path = os.path.join(output_dir, f"_clip_{i:02d}.mp4")
        clip_paths.append(clip_path)

        # Ken Burns: zoompan으로 줌인 효과
        try:
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", img_path,
                "-vf", (
                    f"scale=2160:3840,format=yuv420p,"
                    f"zoompan=z='min(zoom+0.001,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                    f":d={int(duration*25)}:s=1080x1920:fps=25"
                ),
                "-t", str(duration),
                "-c:v", "libx264",
                "-preset", "fast",
                "-pix_fmt", "yuv420p",
                clip_path,
            ]
            subprocess.run(cmd, capture_output=True, timeout=60, check=True)
        except Exception as e:
            print(f"  [ffmpeg] 클립 {i} 생성 실패: {e}")
            # fallback: 줌 없이 정적 이미지
            try:
                cmd_simple = [
                    "ffmpeg", "-y",
                    "-loop", "1", "-i", img_path,
                    "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                    "-t", str(duration),
                    "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                    clip_path,
                ]
                subprocess.run(cmd_simple, capture_output=True, timeout=60, check=True)
            except Exception as e2:
                print(f"  [ffmpeg] 클립 {i} fallback도 실패: {e2}")
                continue

    if not clip_paths:
        print("  [ffmpeg] 렌더링할 클립 없음")
        return None

    # 3. 클립 연결 (concat)
    concat_file = os.path.join(output_dir, f"_concat_{ts}.txt")
    with open(concat_file, "w") as f:
        for cp in clip_paths:
            f.write(f"file '{cp}'\n")

    concat_path = os.path.join(output_dir, f"_concat_{ts}.mp4")

    try:
        cmd_concat = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            concat_path,
        ]
        subprocess.run(cmd_concat, capture_output=True, timeout=120, check=True)
    except Exception as e:
        print(f"  [ffmpeg] 클립 연결 실패: {e}")
        return None

    # 4. 오디오 합성 + 자막 오버레이 → 최종 mp4
    try:
        # 자막 필터 (SRT 파일 사용)
        srt_escaped = srt_path.replace("'", "'\\''").replace(":", "\\:")
        subtitle_filter = (
            f"subtitles='{srt_escaped}':force_style="
            f"'FontName=NanumSquareRoundEB,FontSize=22,PrimaryColour=&HFFFFFF,"
            f"BackColour=&H80000000,BorderStyle=4,Outline=0,Shadow=0,MarginV=80'"
        )

        cmd_final = [
            "ffmpeg", "-y",
            "-i", concat_path,
            "-i", audio_path,
            "-vf", subtitle_filter,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            output_path,
        ]
        subprocess.run(cmd_final, capture_output=True, timeout=300, check=True)
    except Exception as e:
        print(f"  [ffmpeg] 최종 렌더링 실패 (자막 없이 재시도): {e}")
        # 자막 없이 재시도
        try:
            cmd_nosub = [
                "ffmpeg", "-y",
                "-i", concat_path,
                "-i", audio_path,
                "-map", "0:v", "-map", "1:a",
                "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                output_path,
            ]
            subprocess.run(cmd_nosub, capture_output=True, timeout=300, check=True)
        except Exception as e2:
            print(f"  [ffmpeg] 렌더링 최종 실패: {e2}")
            return None

    # 5. 임시 파일 정리
    for cp in clip_paths:
        try:
            os.remove(cp)
        except OSError:
            pass
    for tmp in [concat_file, concat_path]:
        try:
            os.remove(tmp)
        except OSError:
            pass

    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        print(f"  [ffmpeg] 영상 렌더링 완료: {output_path}")
        return output_path

    return None


def _format_srt_time(seconds: float) -> str:
    """초 → SRT 시간 포맷 (HH:MM:SS,mmm)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


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
