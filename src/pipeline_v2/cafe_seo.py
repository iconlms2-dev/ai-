"""카페SEO v3 파이프라인 — 크롤링→제목→본문→댓글+답글→사진→Polish→검수→저장."""
import argparse
from datetime import datetime

from .base_pipeline import BasePipeline
from .state_machine import ProjectState
from .common import call_api, call_api_json, get_event, print_report
from .rule_validators import validate_cafe_seo


class CafeSeoPipeline(BasePipeline):
    channel = "cafe_seo"
    steps = [
        "00_input",
        "01_crawl",        # 상위글 크롤링+분석
        "02_title",        # 제목 리라이팅
        "03_body",         # 본문 생성
        "04_comment",      # 댓글 10개 + 답글 10개
        "04b_photo",       # 사진 매칭
        "05_polish",       # 금칙어 대체 + 타사치환 + 문체 보정
        "06_review",       # 규칙검수 + AI검수
        "07_save",         # 노션 저장
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
                "forbidden": getattr(args, 'forbidden', ''),
            },
            "sub_keywords": getattr(args, 'sub_keywords', ''),
            "competitor_url": getattr(args, 'competitor_url', ''),
            "dedup_key": f"cafe_seo:{args.keyword}:{datetime.now().strftime('%Y%m%d')}",
        }

    def execute_step(self, step: str, args):
        p = self.project

        if step == "00_input":
            p.save_step_file("00_input", "input.json", {
                "keyword": p.get("keyword"),
                "product": p.get("product"),
                "sub_keywords": p.get("sub_keywords", ""),
                "competitor_url": p.get("competitor_url", ""),
            })

        elif step == "01_crawl":
            # 상위글 크롤링 + 분석은 generate 엔드포인트가 통합 처리
            data = self.do_benchmark(args)
            p.save_step_file("01_crawl", "references.json", data)

        elif step == "02_title":
            data = self.do_strategy(args)
            p.save_step_file("02_title", "strategy.json", data)

        elif step == "03_body":
            brief = self.do_brief(args)
            p.save_step_file("03_body", "brief.md", brief or "", as_json=False)

        elif step == "04_comment":
            keyword = p.get("keyword")
            product = p.get("product")

            def write_fn(_):
                payload = {
                    "keywords": [{"keyword": keyword, "page_id": ""}],
                    "product": product,
                }
                results = call_api("/api/cafe/generate", payload, timeout=600)
                result_d = get_event(results, "result")
                if not result_d:
                    err = get_event(results, "error")
                    raise RuntimeError(f"생성 실패: {err}")
                data = result_d.get("data", result_d)
                return {
                    "title": data.get("title", ""),
                    "body": data.get("body", ""),
                    "comments": data.get("comments", ""),
                    "replies": data.get("replies", ""),
                    "images": data.get("images", []),
                    "polish_changes": data.get("polish_changes", []),
                }

            def validate_fn(content):
                return validate_cafe_seo(
                    content["body"], keyword, content.get("comments", ""),
                    replies_text=content.get("replies", ""),
                    sub_keywords=p.get("sub_keywords", ""),
                )

            content, revision = self.revision_loop(args, write_fn, validate_fn)
            p.save_step_file("04_comment", "draft.json", content)
            p.update(revision_count=revision)
            body_len = len(content.get('body', ''))
            replies_len = len(content.get('replies', ''))
            print(f"  본문 {body_len}자 | 답글 {replies_len}자 | 리비전 {revision}회")

        elif step == "04b_photo":
            content = p.load_step_file("04_comment", "draft.json")
            if content and content.get("images"):
                p.save_step_file("04b_photo", "photos.json", {
                    "images": content.get("images", []),
                    "matched_at": datetime.now().isoformat(),
                })
                print(f"  사진 {len(content.get('images', []))}장 매칭 완료")
            else:
                p.save_step_file("04b_photo", "photos.json", {"images": []})

        elif step == "05_polish":
            content = p.load_step_file("04_comment", "draft.json")
            if content and content.get("polish_changes"):
                p.save_step_file("05_polish", "polish.json", {
                    "changes": content.get("polish_changes", []),
                    "polished_at": datetime.now().isoformat(),
                })
                print(f"  Polish 변경 {len(content.get('polish_changes', []))}건")
            else:
                p.save_step_file("05_polish", "polish.json", {"changes": []})

        elif step == "06_review":
            content = p.load_step_file("04_comment", "draft.json")
            if content:
                from .common import ai_review
                result = ai_review(content["body"], "cafe_seo", {
                    "자연스러움": 7, "SEO적합도": 7, "댓글품질": 6, "답글싱크": 6,
                })
                p.save_step_file("06_review", "review.json", result)
                print(f"  AI 검수: {'PASS' if result['pass'] else 'FAIL'} (점수: {result['score']})")
                p.transition("under_review")
                if result["pass"]:
                    p.transition("approved")

        elif step == "07_save":
            p.save_step_file("07_save", "saved.json", {
                "saved_at": datetime.now().isoformat(),
                "status": "completed",
            })

    def finalize(self, args):
        p = self.project
        content = p.load_step_file("04_comment", "draft.json") or {}
        review = p.load_step_file("06_review", "review.json") or {}
        polish = p.load_step_file("05_polish", "polish.json") or {}

        print_report("카페SEO v3 최종 보고", [
            f"프로젝트: {p.project_id}",
            f"키워드: {p.get('keyword')}",
            f"제목: {content.get('title', '')}",
            f"글자수: {len(content.get('body', ''))}자",
            f"리비전: {p.get('revision_count', 0)}회",
            f"AI 검수: {review.get('score', '-')}점",
            f"Polish 변경: {len(polish.get('changes', []))}건",
            f"사진: {len(content.get('images', []))}장",
            f"\n--- 본문 미리보기 ---",
            content.get("body", "(없음)")[:300],
            f"\n--- 댓글 ---",
            content.get("comments", "(없음)")[:200],
            f"\n--- 답글 미리보기 ---",
            content.get("replies", "(없음)")[:200],
        ])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--keyword", required=True)
    p.add_argument("--product-name", required=True)
    p.add_argument("--brand-keyword", required=True)
    p.add_argument("--usp", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--ingredients", default="")
    p.add_argument("--forbidden", default="", help="금칙어 목록 (쉼표 구분)")
    p.add_argument("--sub-keywords", default="", help="서브 키워드 (쉼표 구분)")
    p.add_argument("--competitor-url", default="", help="경쟁사 글 URL")
    p.add_argument("--resume", action="store_true")
    args = p.parse_args()

    pipeline = CafeSeoPipeline()
    if args.resume:
        pipeline.resume(args)
    else:
        pipeline.run(args)


if __name__ == "__main__":
    main()
