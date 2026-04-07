"""숏츠 TTS + 자막 + 문장분리 유틸.

ElevenLabs TTS → 음성파일 + SRT 자막 + 문장 단위 타이밍 JSON.
"""
import base64
import json
import os
import re
from dataclasses import dataclass
from typing import Optional

import requests

from src.services.config import ELEVENLABS_API_KEY


@dataclass
class Sentence:
    """문장 단위 타이밍 정보."""
    index: int
    text: str
    start: float  # 초
    end: float    # 초

    @property
    def duration(self) -> float:
        return self.end - self.start


def generate_tts(text: str, voice_id: str,
                 model_id: str = "eleven_multilingual_v2") -> tuple[bytes, dict]:
    """ElevenLabs TTS 호출.

    Returns: (audio_bytes, alignment_data)
    """
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY가 설정되지 않았습니다")

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
    r = requests.post(url, headers=headers, json=payload, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs API 에러 ({r.status_code}): {r.text[:300]}")

    data = r.json()
    audio_b64 = data.get("audio_base64", "")
    if not audio_b64:
        raise RuntimeError("ElevenLabs 응답에 오디오 데이터 없음")

    audio_bytes = base64.b64decode(audio_b64)
    alignment = data.get("alignment", {})
    return audio_bytes, alignment


def _build_words_from_alignment(alignment: dict) -> list[dict]:
    """캐릭터 타임스탬프 → 단어 리스트."""
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

    return words


def generate_subtitles(text: str, alignment: dict,
                       words_per_segment: int = 3) -> tuple[str, list[dict]]:
    """타임스탬프 기반 SRT 자막 + 세그먼트 JSON 생성.

    Returns: (srt_content, segments_list)
    """
    words = _build_words_from_alignment(alignment)

    segments = []
    for i in range(0, len(words), words_per_segment):
        group = words[i:i + words_per_segment]
        seg_text = " ".join(w["text"] for w in group)
        segments.append({
            "start": group[0]["start"],
            "end": group[-1]["end"],
            "text": seg_text,
        })

    def _fmt(sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int((sec - int(sec)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    srt_lines = []
    for idx, seg in enumerate(segments, 1):
        srt_lines.append(str(idx))
        srt_lines.append(f"{_fmt(seg['start'])} --> {_fmt(seg['end'])}")
        srt_lines.append(seg["text"])
        srt_lines.append("")

    return "\n".join(srt_lines), segments


def split_sentences(text: str, alignment: dict) -> list[Sentence]:
    """대본 텍스트를 문장 단위로 분리 + 타이밍 매핑.

    씬 설계(07_visual)에서 사용.
    """
    words = _build_words_from_alignment(alignment)
    if not words:
        # alignment 없으면 텍스트만 분리
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        return [Sentence(index=i, text=l, start=0, end=0)
                for i, l in enumerate(lines)]

    # 문장 경계: 줄바꿈 또는 마침표/물음표/느낌표
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    sentences = []
    word_idx = 0
    for i, line in enumerate(lines):
        # 이 문장에 해당하는 단어들 찾기
        line_chars = line.replace(" ", "")
        matched_words = []

        scan_idx = word_idx
        accumulated = ""
        while scan_idx < len(words) and len(accumulated) < len(line_chars):
            accumulated += words[scan_idx]["text"]
            matched_words.append(words[scan_idx])
            scan_idx += 1

        if matched_words:
            sentences.append(Sentence(
                index=i,
                text=line,
                start=matched_words[0]["start"],
                end=matched_words[-1]["end"],
            ))
            word_idx = scan_idx
        else:
            # fallback
            prev_end = sentences[-1].end if sentences else 0
            sentences.append(Sentence(index=i, text=line, start=prev_end, end=prev_end))

    return sentences


def save_audio_outputs(output_dir: str, audio_bytes: bytes,
                       srt_content: str, text: str,
                       sentences: list[Sentence],
                       segments: list[dict]) -> dict:
    """오디오 관련 산출물을 단계 폴더에 저장.

    Returns: 파일 경로 dict
    """
    os.makedirs(output_dir, exist_ok=True)

    paths = {}

    # MP3
    audio_path = os.path.join(output_dir, "audio.mp3")
    with open(audio_path, "wb") as f:
        f.write(audio_bytes)
    paths["audio"] = audio_path

    # SRT
    srt_path = os.path.join(output_dir, "subtitles.srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
    paths["srt"] = srt_path

    # 원본 텍스트
    txt_path = os.path.join(output_dir, "script.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)
    paths["txt"] = txt_path

    # 문장 타이밍 JSON
    timing_path = os.path.join(output_dir, "sentences.json")
    with open(timing_path, "w", encoding="utf-8") as f:
        json.dump(
            [{"index": s.index, "text": s.text, "start": s.start,
              "end": s.end, "duration": s.duration}
             for s in sentences],
            f, ensure_ascii=False, indent=2,
        )
    paths["sentences"] = timing_path

    # 세그먼트 JSON (자막용)
    seg_path = os.path.join(output_dir, "segments.json")
    with open(seg_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    paths["segments"] = seg_path

    return paths
