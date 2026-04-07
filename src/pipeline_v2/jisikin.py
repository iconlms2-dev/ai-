"""지식인 v2 파이프라인 — 키워드→질문+답변 생성→검수→Notion 저장."""
import argparse
from datetime import datetime

from .base_pipeline import BasePipeline
from .state_machine import ProjectState
from .common import call_api, get_event, print_report
from .rule_validators import validate_jisikin


class JisikinPipeline(BasePipeline):
    channel = "jisikin"
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
            "dedup_key": f"jisikin:{args.keyword}:{datetime.now().strftime('%Y%m%d')}",
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
                results = call_api("/api/jisikin/generate", payload, timeout=300)
                result_d = get_event(results, "result")
                if not result_d:
                    err = get_event(results, "error")
                    raise RuntimeError(f"생성 실패: {err}")
                data = result_d.get("data", result_d)
                return {
                    "q_title": data.get("q_title", ""),
                    "q_body": data.get("q_body", ""),
                    "answer1": data.get("answer1", ""),
                    "answer2": data.get("answer2", ""),
                }

            def validate_fn(content):
                return validate_jisikin(
                    content["q_title"], content["q_body"],
                    content["answer1"], content["answer2"], keyword,
                )

            content, revision = self.revision_loop(args, write_fn, validate_fn)
            p.save_step_file("04_write", "draft.json", content)
            p.update(revision_count=revision)
            print(f"  답변1: {len(content['answer1'])}자 | 답변2: {len(content['answer2'])}자 | 리비전 {revision}회")

        elif step == "05_review":
            content = p.load_step_file("04_write", "draft.json")
            if content:
                combined = content["answer1"] + "\n" + content["answer2"]
                from .common import ai_review
                result = ai_review(combined, "jisikin", {
                    "전문성": 7, "자연스러움": 7, "키워드적합도": 6,
                })
                p.save_step_file("05_review", "review.json", result)
                print(f"  AI 검수: {'PASS' if result['pass'] else 'FAIL'} (점수: {result['score']})")
                p.transition("under_review")
                if result["pass"]:
                    p.transition("approved")

        elif step == "06_save":
            content = p.load_step_file("04_write", "draft.json")
            saved = False
            if content:
                saved = self.do_save_notion("/api/jisikin/save-notion", {
                    "keyword": p.get("keyword"),
                    "q_title": content.get("q_title", ""),
                    "q_body": content.get("q_body", ""),
                    "answer1": content.get("answer1", ""),
                    "answer2": content.get("answer2", ""),
                })
            p.save_step_file("06_save", "saved.json", {
                "saved_at": datetime.now().isoformat(),
                "status": "completed" if saved else "save_failed",
                "notion_saved": saved,
            })

    def _extract_review_text(self, content: dict) -> str:
        return content.get("answer1", "") + "\n" + content.get("answer2", "")

    def finalize(self, args):
        p = self.project
        content = p.load_step_file("04_write", "draft.json") or {}
        review = p.load_step_file("05_review", "review.json") or {}

        print_report("지식인 v2 최종 보고", [
            f"프로젝트: {p.project_id}",
            f"키워드: {p.get('keyword')}",
            f"질문: {content.get('q_title', '')}",
            f"답변1: {len(content.get('answer1', ''))}자",
            f"답변2: {len(content.get('answer2', ''))}자",
            f"리비전: {p.get('revision_count', 0)}회",
            f"AI 검수: {review.get('score', '-')}점",
            f"\n--- 질문 ---",
            content.get("q_title", "") + "\n" + content.get("q_body", "(없음)")[:200],
            f"\n--- 답변1 미리보기 ---",
            content.get("answer1", "(없음)")[:300],
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

    pipeline = JisikinPipeline()
    if args.resume:
        pipeline.resume(args)
    else:
        pipeline.run(args)


if __name__ == "__main__":
    main()
