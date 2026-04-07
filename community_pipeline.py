"""커뮤니티 침투 파이프라인 — /community 커맨드에서 호출. 끝까지 자동 실행."""
import argparse, requests, json, re, sys
from datetime import datetime

BASE = "http://localhost:8000"
MAX_RETRIES = 3

AD_PATTERNS = [
    r'광고', r'협찬', r'제공받', r'체험단', r'원고료',
    r'링크\s*클릭', r'할인\s*코드', r'쿠폰\s*코드',
    r'구매\s*링크', r'바로\s*가기',
]


def parse_sse_stream(response):
    """SSE 스트림에서 JSON 이벤트 추출."""
    results = []
    for line in response.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            try:
                results.append(json.loads(line[6:]))
            except Exception:
                pass
    return results


def get_data(results, type_key):
    """결과 리스트에서 특정 type의 마지막 이벤트 반환."""
    for r in reversed(results):
        if r.get("type") == type_key:
            return r
    return None


def rule_validate(post_body, comments_text):
    """규칙 검수. 실패 항목 리스트 반환. 빈 리스트 = PASS."""
    errors = []

    # 1) 게시글 200자 이상
    post_len = len(post_body.strip())
    if post_len < 200:
        errors.append(f"게시글 글자수 부족: {post_len}자 (최소 200)")

    # 2) 댓글 3개 이상
    comment_lines = [l.strip() for l in comments_text.strip().split("\n") if l.strip()]
    if len(comment_lines) < 3:
        errors.append(f"댓글 부족: {len(comment_lines)}개 (최소 3)")

    # 3) 광고성 표현 없음
    full_text = post_body + " " + comments_text
    for pat in AD_PATTERNS:
        if re.search(pat, full_text):
            errors.append(f"광고성 표현 발견: {pat}")
            break

    return errors


def run(args):
    community = args.community
    strategy = args.strategy
    keyword = args.keyword
    appeal = args.appeal
    buying_one = args.buying_one
    product = {
        "name": args.product_name,
        "brand_keyword": args.brand_keyword,
        "usp": args.usp,
        "target": args.target,
        "ingredients": args.ingredients,
    }
    forbidden = args.forbidden

    # ── 서버 확인 ──
    try:
        r = requests.get(BASE, timeout=5)
        if r.status_code != 200:
            print("서버 응답 없음")
            sys.exit(1)
    except Exception:
        print("서버 연결 실패 (http://localhost:8000)")
        sys.exit(1)

    # ── STEP 1~3: 생성 + 검수 루프 ──
    post_body = ""
    post_title = ""
    comments_text = ""
    revision = 0

    while revision <= MAX_RETRIES:
        tag = f" (재시도 {revision})" if revision > 0 else ""
        print(f"\nSTEP 1: 침투글 + 댓글 생성{tag}...")

        payload = {
            "keywords": [keyword],
            "community": community,
            "strategy": strategy,
            "product": product,
            "appeal": appeal,
            "buying_one": buying_one,
            "forbidden": forbidden,
            "include_comments": True,
        }

        r = requests.post(f"{BASE}/api/community/generate",
                          json=payload,
                          stream=True, timeout=180)
        results = parse_sse_stream(r)

        # 에러 체크
        err_evt = get_data(results, "error")
        if err_evt:
            print(f"  API 에러: {err_evt.get('message', '알 수 없음')}")
            revision += 1
            if revision > MAX_RETRIES:
                print(f"  {MAX_RETRIES}회 초과. 중단.")
                sys.exit(1)
            continue

        # result 추출
        result_evt = get_data(results, "result")
        if not result_evt:
            print("  결과 이벤트 없음")
            revision += 1
            if revision > MAX_RETRIES:
                print(f"  {MAX_RETRIES}회 초과. 중단.")
                sys.exit(1)
            continue

        data = result_evt.get("data", {})
        post_title = data.get("title", "")
        post_body = data.get("body", "")
        comments_text = data.get("comments", "")

        print(f"  생성 완료: 제목 {len(post_title)}자 / 본문 {len(post_body)}자 / 댓글 {len(comments_text)}자")

        # STEP 2: 규칙 검수
        print("STEP 2: 규칙 검수...")
        errs = rule_validate(post_body, comments_text)
        if errs:
            print(f"  FAIL: {errs}")
            revision += 1
            if revision > MAX_RETRIES:
                print(f"  {MAX_RETRIES}회 초과. 현재 버전 사용.")
                break
            print(f"  -> 재시도 {revision}/{MAX_RETRIES}")
            continue
        print(f"  PASS: 본문 {len(post_body)}자, 댓글 OK, 광고성 없음")
        break

    # ── 댓글 파싱 ──
    comment_lines = [l.strip() for l in comments_text.strip().split("\n") if l.strip()]

    # ── STEP 3: job_state.json 저장 ──
    print("\nSTEP 3: job_state 저장...")
    state_path = "/Users/iconlms/Desktop/안티그래비티/job_state.json"
    try:
        state = json.load(open(state_path))
    except Exception:
        state = {"jobs": []}

    job = {
        "job_id": f"community-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "channel": "community",
        "status": "approved",
        "community": community,
        "strategy": strategy,
        "keyword": keyword,
        "dedup_key": f"community:{community}:{keyword}:{datetime.now().strftime('%Y%m%d')}",
        "revision_count": revision,
        "post_char_count": len(post_body),
        "comment_count": len(comment_lines),
        "manual_version": "community-v1",
        "prompt_version": datetime.now().strftime("%Y-%m-%d"),
        "created_at": datetime.now().isoformat(),
    }
    state["jobs"].append(job)
    with open(state_path, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    # ── 최종 보고 ──
    print("\n" + "=" * 60)
    print("최종 보고")
    print("=" * 60)
    print(f"커뮤니티: {community} | 전략: {strategy}")
    print(f"키워드: {keyword}")
    print(f"본문: {len(post_body)}자 | 댓글: {len(comment_lines)}개 | 재시도: {revision}회")
    print(f"\n--- 제목 ---")
    print(post_title)
    print(f"\n--- 게시글 ---")
    print(post_body)
    print(f"\n--- 댓글 ({len(comment_lines)}개) ---")
    for i, c in enumerate(comment_lines, 1):
        print(f"  {i}. {c}")
    print(f"\n저장 완료: {job['job_id']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="커뮤니티 침투 파이프라인")
    p.add_argument("--community", required=True, help="뽐뿌/클리앙/디시/루리웹 등")
    p.add_argument("--strategy", required=True, help="전략 번호 1~4")
    p.add_argument("--keyword", required=True, help="키워드")
    p.add_argument("--appeal", required=True, help="소구점")
    p.add_argument("--buying-one", required=True, dest="buying_one", help="구매원씽")
    p.add_argument("--product-name", required=True, dest="product_name", help="제품명")
    p.add_argument("--brand-keyword", required=True, dest="brand_keyword", help="브랜드 키워드")
    p.add_argument("--usp", required=True, help="USP")
    p.add_argument("--target", required=True, help="타겟")
    p.add_argument("--ingredients", required=True, help="성분")
    p.add_argument("--forbidden", default="", help="금지어")
    run(p.parse_args())
