"""카페SEO v2 파이프라인 — 키워드→원고+댓글 생성→검수→저장."""
import argparse
from datetime import datetime

from .base_pipeline import BasePipeline
from .state_machine import ProjectState
from .common import call_api, get_event, print_report
from .rule_validators import validate_cafe_seo


class CafeSeoPipeline(BasePipeline):
    channel = "cafe_seo"
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
            "keyword": args.keyword,
            "product": {
                "name": args.product_name,
                "brand_keyword": args.brand_keyword,
                "usp": args.usp,
                "target": args.target,
                "ingredients": args.ingredients,
            },
            "dedup_key": f"cafe_seo:{args.keyword}:{datetime.now().strftime('%Y%m%d')}",
        }

    def execute_step(self, step: str, args):
        p = self.project

        if step == "00_input":
            p.save_step_file("00_input", "input.json", {
                "keyword": p.get("keyword"),
                "product": p.get("product"),
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
            keyword = p.get("keyword")
            product = p.get("product")

            def write_fn(_):
                payload = {
                    "keywords": [{"keyword": keyword, "page_id": ""}],
                    "product": product,
                }
                results = call_api("/api/cafe/generate", payload, timeout=300)
                result_d = get_event(results, "result")
                if not result_d:
                    err = get_event(results, "error")
                    raise RuntimeError(f"생성 실패: {err}")
                data = result_d.get("data", result_d)
                return {
                    "title": data.get("title", ""),
                    "body": data.get("body", ""),
                    "comments": data.get("comments", ""),
                }

            def validate_fn(content):
                return validate_cafe_seo(
                    content["body"], keyword, content.get("comments", ""),
                )

            content, revision = self.revision_loop(args, write_fn, validate_fn)
            p.save_step_file("04_write", "draft.json", content)
            p.update(revision_count=revision)
            print(f"  {len(content['body'])}자 | 리비전 {revision}회")

        elif step == "05_review":
            content = p.load_step_file("04_write", "draft.json")
            if content:
                from .common import ai_review
                result = ai_review(content["body"], "cafe_seo", {
                    "자연스러움": 7, "SEO적합도": 7, "댓글품질": 6,
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

    def finalize(self, args):
        p = self.project
        content = p.load_step_file("04_write", "draft.json") or {}
        review = p.load_step_file("05_review", "review.json") or {}

        print_report("카페SEO v2 최종 보고", [
            f"프로젝트: {p.project_id}",
            f"키워드: {p.get('keyword')}",
            f"제목: {content.get('title', '')}",
            f"글자수: {len(content.get('body', ''))}자",
            f"리비전: {p.get('revision_count', 0)}회",
            f"AI 검수: {review.get('score', '-')}점",
            f"\n--- 본문 미리보기 ---",
            content.get("body", "(없음)")[:300],
            f"\n--- 댓글 ---",
            content.get("comments", "(없음)")[:200],
        ])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--keyword", required=True)
    p.add_argument("--product-name", required=True)
    p.add_argument("--brand-keyword", required=True)
    p.add_argument("--usp", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--ingredients", default="")
    p.add_argument("--resume", action="store_true")
    args = p.parse_args()

    pipeline = CafeSeoPipeline()
    if args.resume:
        pipeline.resume(args)
    else:
        pipeline.run(args)


if __name__ == "__main__":
    main()
