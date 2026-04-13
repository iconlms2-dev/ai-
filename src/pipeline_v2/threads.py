"""쓰레드 v2 파이프라인 — 벤치마킹→키워드→콘텐츠 생성→검수→저장."""
import argparse
import logging
from datetime import datetime

from .base_pipeline import BasePipeline
from .state_machine import ProjectState
from .common import call_api, get_event, print_report
from .rule_validators import validate_threads

logger = logging.getLogger(__name__)


class ThreadsPipeline(BasePipeline):
    channel = "threads"
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
        keywords = args.keywords.split(",") if isinstance(args.keywords, str) else args.keywords
        return {
            "type": args.type,
            "keywords": keywords,
            "product": args.product,
            "selling_logic": args.selling_logic,
            "forbidden": args.forbidden,
            "count": args.count,
            "dedup_key": f"threads:{keywords[0] if keywords else ''}:{datetime.now().strftime('%Y%m%d')}",
        }

    def execute_step(self, step: str, args):
        p = self.project

        if step == "00_input":
            p.save_step_file("00_input", "input.json", {
                "type": p.get("type"),
                "keywords": p.get("keywords"),
                "product": p.get("product"),
                "selling_logic": p.get("selling_logic"),
                "forbidden": p.get("forbidden"),
                "count": p.get("count", 1),
            })

        elif step == "01_benchmark":
            keywords = p.get("keywords", [])
            try:
                from src.services.benchmark import crawl_threads_references
                refs = crawl_threads_references(keywords=keywords, max_posts=5)
                if refs:
                    print(f"  Threads 인기 게시물 {len(refs)}개 수집 완료")
                    avg_chars = sum(r["char_count"] for r in refs) // len(refs)
                    avg_hashtags = sum(r["hashtag_count"] for r in refs) / len(refs)
                    data = {
                        "references": refs,
                        "patterns": {
                            "avg_char_count": avg_chars,
                            "avg_hashtag_count": round(avg_hashtags, 1),
                            "avg_likes": sum(r["likes"] for r in refs) // len(refs),
                        },
                    }
                else:
                    print("  Threads 벤치마킹 데이터 없음 — 스킵")
                    data = {"skipped": True, "reason": "데이터 없음"}
            except Exception as e:
                logger.warning("Threads 벤치마킹 오류: %s", e)
                print(f"  벤치마킹 오류 — 스킵: {e}")
                data = {"skipped": True, "reason": str(e)}
            p.save_step_file("01_benchmark", "references.json", data)

        elif step == "02_strategy":
            data = self.do_strategy(args)
            p.save_step_file("02_strategy", "strategy.json", data)

        elif step == "03_brief":
            brief = self.do_brief(args)
            p.save_step_file("03_brief", "brief.md", brief or "", as_json=False)

        elif step == "04_write":
            content_type = p.get("type")
            keywords = p.get("keywords", [])
            product = p.get("product")
            selling_logic = p.get("selling_logic")
            forbidden = p.get("forbidden")
            count = p.get("count", 1)

            def write_fn(_):
                payload = {
                    "type": content_type,
                    "account_id": "",
                    "keywords": keywords,
                    "product": product,
                    "selling_logic": selling_logic,
                    "forbidden": forbidden,
                    "count": count,
                    "ref_posts": [],
                }
                results = call_api("/api/threads/generate", payload, timeout=300)
                result_d = get_event(results, "result")
                if not result_d:
                    err = get_event(results, "error")
                    raise RuntimeError(f"생성 실패: {err}")
                data = result_d.get("data", result_d)
                text = data.get("full_text", data.get("text", ""))
                return {"text": text}

            def validate_fn(content):
                return validate_threads(content["text"])

            content, revision = self.revision_loop(args, write_fn, validate_fn)
            p.save_step_file("04_write", "draft.json", content)
            p.save_step_file("04_write", "post.md", content["text"], as_json=False)
            p.update(revision_count=revision)
            print(f"  {len(content['text'])}자 | 리비전 {revision}회")

        elif step == "05_review":
            content = p.load_step_file("04_write", "draft.json")
            if content:
                from .common import ai_review
                result = ai_review(content["text"], "threads", {
                    "자연스러움": 7, "설득력": 6, "채널적합도": 7,
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

        print_report("쓰레드 v2 최종 보고", [
            f"프로젝트: {p.project_id}",
            f"유형: {p.get('type')}",
            f"글자수: {len(content.get('text', ''))}자",
            f"리비전: {p.get('revision_count', 0)}회",
            f"AI 검수: {review.get('score', '-')}점",
            f"\n--- 본문 ---",
            content.get("text", "(없음)")[:500],
        ])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--type", required=True, help="콘텐츠 유형")
    p.add_argument("--keywords", required=True, help="쉼표 구분 키워드")
    p.add_argument("--product", required=True)
    p.add_argument("--selling-logic", required=True)
    p.add_argument("--forbidden", default="")
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--resume", action="store_true")
    args = p.parse_args()

    pipeline = ThreadsPipeline()
    if args.resume:
        pipeline.resume(args)
    else:
        pipeline.run(args)


if __name__ == "__main__":
    main()
