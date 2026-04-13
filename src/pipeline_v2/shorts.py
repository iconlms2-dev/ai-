"""숏츠 v2 풀 자동화 파이프라인 — 10단계.

00_input → 01_benchmark → 02_strategy → 03_brief → 04_script
→ 05_review → 06_audio → 07_visual → 08_edit → 09_upload

auto 모드: 전 과정 자동 / ask 모드: 전략·업로드에서 사용자 확인
수동 단계: CapCut 렌더링 1곳만
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

from .base_pipeline import BasePipeline
from .state_machine import ProjectState
from .workflow import WorkflowConfig
from .common import call_api, get_event, print_report
from .rule_validators import validate_shorts


class ShortsPipeline(BasePipeline):
    channel = "shorts"
    steps = [
        "00_input",
        "01_benchmark",
        "02_strategy",
        "03_brief",
        "04_script",
        "05_review",
        "06_audio",
        "07_visual",
        "08_edit",
        "09_upload",
    ]

    def build_meta(self, args) -> dict:
        return {
            "material": {
                "product": args.product,
                "target": args.target,
                "problem": args.problem,
                "emotion": args.emotion,
                "trust": args.trust,
                "cta": args.cta,
            },
            "content_type": getattr(args, "type", "썰형"),
            "length": getattr(args, "length", 600),
            "mode": getattr(args, "mode", self.workflow.mode),
            "benchmark_urls": getattr(args, "urls", None) or self.workflow.benchmark_urls,
            "voice_id": getattr(args, "voice_id", "") or self.workflow.voice_id,
            "dedup_key": f"shorts:{args.product}:{datetime.now().strftime('%Y%m%d')}",
        }

    # ──────────────────────────────────────────────────────────
    # 단계별 실행
    # ──────────────────────────────────────────────────────────

    def execute_step(self, step: str, args):
        p = self.project

        if step == "00_input":
            self._step_input(p)

        elif step == "01_benchmark":
            self._step_benchmark(p)

        elif step == "02_strategy":
            self._step_strategy(p, args)

        elif step == "03_brief":
            self._step_brief(p)

        elif step == "04_script":
            self._step_script(p, args)

        elif step == "05_review":
            self._step_review(p)

        elif step == "06_audio":
            self._step_audio(p)

        elif step == "07_visual":
            self._step_visual(p)

        elif step == "08_edit":
            self._step_edit(p)

        elif step == "09_upload":
            self._step_upload(p)

    # ── 00: 입력 ──

    def _step_input(self, p: ProjectState):
        p.save_step_file("00_input", "material.json", p.get("material"))

    # ── 01: 벤치마킹 ──

    def _step_benchmark(self, p: ProjectState):
        urls = p.get("benchmark_urls") or []
        if not urls:
            print("  벤치마킹 URL 없음 — 스킵")
            p.save_step_file("01_benchmark", "benchmark.json", {"skipped": True})
            return

        from .shorts_benchmark import run_benchmark
        data = run_benchmark(urls)
        p.save_step_file("01_benchmark", "benchmark.json", data)

        ref_count = len(data.get("references", []))
        print(f"  벤치마킹 완료: {ref_count}개 영상 분석")
        self.cost.add("claude", 0.3, "벤치마킹 분석")

    # ── 02: 전략 (컨셉 3세트) ──

    def _step_strategy(self, p: ProjectState, args):
        material = p.load_step_file("00_input", "material.json")
        benchmark = p.load_step_file("01_benchmark", "benchmark.json") or {}
        patterns = benchmark.get("patterns", {})

        # 컨셉 3세트 생성
        results = call_api("/api/shorts/topics", {
            "material": material,
            "type": p.get("content_type", "썰형"),
            "patterns": patterns if not patterns.get("skipped") else None,
            "count": 3,
        }, timeout=120)

        topics_d = get_event(results, "topics")
        if not topics_d:
            raise RuntimeError(f"주제 생성 실패: {get_event(results, 'error')}")

        topics_text = topics_d["text"]
        numbered = [l.strip() for l in topics_text.split("\n")
                    if l.strip() and re.match(r'^\d+\.', l.strip())]

        concepts = []
        for line in numbered[:3]:
            clean = re.sub(r'^\d+\.\s*', '', line)
            parts = clean.split("—", 1)
            topic = parts[0].strip().strip('"').strip('\u201c').strip('\u201d').strip('*')
            appeal = parts[1].strip() if len(parts) > 1 else ""
            concepts.append({
                "topic": topic,
                "appeal": appeal,
                "hook_angle": "",
            })

        # auto/ask 모드에 따른 선택
        if self.workflow.should_ask("02_strategy"):
            selected_idx = self.ask_user(
                "컨셉을 선택하세요:",
                [{"label": f"{c['topic']} — {c['appeal']}"} for c in concepts],
            )
        else:
            # auto: 첫 번째 (또는 AI 추천) 자동 선택
            selected_idx = 0

        strategy = {
            "concepts": concepts,
            "selected_index": selected_idx,
            "content_type": p.get("content_type", "썰형"),
            "patterns": patterns if not patterns.get("skipped") else {},
        }
        p.save_step_file("02_strategy", "strategy.json", strategy)
        self.cost.add("claude", 0.1, "전략 생성")

        topic = concepts[selected_idx]["topic"] if concepts else ""
        print(f"  컨셉 선택: {topic[:60]}")

    # ── 03: 기획서 ──

    def _step_brief(self, p: ProjectState):
        strategy = p.load_step_file("02_strategy", "strategy.json")
        selected = strategy["concepts"][strategy["selected_index"]]
        patterns = strategy.get("patterns", {})

        # 상세 기획서 생성 (벤치마킹 패턴 반영)
        material = p.load_step_file("00_input", "material.json")

        results = call_api("/api/shorts/brief", {
            "material": material,
            "concept": selected,
            "content_type": strategy["content_type"],
            "patterns": patterns,
        }, timeout=120)

        brief_d = get_event(results, "brief")
        if brief_d and brief_d.get("text"):
            brief_text = brief_d["text"]
        else:
            # fallback: 기본 기획서
            hook_patterns = patterns.get("common_hooks", [])
            hook_section = "\n".join(f"- {h}" for h in hook_patterns[:3]) if hook_patterns else "- 없음"
            brief_text = f"""# 기획서

## 주제
{selected['topic']}

## 유형
{strategy['content_type']}

## 소재
- 제품: {material.get('product', '')}
- 타겟: {material.get('target', '')}
- 문제: {material.get('problem', '')}
- 감정: {material.get('emotion', '')}
- 신뢰근거: {material.get('trust', '')}
- CTA: {material.get('cta', '')}

## 매력 포인트
{selected.get('appeal', '')}

## 벤치마킹 훅 패턴
{hook_section}

## 구조
1. 훅 (3초) — 강력한 첫 문장
2. 감정 공감 — 타겟의 고통 묘사
3. 전환점 — 해결 방법 발견
4. 증거 — 신뢰 근거 제시
5. 결과 — 극적인 변화
6. CTA — 행동 유도
"""

        p.save_step_file("03_brief", "brief.md", brief_text, as_json=False)
        self.cost.add("claude", 0.1, "기획서 생성")
        print(f"  기획서 생성 완료 ({len(brief_text)}자)")

    # ── 04: 대본 ──

    def _step_script(self, p: ProjectState, args):
        strategy = p.load_step_file("02_strategy", "strategy.json")
        material = p.load_step_file("00_input", "material.json")
        brief = p.load_step_file("03_brief", "brief.md", as_json=False) or ""
        topic = strategy["concepts"][strategy["selected_index"]]["topic"]

        def write_fn(_):
            results = call_api("/api/shorts/script", {
                "material": material,
                "type": p.get("content_type", "썰형"),
                "topic": topic,
                "length": p.get("length", 600),
                "brief": brief,
            }, timeout=120)
            script_d = get_event(results, "script")
            if not script_d:
                raise RuntimeError(f"대본 생성 실패: {get_event(results, 'error')}")
            return {"text": script_d["text"], "char_count": len(script_d["text"])}

        def validate_fn(content):
            return validate_shorts(content["text"])

        content, revision = self.revision_loop(args, write_fn, validate_fn)
        p.save_step_file("04_script", "draft.md", content["text"], as_json=False)
        p.save_step_file("04_script", "script.json", content)
        p.update(revision_count=revision)
        self.cost.add("claude", 0.2 * (1 + revision), "대본 생성+리비전")
        print(f"  {content['char_count']}자 | 리비전 {revision}회")

    # ── 05: AI 검수 ──

    def _step_review(self, p: ProjectState):
        script = p.load_step_file("04_script", "script.json")
        if not script:
            raise RuntimeError("대본 없음 — 04_script 단계 미완료")

        from .common import ai_review
        result = ai_review(script["text"], "shorts", {
            "자연스러움": 7, "설득력": 6, "채널적합도": 7
        })
        p.save_step_file("05_review", "review.json", result)
        print(f"  AI 검수: {'PASS' if result['pass'] else 'FAIL'} (점수: {result['score']})")

        p.transition("under_review")
        if result["pass"]:
            p.transition("approved")
        self.cost.add("claude", 0.1, "AI 검수")

    # ── 06: TTS + 자막 + 문장분리 ──

    def _step_audio(self, p: ProjectState):
        script = p.load_step_file("04_script", "script.json")
        if not script:
            raise RuntimeError("대본 없음")

        voice_id = p.get("voice_id") or self.workflow.voice_id
        if not voice_id:
            # ask 모드면 음성 선택 요청
            if self.workflow.should_ask("06_audio"):
                # 서버 API로 음성 목록 조회
                from .common import call_api_json
                try:
                    voices_data = call_api_json("/api/shorts/voices", method="GET")
                    voices = voices_data.get("voices", [])
                    if voices:
                        idx = self.ask_user(
                            "TTS 음성을 선택하세요:",
                            [{"label": f"{v['name']} ({v.get('category', '')})",
                              "voice_id": v["voice_id"]}
                             for v in voices[:10]],
                        )
                        voice_id = voices[idx]["voice_id"]
                except Exception:
                    pass

            if not voice_id:
                # fallback: 기본 한국어 음성
                voice_id = "XB0fDUnXU5powFXDhCwa"  # Charlotte (ElevenLabs 기본)

        from .shorts_audio import (
            generate_tts, generate_subtitles, split_sentences,
            save_audio_outputs,
        )

        print("  TTS 생성 중 (ElevenLabs)...")
        audio_bytes, alignment = generate_tts(script["text"], voice_id)
        self.cost.add("elevenlabs", 2.75, f"TTS ({len(script['text'])}자)")

        print("  자막 생성 중...")
        srt_content, segments = generate_subtitles(script["text"], alignment)

        print("  문장 분리 중...")
        sentences = split_sentences(script["text"], alignment)

        output_dir = p.step_dir("06_audio")
        paths = save_audio_outputs(
            output_dir, audio_bytes, srt_content,
            script["text"], sentences, segments,
        )

        p.save_step_file("06_audio", "audio_meta.json", {
            "voice_id": voice_id,
            "duration": sentences[-1].end if sentences else 0,
            "sentence_count": len(sentences),
            "segment_count": len(segments),
            "paths": {k: os.path.basename(v) for k, v in paths.items()},
        })

        duration = sentences[-1].end if sentences else 0
        print(f"  TTS 완료: {duration:.1f}초 | {len(sentences)}문장 | {len(segments)}자막")

    # ── 07: 비주얼 (스토리보드 + 이미지) ──

    def _step_visual(self, p: ProjectState):
        brief = p.load_step_file("03_brief", "brief.md", as_json=False) or ""
        script = p.load_step_file("04_script", "script.json")
        sentences_data = p.load_step_file("06_audio", "sentences.json")

        if not script or not sentences_data:
            raise RuntimeError("대본 또는 문장 타이밍 데이터 없음")

        from .shorts_visual import (
            design_storyboard, generate_image_prompts,
            generate_images, save_storyboard,
        )

        print("  스토리보드 설계 중...")
        scenes = design_storyboard(brief, script["text"], sentences_data)
        self.cost.add("claude", 0.15, "스토리보드 설계")

        print(f"  {len(scenes)}개 씬 설계 완료")

        print("  이미지 프롬프트 생성 중...")
        art_style = self.workflow.art_style
        prompts = generate_image_prompts(scenes, brief, art_style)
        self.cost.add("claude", 0.1, "이미지 프롬프트")

        print(f"  {len(scenes)}개 이미지 생성 중 (Whisk AI)...")
        output_dir = p.step_dir("07_visual")

        try:
            image_paths = generate_images(scenes, output_dir, art_style)
            img_cost = len(image_paths) * 0.12  # 이미지 1장당 ~$0.12
            self.cost.add("whisk", img_cost, f"이미지 {len(image_paths)}장")
        except Exception as e:
            print(f"  이미지 생성 실패: {e}")
            image_paths = []

        storyboard_path = save_storyboard(output_dir, scenes)
        print(f"  비주얼 완료: {len(image_paths)}개 이미지")

    # ── 08: CapCut 편집 JSON ──

    def _step_edit(self, p: ProjectState):
        # 필요 데이터 로드
        script = p.load_step_file("04_script", "script.json")
        audio_meta = p.load_step_file("06_audio", "audio_meta.json")
        storyboard_data = p.load_step_file("07_visual", "storyboard.json")
        segments_data = p.load_step_file("06_audio", "segments.json")

        if not script or not audio_meta:
            raise RuntimeError("대본 또는 오디오 메타 없음")

        from .shorts_capcut import generate_capcut_project, generate_youtube_meta, render_video_ffmpeg

        # 파일 경로 구성
        audio_dir = p.step_dir("06_audio")
        audio_path = os.path.join(audio_dir, "audio.mp3")
        visual_dir = p.step_dir("07_visual")

        # 이미지 경로 수집
        image_paths = []
        if storyboard_data:
            for scene in storyboard_data:
                img_path = scene.get("image_path", "")
                if img_path and os.path.exists(img_path):
                    image_paths.append(img_path)
                else:
                    # images 폴더에서 씬 번호로 찾기
                    alt = os.path.join(visual_dir, "images", f"scene_{scene['index']:02d}.png")
                    image_paths.append(alt if os.path.exists(alt) else "")

        scenes = storyboard_data or []
        subtitle_segments = segments_data or []
        total_duration = audio_meta.get("duration", 60)

        print("  CapCut 프로젝트 생성 중...")
        project_name = f"shorts_{p.project_id}"
        draft_dir = generate_capcut_project(
            project_name=project_name,
            scenes=scenes,
            audio_path=audio_path,
            subtitle_segments=subtitle_segments,
            image_paths=image_paths,
            total_duration=total_duration,
        )

        # ffmpeg 자동 렌더링 (CapCut 없이도 mp4 생성)
        upload_dir = p.step_dir("09_upload")
        ffmpeg_video_path = None
        if image_paths and os.path.exists(audio_path):
            print("  ffmpeg 자동 렌더링 시도 중...")
            ffmpeg_video_path = render_video_ffmpeg(
                scenes=scenes,
                audio_path=audio_path,
                subtitle_segments=subtitle_segments,
                image_paths=image_paths,
                total_duration=total_duration,
                output_dir=upload_dir,
                project_name=project_name,
            )
            if ffmpeg_video_path:
                print(f"  ffmpeg 렌더링 성공: {ffmpeg_video_path}")
            else:
                print("  ffmpeg 렌더링 실패 — CapCut에서 수동 렌더링 필요")

        # YouTube 메타데이터 생성
        brief = p.load_step_file("03_brief", "brief.md", as_json=False) or ""
        hooks_data = p.load_step_file("06_audio", "hooks.json") or {}
        hooks = hooks_data.get("hooks", [])

        print("  YouTube 메타데이터 생성 중...")
        yt_meta = generate_youtube_meta(brief, script["text"], hooks)
        self.cost.add("claude", 0.05, "YouTube 메타데이터")

        p.save_step_file("08_edit", "edit_meta.json", {
            "capcut_draft_dir": draft_dir,
            "ffmpeg_video_path": ffmpeg_video_path or "",
            "youtube_meta": yt_meta,
            "total_duration": total_duration,
            "scene_count": len(scenes),
            "image_count": len([ip for ip in image_paths if ip]),
        })

        if ffmpeg_video_path:
            print(f"  영상 자동 렌더링 완료 → 09_upload 단계 자동 진행 가능")
        else:
            print(f"  CapCut 프로젝트 생성 완료")
            print(f"  렌더링 후 09_upload/ 폴더에 .mp4 파일을 넣어주세요")

    # ── 09: YouTube 업로드 ──

    def _step_upload(self, p: ProjectState):
        from .shorts_upload import upload_to_youtube, check_rendered_video

        edit_meta = p.load_step_file("08_edit", "edit_meta.json")
        if not edit_meta:
            raise RuntimeError("편집 메타 없음 — 08_edit 단계 미완료")

        yt_meta = edit_meta.get("youtube_meta", {})

        # 렌더링된 영상 찾기
        video_path = check_rendered_video(p.root)
        if not video_path:
            # 09_upload 폴더 생성하고 안내
            upload_dir = p.step_dir("09_upload")
            p.save_step_file("09_upload", "waiting.json", {
                "status": "waiting_for_render",
                "message": "CapCut에서 렌더링 후 이 폴더에 .mp4 파일을 넣어주세요",
                "upload_dir": upload_dir,
            })
            print("  렌더링된 영상 없음 — 렌더링 후 --resume로 재실행하세요")
            print(f"  영상 경로: {upload_dir}/")
            return

        # ask 모드: 업로드 전 확인
        if self.workflow.should_ask("09_upload"):
            idx = self.ask_user(
                f"YouTube에 업로드하시겠습니까?\n제목: {yt_meta.get('title', '')}\n파일: {video_path}",
                [{"label": "업로드"}, {"label": "스킵"}],
            )
            if idx == 1:
                p.save_step_file("09_upload", "upload.json", {"skipped": True})
                print("  업로드 스킵")
                return

        try:
            p.transition("publish_ready")
            p.transition("uploading")

            result = upload_to_youtube(
                video_path=video_path,
                title=yt_meta.get("title", f"shorts_{p.project_id}"),
                description=yt_meta.get("description", ""),
                tags=yt_meta.get("tags", ["shorts"]),
                category_id=yt_meta.get("category_id", "22"),
                privacy="private",  # 안전을 위해 비공개로 업로드
            )

            p.transition("published")
            p.save_step_file("09_upload", "upload.json", result)
            print(f"  업로드 완료: {result['url']}")

        except Exception as e:
            p.save_step_file("09_upload", "upload.json", {
                "error": str(e),
                "video_path": video_path,
            })
            print(f"  업로드 실패: {e}")
            raise

    # ──────────────────────────────────────────────────────────
    # 최종 보고
    # ──────────────────────────────────────────────────────────

    def finalize(self, args):
        p = self.project
        script = p.load_step_file("04_script", "script.json") or {}
        review = p.load_step_file("05_review", "review.json") or {}
        audio_meta = p.load_step_file("06_audio", "audio_meta.json") or {}
        edit_meta = p.load_step_file("08_edit", "edit_meta.json") or {}
        upload = p.load_step_file("09_upload", "upload.json") or {}

        cost_summary = self.cost.summary()

        lines = [
            f"프로젝트: {p.project_id}",
            f"글자수: {script.get('char_count', 0)}자",
            f"리비전: {p.get('revision_count', 0)}회",
            f"AI 검수: {review.get('score', '-')}점",
            f"음성: {audio_meta.get('duration', 0):.1f}초",
            f"씬: {edit_meta.get('scene_count', 0)}개",
            f"이미지: {edit_meta.get('image_count', 0)}개",
        ]

        if upload.get("url"):
            lines.append(f"YouTube: {upload['url']}")
        elif upload.get("skipped"):
            lines.append("업로드: 스킵")
        elif upload.get("status") == "waiting_for_render":
            lines.append("업로드: 렌더링 대기 중")

        lines.append(f"\n비용: ${cost_summary['total']:.2f}")
        for svc, amt in cost_summary.get("by_service", {}).items():
            lines.append(f"  - {svc}: ${amt:.2f}")

        lines.extend([
            f"\n--- 대본 (앞 500자) ---",
            script.get("text", "(없음)")[:500],
        ])

        print_report("숏츠 v2 풀 자동화 최종 보고", lines)

        # 비용 경고
        if cost_summary["total"] > self.workflow.cost_limit:
            print(f"\n[경고] 비용 ${cost_summary['total']:.2f} > 상한 ${self.workflow.cost_limit:.2f}")


# ──────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="숏츠 풀 자동화 파이프라인")
    p.add_argument("--product", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--problem", required=True)
    p.add_argument("--emotion", required=True)
    p.add_argument("--trust", required=True)
    p.add_argument("--cta", required=True)
    p.add_argument("--type", default="썰형")
    p.add_argument("--length", type=int, default=600)
    p.add_argument("--mode", choices=["auto", "ask"], default="auto")
    p.add_argument("--urls", nargs="*", default=[], help="벤치마킹 YouTube URL")
    p.add_argument("--voice-id", dest="voice_id", default="")
    p.add_argument("--resume", action="store_true")
    args = p.parse_args()

    workflow = WorkflowConfig(
        mode=args.mode,
        voice_id=args.voice_id,
        benchmark_urls=args.urls or [],
    )

    pipeline = ShortsPipeline(workflow=workflow)
    if args.resume:
        pipeline.resume(args)
    else:
        pipeline.run(args)


if __name__ == "__main__":
    main()
