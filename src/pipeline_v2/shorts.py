"""숏츠 v2 파이프라인 — 벤치마킹→전략→기획→대본→검수→TTS→저장."""
import argparse
import sys
from datetime import datetime

from .base_pipeline import BasePipeline
from .state_machine import ProjectState
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
        "07_save",
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
            "content_type": args.type,
            "length": args.length,
            "dedup_key": f"shorts:{args.product}:{datetime.now().strftime('%Y%m%d')}",
        }

    def execute_step(self, step: str, args):
        p = self.project

        if step == "00_input":
            p.save_step_file("00_input", "material.json", p.get("material"))

        elif step == "01_benchmark":
            # v2: YouTube 레퍼런스 수집 + 분석
            data = self.do_benchmark(args)
            p.save_step_file("01_benchmark", "references.json", data)

        elif step == "02_strategy":
            material = p.load_step_file("00_input", "material.json")
            results = call_api("/api/shorts/topics", {
                "material": material,
                "type": p.get("content_type", "썰형"),
            }, timeout=120)
            topics_d = get_event(results, "topics")
            if not topics_d:
                raise RuntimeError(f"주제 생성 실패: {get_event(results, 'error')}")

            import re
            topics_text = topics_d["text"]
            numbered = [l.strip() for l in topics_text.split("\n")
                        if l.strip() and re.match(r'^\d+\.', l.strip())]
            topics = []
            for line in numbered:
                clean = re.sub(r'^\d+\.\s*', '', line).split("—")[0].strip().strip('"').strip('\u201c').strip('\u201d').strip('*')
                topics.append({"topic": clean, "hook_angle": "", "appeal": ""})

            strategy = {
                "topics": topics,
                "selected_index": 0,
                "content_type": p.get("content_type", "썰형"),
            }
            p.save_step_file("02_strategy", "strategy.json", strategy)
            topic = topics[0]["topic"] if topics else ""
            print(f"  주제 선택: {topic[:60]}")

        elif step == "03_brief":
            strategy = p.load_step_file("02_strategy", "strategy.json")
            selected = strategy["topics"][strategy["selected_index"]]
            brief = f"# 기획서\n\n주제: {selected['topic']}\n유형: {strategy['content_type']}\n"
            p.save_step_file("03_brief", "brief.md", brief, as_json=False)

        elif step == "04_script":
            strategy = p.load_step_file("02_strategy", "strategy.json")
            material = p.load_step_file("00_input", "material.json")
            topic = strategy["topics"][strategy["selected_index"]]["topic"]

            def write_fn(_):
                results = call_api("/api/shorts/script", {
                    "material": material,
                    "type": p.get("content_type", "썰형"),
                    "topic": topic,
                    "length": p.get("length", 600),
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
            print(f"  {content['char_count']}자 | 리비전 {revision}회")

        elif step == "05_review":
            # AI 검수 (규칙은 04에서 완료, 여기서는 AI만)
            script = p.load_step_file("04_script", "script.json")
            if script:
                from .common import ai_review
                result = ai_review(script["text"], "shorts", {
                    "자연스러움": 7, "설득력": 6, "채널적합도": 7
                })
                p.save_step_file("05_review", "review.json", result)
                print(f"  AI 검수: {'PASS' if result['pass'] else 'FAIL'} (점수: {result['score']})")
                p.transition("under_review")
                if result["pass"]:
                    p.transition("approved")

        elif step == "06_audio":
            # TTS 생성
            script = p.load_step_file("04_script", "script.json")
            if script:
                try:
                    results = call_api("/api/shorts/hooks", {
                        "script": script["text"]
                    }, timeout=120)
                    hooks_d = get_event(results, "hooks")
                    hooks_text = hooks_d["text"] if hooks_d else ""
                    import re
                    hook_lines = [l.strip() for l in hooks_text.split("\n")
                                  if re.match(r'^\d+\.', l.strip())]
                    p.save_step_file("06_audio", "hooks.json", {"hooks": hook_lines})
                    print(f"  훅 {len(hook_lines)}개 생성")
                except Exception as e:
                    print(f"  훅 생성 스킵: {e}")
                    p.save_step_file("06_audio", "hooks.json", {"hooks": [], "skipped": True})

        elif step == "07_save":
            p.save_step_file("07_save", "saved.json", {
                "saved_at": datetime.now().isoformat(),
                "status": "completed"
            })

    def finalize(self, args):
        p = self.project
        script = p.load_step_file("04_script", "script.json") or {}
        hooks = p.load_step_file("06_audio", "hooks.json") or {}
        review = p.load_step_file("05_review", "review.json") or {}

        print_report("숏츠 v2 최종 보고", [
            f"프로젝트: {p.project_id}",
            f"글자수: {script.get('char_count', 0)}자",
            f"리비전: {p.get('revision_count', 0)}회",
            f"AI 검수: {review.get('score', '-')}점",
            f"훅: {len(hooks.get('hooks', []))}개",
            f"\n--- 대본 ---",
            script.get("text", "(없음)")[:500],
        ])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--product", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--problem", required=True)
    p.add_argument("--emotion", required=True)
    p.add_argument("--trust", required=True)
    p.add_argument("--cta", required=True)
    p.add_argument("--type", default="썰형")
    p.add_argument("--length", type=int, default=600)
    p.add_argument("--resume", action="store_true")
    args = p.parse_args()

    pipeline = ShortsPipeline()
    if args.resume:
        pipeline.resume(args)
    else:
        pipeline.run(args)


if __name__ == "__main__":
    main()
