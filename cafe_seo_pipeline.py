"""카페SEO 파이프라인 — /cafe-seo 커맨드에서 호출. 끝까지 자동 실행."""
import argparse, requests, json, re, sys
from datetime import datetime

BASE = "http://localhost:8000"
MAX_REVISIONS = 3

AD_WORDS = [
    "강추", "대박", "최고의", "미쳤다", "완전 좋", "꼭 사세요",
    "인생템", "갓", "킹", "찐", "레전드", "넘사벽", "역대급",
    "무조건 사야", "안 사면 후회",
]


def parse_sse_stream(response):
    results = []
    for line in response.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            try:
                results.append(json.loads(line[6:]))
            except Exception:
                pass
    return results


def get_data(results, type_key):
    for r in reversed(results):
        if r.get("type") == type_key:
            return r
    return None


def rule_validate(body, keyword, comments_text):
    """규칙 검수. 실패 항목 리스트 반환. 빈 리스트 = PASS."""
    errors = []

    # 글자수 체크 (800~1500)
    c = len(body)
    if c < 800:
        errors.append(f"글자수 부족: {c}자 (최소 800)")
    if c > 1500:
        errors.append(f"글자수 초과: {c}자 (최대 1500)")

    # 키워드 횟수 체크 (3~6회)
    kw_count = body.lower().count(keyword.lower())
    if kw_count < 3:
        errors.append(f"키워드 부족: {kw_count}회 (최소 3회)")
    if kw_count > 6:
        errors.append(f"키워드 과다: {kw_count}회 (최대 6회)")

    # 댓글 3개 이상
    comment_lines = [l.strip() for l in comments_text.strip().split("\n") if l.strip()]
    if len(comment_lines) < 3:
        errors.append(f"댓글 부족: {len(comment_lines)}개 (최소 3개)")

    # 광고성 표현 체크
    for w in AD_WORDS:
        if w in body:
            errors.append(f"광고성 표현 발견: '{w}'")
            break

    return errors


def run(args):
    keyword = args.keyword
    product = {
        "name": args.product_name,
        "brand_keyword": args.brand_keyword,
        "usp": args.usp,
        "target": args.target,
        "ingredients": args.ingredients,
    }

    # -- 서버 확인 --
    try:
        r = requests.get(BASE, timeout=5)
        if r.status_code != 200:
            print("서버 응답 없음")
            sys.exit(1)
    except Exception:
        print("서버 연결 실패 (http://localhost:8000)")
        sys.exit(1)

    # -- STEP 1-2: 생성 + 검수 루프 --
    title = ""
    body = ""
    comments = ""
    char_count = 0
    revision = 0

    while revision <= MAX_REVISIONS:
        tag = f" (리비전 {revision})" if revision > 0 else ""
        print(f"\nSTEP 1: 카페SEO 원고 생성{tag}...")

        payload = {
            "keywords": [{"keyword": keyword, "page_id": ""}],
            "product": product,
        }
        r = requests.post(f"{BASE}/api/cafe/generate",
                          json=payload, stream=True, timeout=300)
        results = parse_sse_stream(r)
        result_d = get_data(results, "result")
        if not result_d:
            err = get_data(results, "error")
            print(f"생성 실패: {err}")
            sys.exit(1)

        data = result_d.get("data", result_d)
        title = data.get("title", "")
        body = data.get("body", "")
        comments = data.get("comments", "")
        char_count = len(body)
        kw_count = body.lower().count(keyword.lower())
        print(f"  생성 완료: 제목={title[:40]}... | {char_count}자 | 키워드 {kw_count}회")

        print("STEP 2: 규칙 검수...")
        errs = rule_validate(body, keyword, comments)
        if errs:
            print(f"  FAIL: {errs}")
            revision += 1
            if revision > MAX_REVISIONS:
                print(f"  {MAX_REVISIONS}회 초과. 현재 버전 사용.")
                break
            print(f"  -> 리비전 {revision}/{MAX_REVISIONS}")
            continue
        print(f"  PASS: {char_count}자, 키워드 {kw_count}회")
        break

    # -- STEP 3: job_state 저장 --
    state_path = "/Users/iconlms/Desktop/안티그래비티/job_state.json"
    try:
        state = json.load(open(state_path))
    except Exception:
        state = {"jobs": []}

    kw_count = body.lower().count(keyword.lower())
    comment_lines = [l.strip() for l in comments.strip().split("\n") if l.strip()]

    job = {
        "job_id": f"cafe-seo-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "channel": "cafe_seo",
        "status": "approved",
        "keyword": keyword,
        "title": title,
        "dedup_key": f"cafe_seo:{keyword}:{datetime.now().strftime('%Y%m%d')}",
        "revision_count": revision,
        "char_count": char_count,
        "keyword_count": kw_count,
        "comment_count": len(comment_lines),
        "manual_version": "cafe-seo-v1",
        "prompt_version": datetime.now().strftime("%Y-%m-%d"),
        "created_at": datetime.now().isoformat(),
    }
    state["jobs"].append(job)
    with open(state_path, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    # -- 최종 보고 --
    print("\n" + "=" * 60)
    print("최종 보고")
    print("=" * 60)
    print(f"키워드: {keyword}")
    print(f"제목: {title}")
    print(f"글자수: {char_count}자 | 키워드: {kw_count}회 | 댓글: {len(comment_lines)}개 | 리비전: {revision}회")
    print(f"\n--- 본문 (앞 500자) ---")
    print(body[:500])
    if len(body) > 500:
        print(f"\n... (총 {len(body)}자)")
    print(f"\n--- 댓글 ---")
    for cl in comment_lines[:5]:
        print(f"  {cl}")
    if len(comment_lines) > 5:
        print(f"  ... 외 {len(comment_lines) - 5}개")
    print(f"\n저장: {job['job_id']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--keyword", required=True)
    p.add_argument("--product-name", required=True)
    p.add_argument("--brand-keyword", required=True)
    p.add_argument("--usp", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--ingredients", required=True)
    run(p.parse_args())
