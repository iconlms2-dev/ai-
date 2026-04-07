"""유튜브 댓글 v2 파이프라인 — 영상 검색→정보 수집→댓글 생성→검수→저장."""
import argparse
import re
from datetime import datetime

from .base_pipeline import BasePipeline
from .state_machine import ProjectState
from .common import (
    call_api, call_api_json, get_event, get_all_events, print_report,
)
from .rule_validators import validate_youtube_comment


def _parse_comments_from_text(comment_text: str) -> list[str]:
    """3단 시나리오 텍스트에서 개별 댓글 추출."""
    comments = []

    # 방법1: "댓글N:" 헤더 기반
    pattern = r'댓글\d[^:]*:\s*\n(.*?)(?=\n댓글\d|$)'
    matches = re.findall(pattern, comment_text, re.DOTALL)
    if matches:
        for m in matches:
            lines = []
            for line in m.strip().split('\n'):
                s = line.strip()
                if not s:
                    continue
                if re.match(r'^\(?(밑밥|해결사|쐐기)\)?$', s):
                    continue
                lines.append(s)
            text = ' '.join(lines).strip()
            text = re.sub(r'^@\S*\s*', '', text).strip()
            if text and len(text) > 5:
                comments.append(text)

    # 방법2: 번호 기반
    if not comments:
        pattern2 = r'(?:1단계|2단계|3단계|\d+\.)[^\n]*\n(.*?)(?=(?:1단계|2단계|3단계|\d+\.)|$)'
        matches2 = re.findall(pattern2, comment_text, re.DOTALL)
        for m in matches2:
            lines = []
            for line in m.strip().split('\n'):
                s = line.strip()
                if not s or re.match(r'^\(?(밑밥|해결사|쐐기)\)?$', s):
                    continue
                lines.append(s)
            text = ' '.join(lines).strip()
            text = re.sub(r'^@\S*\s*', '', text).strip()
            if text and len(text) > 5:
                comments.append(text)

    # 방법3: 줄 기반 (최후 수단)
    if not comments:
        current = []
        for line in comment_text.strip().split('\n'):
            s = line.strip()
            if re.match(r'(댓글\d|1단계|2단계|3단계|\d+\.\s)', s):
                if current:
                    text = ' '.join(current).strip()
                    text = re.sub(r'^@\S*\s*', '', text).strip()
                    if text and len(text) > 5:
                        comments.append(text)
                current = []
            elif s and not re.match(r'^\(?(밑밥|해결사|쐐기)\)?$', s):
                current.append(s)
        if current:
            text = ' '.join(current).strip()
            text = re.sub(r'^@\S*\s*', '', text).strip()
            if text and len(text) > 5:
                comments.append(text)

    return comments


class YoutubePipeline(BasePipeline):
    channel = "youtube"
    steps = [
        "00_input",
        "01_search",
        "02_fetch_info",
        "03_write",
        "04_review",
        "05_save",
    ]

    def build_meta(self, args) -> dict:
        return {
            "keyword": args.keyword,
            "brand_keyword": args.brand_keyword,
            "count": args.count,
            "dedup_key": f"youtube:{args.keyword}:{datetime.now().strftime('%Y%m%d')}",
        }

    def execute_step(self, step: str, args):
        p = self.project

        if step == "00_input":
            p.save_step_file("00_input", "input.json", {
                "keyword": p.get("keyword"),
                "brand_keyword": p.get("brand_keyword"),
                "count": p.get("count", 3),
            })

        elif step == "01_search":
            keyword = p.get("keyword")
            result = call_api_json("/api/youtube/search-videos", {
                "keyword": keyword, "count": 5,
            }, timeout=60)
            if "error" in result:
                raise RuntimeError(f"영상 검색 에러: {result['error']}")
            videos = result.get("videos", [])
            if not videos:
                raise RuntimeError("검색 결과 없음")
            p.save_step_file("01_search", "videos.json", videos)
            print(f"  {len(videos)}개 영상 발견")

        elif step == "02_fetch_info":
            videos = p.load_step_file("01_search", "videos.json") or []
            top_videos = videos[:3]
            enriched = []
            for i, v in enumerate(top_videos):
                vid_url = v.get("url", f"https://www.youtube.com/watch?v={v.get('id', '')}")
                print(f"  [{i+1}/{len(top_videos)}] {v.get('title', '제목 없음')[:50]}")
                try:
                    info = call_api_json("/api/youtube/fetch-info", {"url": vid_url}, timeout=15)
                    enriched.append({
                        "title": info.get("title") or v.get("title", ""),
                        "description": info.get("description", ""),
                        "link": vid_url,
                        "script": info.get("transcript", ""),
                    })
                except Exception as e:
                    print(f"    정보 수집 실패: {e}")
                    enriched.append({
                        "title": v.get("title", ""),
                        "description": "",
                        "link": vid_url,
                        "script": "",
                    })
            p.save_step_file("02_fetch_info", "enriched.json", enriched)
            print(f"  상세 정보 수집 완료: {len(enriched)}개")

        elif step == "03_write":
            enriched = p.load_step_file("02_fetch_info", "enriched.json") or []
            brand_keyword = p.get("brand_keyword")
            count = p.get("count", 3)

            def write_fn(_):
                results = call_api("/api/youtube/generate", {
                    "videos": enriched,
                    "brand_keyword": brand_keyword,
                    "product_name": brand_keyword,
                }, timeout=300)
                err = get_event(results, "error")
                if err:
                    raise RuntimeError(f"댓글 생성 실패: {err.get('message', err)}")
                result_items = get_all_events(results, "result")
                if not result_items:
                    raise RuntimeError("생성 결과 없음")

                video_results = []
                for item in result_items:
                    data = item.get("data", item)
                    video_results.append({
                        "title": data.get("title", ""),
                        "link": data.get("link", ""),
                        "summary": data.get("summary", ""),
                        "comment_raw": data.get("comment", ""),
                        "comments": _parse_comments_from_text(data.get("comment", "")),
                    })
                return {"videos": video_results}

            def validate_fn(content):
                errors = []
                cnt = p.get("count", 3)
                for vr in content.get("videos", []):
                    for ci, c in enumerate(vr.get("comments", [])[:cnt]):
                        errs = validate_youtube_comment(c, vr.get("title", ""))
                        errors.extend([f"[{vr['title'][:20]}] 댓글{ci+1}: {e}" for e in errs])
                return errors

            content, revision = self.revision_loop(args, write_fn, validate_fn)
            p.save_step_file("03_write", "draft.json", content)
            p.update(revision_count=revision)
            total = sum(len(v.get("comments", [])) for v in content.get("videos", []))
            print(f"  {len(content.get('videos', []))}개 영상 / {total}개 댓글 | 리비전 {revision}회")

        elif step == "04_review":
            content = p.load_step_file("03_write", "draft.json")
            if content:
                p.transition("under_review")
                p.transition("approved")
                p.save_step_file("04_review", "review.json", {
                    "pass": True, "note": "규칙 검수 03_write에서 완료",
                })

        elif step == "05_save":
            p.save_step_file("05_save", "saved.json", {
                "saved_at": datetime.now().isoformat(),
                "status": "completed",
            })

    def _extract_review_text(self, content: dict) -> str:
        parts = []
        for v in content.get("videos", []):
            parts.extend(v.get("comments", []))
        return "\n".join(parts)

    def finalize(self, args):
        p = self.project
        content = p.load_step_file("03_write", "draft.json") or {}
        videos = content.get("videos", [])
        total = sum(len(v.get("comments", [])) for v in videos)

        lines = [
            f"프로젝트: {p.project_id}",
            f"키워드: {p.get('keyword')}",
            f"영상: {len(videos)}개",
            f"댓글: {total}개",
            f"리비전: {p.get('revision_count', 0)}회",
        ]
        for v in videos:
            lines.append(f"\n--- {v.get('title', '(없음)')[:50]} ---")
            for ci, c in enumerate(v.get("comments", [])[:3]):
                lines.append(f"  댓글{ci+1}: {c[:80]}")

        print_report("유튜브 댓글 v2 최종 보고", lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--keyword", required=True)
    p.add_argument("--brand-keyword", required=True)
    p.add_argument("--count", type=int, default=3)
    p.add_argument("--resume", action="store_true")
    args = p.parse_args()

    pipeline = YoutubePipeline()
    if args.resume:
        pipeline.resume(args)
    else:
        pipeline.run(args)


if __name__ == "__main__":
    main()
