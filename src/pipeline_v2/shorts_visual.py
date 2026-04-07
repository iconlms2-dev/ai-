"""숏츠 비주얼 — 스토리보드 설계 + 이미지 생성.

씬 설계(6~7초 단위) → 이미지 프롬프트 → Whisk AI 이미지 생성 → 훅/인트로 비디오 생성.
"""
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

from src.services.config import WHISK_API_KEY
from .common import call_api, get_event


@dataclass
class Scene:
    """개별 씬 정보."""
    index: int
    start: float       # 초
    end: float          # 초
    description: str    # 씬 설명
    mood: str           # 분위기
    camera: str         # 카메라 앵글/움직임
    text_overlay: str   # 화면에 표시될 텍스트 (자막 외)
    image_prompt: str = ""
    image_path: str = ""
    is_hook: bool = False  # 훅/인트로 씬 여부

    @property
    def duration(self) -> float:
        return self.end - self.start


def design_storyboard(brief: str, script: str,
                      sentences: list[dict],
                      target_scene_duration: float = 6.5) -> list[Scene]:
    """Claude에게 스토리보드 설계 요청.

    Args:
        brief: 기획서 텍스트
        script: 대본 전문
        sentences: 문장 타이밍 리스트 [{index, text, start, end, duration}, ...]
        target_scene_duration: 목표 씬 길이 (초)

    Returns: Scene 리스트
    """
    total_duration = sentences[-1]["end"] if sentences else 60
    expected_scenes = max(3, int(total_duration / target_scene_duration))

    results = call_api("/api/shorts/storyboard", {
        "brief": brief,
        "script": script,
        "sentences": sentences,
        "expected_scenes": expected_scenes,
        "total_duration": total_duration,
    }, timeout=120)

    storyboard_d = get_event(results, "storyboard")
    if not storyboard_d:
        # fallback: 문장 기반 자동 씬 분할
        return _auto_split_scenes(sentences, target_scene_duration)

    scenes = []
    for i, s in enumerate(storyboard_d.get("scenes", [])):
        scenes.append(Scene(
            index=i,
            start=s.get("start", 0),
            end=s.get("end", 0),
            description=s.get("description", ""),
            mood=s.get("mood", ""),
            camera=s.get("camera", "static"),
            text_overlay=s.get("text_overlay", ""),
            is_hook=(i == 0),
        ))

    return scenes if scenes else _auto_split_scenes(sentences, target_scene_duration)


def _auto_split_scenes(sentences: list[dict],
                       target_duration: float = 6.5) -> list[Scene]:
    """문장 타이밍 기반 자동 씬 분할 (API 미응답 시 fallback)."""
    if not sentences:
        return [Scene(index=0, start=0, end=60, description="전체",
                      mood="neutral", camera="static", text_overlay="",
                      is_hook=True)]

    scenes = []
    current_start = sentences[0]["start"]
    current_texts = []
    scene_idx = 0

    for sent in sentences:
        current_texts.append(sent["text"])
        elapsed = sent["end"] - current_start

        if elapsed >= target_duration:
            scenes.append(Scene(
                index=scene_idx,
                start=current_start,
                end=sent["end"],
                description=" ".join(current_texts),
                mood="dramatic" if scene_idx == 0 else "neutral",
                camera="zoom_in" if scene_idx == 0 else "static",
                text_overlay="",
                is_hook=(scene_idx == 0),
            ))
            scene_idx += 1
            current_start = sent["end"]
            current_texts = []

    # 남은 문장
    if current_texts:
        scenes.append(Scene(
            index=scene_idx,
            start=current_start,
            end=sentences[-1]["end"],
            description=" ".join(current_texts),
            mood="hopeful",
            camera="static",
            text_overlay="",
        ))

    return scenes


def generate_image_prompts(scenes: list[Scene], brief: str,
                           art_style: str = "realistic") -> list[str]:
    """씬별 이미지 생성 프롬프트 생성.

    Returns: 프롬프트 리스트 (씬 순서)
    """
    results = call_api("/api/shorts/image-prompts", {
        "scenes": [
            {"index": s.index, "description": s.description,
             "mood": s.mood, "camera": s.camera, "is_hook": s.is_hook}
            for s in scenes
        ],
        "brief": brief,
        "art_style": art_style,
    }, timeout=120)

    prompts_d = get_event(results, "prompts")
    if prompts_d and prompts_d.get("prompts"):
        prompts = prompts_d["prompts"]
        # 씬에 프롬프트 매핑
        for i, scene in enumerate(scenes):
            if i < len(prompts):
                scene.image_prompt = prompts[i]
        return prompts

    # fallback: 기본 프롬프트
    prompts = []
    for scene in scenes:
        prompt = (
            f"{art_style} style, {scene.mood} mood, "
            f"{scene.camera} camera angle, "
            f"scene: {scene.description[:100]}, "
            f"high quality, 9:16 aspect ratio, shorts format"
        )
        scene.image_prompt = prompt
        prompts.append(prompt)

    return prompts


def generate_image_whisk(prompt: str, output_path: str,
                         aspect_ratio: str = "9:16") -> str:
    """Google Whisk AI로 이미지 생성.

    Returns: 저장된 이미지 파일 경로
    """
    if not WHISK_API_KEY:
        raise RuntimeError("WHISK_API_KEY가 설정되지 않았습니다")

    # Whisk AI API 호출
    url = "https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict"
    headers = {
        "Content-Type": "application/json",
    }
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": aspect_ratio,
        },
    }

    r = requests.post(
        f"{url}?key={WHISK_API_KEY}",
        headers=headers,
        json=payload,
        timeout=60,
    )

    if r.status_code != 200:
        raise RuntimeError(f"Whisk AI 에러 ({r.status_code}): {r.text[:300]}")

    data = r.json()
    predictions = data.get("predictions", [])
    if not predictions:
        raise RuntimeError("Whisk AI 응답에 이미지 없음")

    # base64 디코딩 → 파일 저장
    import base64
    img_b64 = predictions[0].get("bytesBase64Encoded", "")
    if not img_b64:
        raise RuntimeError("Whisk AI 이미지 데이터 없음")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(base64.b64decode(img_b64))

    return output_path


def generate_images(scenes: list[Scene], output_dir: str,
                    art_style: str = "realistic") -> list[str]:
    """모든 씬의 이미지 생성.

    Returns: 이미지 경로 리스트
    """
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    paths = []
    for scene in scenes:
        if not scene.image_prompt:
            continue

        img_path = os.path.join(images_dir, f"scene_{scene.index:02d}.png")

        try:
            generate_image_whisk(scene.image_prompt, img_path)
            scene.image_path = img_path
            paths.append(img_path)
            print(f"    씬 {scene.index}: 이미지 생성 완료")
        except Exception as e:
            print(f"    씬 {scene.index}: 이미지 생성 실패 — {e}")
            # placeholder 생성 (빈 파일)
            with open(img_path, "wb") as f:
                f.write(b"")
            scene.image_path = img_path
            paths.append(img_path)

        # rate limiting
        time.sleep(1)

    return paths


def save_storyboard(output_dir: str, scenes: list[Scene]) -> str:
    """스토리보드 JSON 저장."""
    path = os.path.join(output_dir, "storyboard.json")
    data = []
    for s in scenes:
        data.append({
            "index": s.index,
            "start": s.start,
            "end": s.end,
            "duration": s.duration,
            "description": s.description,
            "mood": s.mood,
            "camera": s.camera,
            "text_overlay": s.text_overlay,
            "image_prompt": s.image_prompt,
            "image_path": s.image_path,
            "is_hook": s.is_hook,
        })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return path
