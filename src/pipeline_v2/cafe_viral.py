"""카페바이럴 v2 파이프라인 — 3단계(일상→고민→침투) 생성→검수→저장."""
import argparse
from datetime import datetime

from .base_pipeline import BasePipeline
from .state_machine import ProjectState
from .common import call_api, get_event, print_report
from .rule_validators import validate_cafe_viral


class CafeViralPipeline(BasePipeline):
    channel = "cafe_viral"
    steps = [
        "00_input",
        "01_benchmark",
        "02_strategy",
        "03_brief",
        "04_write",
        "05_review",
        "06_save",
    ]

    def build_meta(self, args) -> dict:
        return {
            "category": args.category,
            "product": {
                "target": args.target,
                "target_concern": args.target_concern,
                "product_category": args.product_category,
                "brand_keyword": args.brand_keyword,
                "name": args.product_name,
                "usp": args.usp,
                "ingredients": args.ingredients,
            },
            "set_count": args.set_count,
            "dedup_key": f"cafe_viral:{args.brand_keyword}:{datetime.now().strftime('%Y%m%d')}",
        }

    def execute_step(self, step: str, args):
        p = self.project

        if step == "00_input":
            p.save_step_file("00_input", "input.json", {
                "category": p.get("category"),
                "product": p.get("product"),
                "set_count": p.get("set_count", 1),
            })

        elif step == "01_benchmark":
            data = self.do_benchmark(args)
            p.save_step_file("01_benchmark", "references.json", data)

        elif step == "02_strategy":
            data = self.do_strategy(args)
            p.save_step_file("02_strategy", "strategy.json", data)

        elif step == "03_brief":
            brief = self.do_brief(args)
            p.save_step_file("03_brief", "brief.md", brief or "", as_json=False)

        elif step == "04_write":
            category = p.get("category")
            product = p.get("product")
            set_count = p.get("set_count", 1)

            def write_fn(_):
                payload = {
                    "category": category,
                    "product": product,
                    "set_count": set_count,
                }
                results = call_api("/api/viral/generate", payload, timeout=300)
                result_d = get_event(results, "result")
                if not result_d:
                    err = get_event(results, "error")
                    raise RuntimeError(f"생성 실패: {err}")
                data = result_d.get("data", result_d)
                return {
                    "stage1": data.get("stage1", {}),
                    "stage2": data.get("stage2", {}),
                    "stage3": data.get("stage3", {}),
                }

            def validate_fn(content):
                return validate_cafe_viral(
                    content["stage1"], content["stage2"], content["stage3"],
                )

            content, revision = self.revision_loop(args, write_fn, validate_fn)
            p.save_step_file("04_write", "draft.json", content)
            p.update(revision_count=revision)
            print(f"  3단계 생성 완료 | 리비전 {revision}회")

        elif step == "05_review":
            content = p.load_step_file("04_write", "draft.json")
            if content:
                combined = ""
                for key in ["stage1", "stage2", "stage3"]:
                    s = content.get(key, {})
                    combined += s.get("title", "") + "\n" + s.get("body", "") + "\n"
                from .common import ai_review
                result = ai_review(combined, "cafe_viral", {
                    "자연스러움": 8, "단계별일관성": 7, "광고비노출": 8,
                })
                p.save_step_file("05_review", "review.json", result)
                print(f"  AI 검수: {'PASS' if result['pass'] else 'FAIL'} (점수: {result['score']})")
                p.transition("under_review")
                if result["pass"]:
                    p.transition("approved")

        elif step == "06_save":
            p.save_step_file("06_save", "saved.json", {
                "saved_at": datetime.now().isoformat(),
                "status": "completed",
            })

    def _extract_review_text(self, content: dict) -> str:
        parts = []
        for key in ["stage1", "stage2", "stage3"]:
            s = content.get(key, {})
            parts.append(s.get("body", ""))
        return "\n".join(parts)

    def finalize(self, args):
        p = self.project
        content = p.load_step_file("04_write", "draft.json") or {}
        review = p.load_step_file("05_review", "review.json") or {}

        lines = [
            f"프로젝트: {p.project_id}",
            f"카테고리: {p.get('category')}",
            f"리비전: {p.get('revision_count', 0)}회",
            f"AI 검수: {review.get('score', '-')}점",
        ]
        for i, key in enumerate(["stage1", "stage2", "stage3"], 1):
            s = content.get(key, {})
            lines.append(f"\n--- {i}단계: {s.get('title', '(없음)')} ---")
            lines.append(s.get("body", "(없음)")[:200])

        print_report("카페바이럴 v2 최종 보고", lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--category", required=True)
    p.add_argument("--product-name", required=True)
    p.add_argument("--brand-keyword", required=True)
    p.add_argument("--usp", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--target-concern", required=True)
    p.add_argument("--product-category", required=True)
    p.add_argument("--ingredients", default="")
    p.add_argument("--set-count", type=int, default=1)
    p.add_argument("--resume", action="store_true")
    args = p.parse_args()

    pipeline = CafeViralPipeline()
    if args.resume:
        pipeline.resume(args)
    else:
        pipeline.run(args)


if __name__ == "__main__":
    main()
