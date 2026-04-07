"""파워컨텐츠 파이프라인 — /powercontent 커맨드에서 호출. 끝까지 자동 실행."""
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


def rule_validate(ad_title, ad_desc, body, keyword, char_count=None):
    """규칙 검수. 실패 항목 리스트 반환. 빈 리스트 = PASS."""
    errors = []

    # 글자수 체크 (3000자 이상)
    c = char_count if char_count is not None else len(body)
    if c < 3000:
        errors.append(f"글자수 부족: {c}자 (최소 3000)")

    # 키워드 횟수 체크 (10회 이상)
    kw = body.lower().count(keyword.lower())
    if kw < 10:
        errors.append(f"키워드 부족: {kw}회 (최소 10회)")

    # 광고 제목 존재 체크
    if not ad_title or len(ad_title.strip()) < 2:
        errors.append("광고 제목 없음")

    # 광고 설명 존재 체크
    if not ad_desc or len(ad_desc.strip()) < 2:
        errors.append("광고 설명 없음")

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
    ad_title = ""
    ad_desc = ""
    body = ""
    char_count = 0
    revision = 0

    while revision <= MAX_REVISIONS:
        tag = f" (리비전 {revision})" if revision > 0 else ""
        print(f"\nSTEP 1: 파워컨텐츠 생성{tag}...")

        payload = {
            "keyword": keyword,
            "product": product,
            "appeal": args.appeal,
            "buying_thing": args.buying_thing,
            "deficit_level": args.deficit_level,
            "stage": args.stage,
            "hooking_type": args.hooking_type,
            "forbidden": args.forbidden,
        }
        r = requests.post(f"{BASE}/api/powercontent/generate",
                          json=payload, stream=True, timeout=300)
        results = parse_sse_stream(r)

        # 에러 체크
        err = get_data(results, "error")
        if err:
            print(f"생성 실패: {err.get('message', err)}")
            sys.exit(1)

        # result 이벤트에서 데이터 추출
        result_d = get_data(results, "result")
        if not result_d:
            # ad 이벤트에서라도 추출 시도
            ad_d = get_data(results, "ad")
            if ad_d:
                ad_title = ad_d.get("title", "")
                ad_desc = ad_d.get("desc", "")
            print(f"result 이벤트 없음. 수신 이벤트: {[r.get('type') for r in results]}")
            revision += 1
            if revision > MAX_REVISIONS:
                print(f"  {MAX_REVISIONS}회 초과. 생성 실패.")
                sys.exit(1)
            continue

        ad_title = result_d.get("ad_title", "")
        ad_desc = result_d.get("ad_desc", "")
        body = result_d.get("body", "")
        char_count = result_d.get("char_count", len(body))
        kw_count = body.lower().count(keyword.lower())

        print(f"  생성 완료: 광고제목={ad_title[:30]}... | {char_count}자 | 키워드 {kw_count}회")

        print("STEP 2: 규칙 검수...")
        errs = rule_validate(ad_title, ad_desc, body, keyword, char_count)
        if errs:
            print(f"  FAIL: {errs}")
            revision += 1
            if revision > MAX_REVISIONS:
                print(f"  {MAX_REVISIONS}회 초과. 현재 버전 사용.")
                break
            print(f"  -> 리비전 {revision}/{MAX_REVISIONS}")
            continue
        print(f"  PASS: {char_count}자, 키워드 {kw_count}회, 광고카피 존재")
        break

    kw_count = body.lower().count(keyword.lower())

    # -- STEP 3: job_state 저장 --
    state_path = "/Users/iconlms/Desktop/안티그래비티/job_state.json"
    try:
        with open(state_path) as f:
            state = json.load(f)
    except Exception:
        state = {"jobs": []}

    job = {
        "job_id": f"powercontent-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "channel": "powercontent",
        "status": "approved",
        "keyword": keyword,
        "ad_title": ad_title,
        "ad_desc": ad_desc,
        "dedup_key": f"powercontent:{keyword}:{datetime.now().strftime('%Y%m%d')}",
        "revision_count": revision,
        "char_count": char_count,
        "keyword_count": kw_count,
        "manual_version": "powercontent-v1",
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
    print(f"광고 제목: {ad_title}")
    print(f"광고 설명: {ad_desc}")
    print(f"글자수: {char_count}자 | 키워드: {kw_count}회 | 리비전: {revision}회")
    print(f"\n--- 본문 (앞 500자) ---")
    print(body[:500])
    if len(body) > 500:
        print(f"\n... (총 {len(body)}자)")
    print(f"\n저장: {job['job_id']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="파워컨텐츠 파이프라인")
    p.add_argument("--keyword", required=True)
    p.add_argument("--product-name", required=True)
    p.add_argument("--brand-keyword", required=True)
    p.add_argument("--usp", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--ingredients", required=True)
    p.add_argument("--appeal", default="")
    p.add_argument("--buying-thing", default="")
    p.add_argument("--deficit-level", default="중")
    p.add_argument("--stage", default="탐색")
    p.add_argument("--hooking-type", default="궁금증")
    p.add_argument("--forbidden", default="")
    run(p.parse_args())
