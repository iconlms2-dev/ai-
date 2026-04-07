"""블로그 파이프라인 — /blog 커맨드에서 호출. 끝까지 자동 실행."""
import argparse, requests, json, re, sys
from datetime import datetime

BASE = "http://localhost:8000"
MAX_REVISIONS = 3


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


def rule_validate(title, body, keyword, char_count=None, keyword_count=None):
    """규칙 검수. 실패 항목 리스트 반환. 빈 리스트 = PASS."""
    errors = []

    # 글자수 체크 (SSE에서 넘어온 값 우선, 없으면 직접 계산)
    c = char_count if char_count is not None else len(body)
    if c < 2200:
        errors.append(f"글자수 부족: {c}자 (최소 2200)")

    # 키워드 횟수 체크
    kw = keyword_count if keyword_count is not None else (body.lower().count(keyword.lower()) + title.lower().count(keyword.lower()))
    if kw < 8:
        errors.append(f"키워드 부족: {kw}회 (최소 8회)")

    # 소제목 체크: ## 또는 **소제목** 패턴
    subtitle_patterns = re.findall(r'(?:^|\n)\s*##\s+.+|(?:^|\n)\s*\*\*[^*]+\*\*', body)
    paragraph_count = len([p for p in body.split('\n\n') if p.strip()])
    if len(subtitle_patterns) < 4 and paragraph_count < 8:
        errors.append(f"소제목 {len(subtitle_patterns)}개, 문단 {paragraph_count}개 (소제목 4개+ 또는 문단 8개+ 필요)")

    # [사진] 태그 체크 ([이미지N] 패턴도 허용)
    has_photo = '[사진]' in body or '(사진)' in body or bool(re.search(r'\[이미지\d*\]', body))
    if not has_photo:
        errors.append("[사진] 또는 [이미지] 태그 없음")

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
    char_count = 0
    keyword_count = 0
    revision = 0

    while revision <= MAX_REVISIONS:
        tag = f" (리비전 {revision})" if revision > 0 else ""
        print(f"\nSTEP 1: 블로그 원고 생성{tag}...")

        payload = {
            "keywords": [{"keyword": keyword, "page_id": ""}],
            "product": product,
        }
        r = requests.post(f"{BASE}/api/blog/generate",
                          json=payload, stream=True, timeout=300)
        results = parse_sse_stream(r)
        result_d = get_data(results, "result")
        if not result_d:
            err = get_data(results, "error")
            print(f"생성 실패: {err}")
            sys.exit(1)

        # result 이벤트의 data 필드 안에 실제 데이터가 있음
        data = result_d.get("data", result_d)
        title = data.get("title", "")
        body = data.get("body", "")
        char_count = data.get("char_count", len(body))
        keyword_count = data.get("actual_repeat", data.get("keyword_count", 0))
        print(f"  생성 완료: 제목={title[:40]}... | {char_count}자 | 키워드 {keyword_count}회")

        print("STEP 2: 규칙 검수...")
        errs = rule_validate(title, body, keyword, char_count, keyword_count)
        if errs:
            print(f"  FAIL: {errs}")
            revision += 1
            if revision > MAX_REVISIONS:
                print(f"  {MAX_REVISIONS}회 초과. 현재 버전 사용.")
                break
            print(f"  -> 리비전 {revision}/{MAX_REVISIONS}")
            continue
        print(f"  PASS: {char_count}자, 키워드 {keyword_count}회")
        break

    # -- STEP 3: job_state 저장 --
    state_path = "/Users/iconlms/Desktop/안티그래비티/job_state.json"
    try:
        state = json.load(open(state_path))
    except Exception:
        state = {"jobs": []}

    job = {
        "job_id": f"blog-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "channel": "blog",
        "status": "approved",
        "keyword": keyword,
        "title": title,
        "dedup_key": f"blog:{keyword}:{datetime.now().strftime('%Y%m%d')}",
        "revision_count": revision,
        "char_count": char_count,
        "keyword_count": keyword_count,
        "manual_version": "blog-v1",
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
    print(f"글자수: {char_count}자 | 키워드: {keyword_count}회 | 리비전: {revision}회")
    print(f"\n--- 본문 (앞 500자) ---")
    print(body[:500])
    if len(body) > 500:
        print(f"\n... (총 {len(body)}자)")
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
