"""쓰레드 파이프라인 -- /threads 커맨드에서 호출. 끝까지 자동 실행."""
import argparse, requests, json, re, sys
from datetime import datetime

BASE = "http://localhost:8000"
MAX_RETRIES = 3


def parse_sse_stream(response):
    """SSE 스트림에서 data 이벤트를 파싱하여 리스트로 반환."""
    results = []
    for line in response.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            try:
                results.append(json.loads(line[6:]))
            except Exception:
                pass
    return results


def get_events_by_type(results, type_key):
    """특정 타입의 이벤트만 필터링."""
    return [r for r in results if r.get("type") == type_key]


def get_last_event(results, type_key):
    """특정 타입의 마지막 이벤트 반환."""
    for r in reversed(results):
        if r.get("type") == type_key:
            return r
    return None


def rule_validate(text):
    """규칙 검수. 실패 항목 리스트 반환. 빈 리스트 = PASS."""
    errors = []
    c = len(text)

    # 글자수 100~500
    if c < 100:
        errors.append(f"글자수 부족: {c}자 (최소 100)")
    if c > 500:
        errors.append(f"글자수 초과: {c}자 (최대 500)")

    # 이모지 적절성 -- 너무 많으면 문제 (5개 초과)
    emoji_pattern = re.compile(
        r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF'
        r'\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF'
        r'\U0001F900-\U0001F9FF\U0001FA00-\U0001FAFF'
        r'\U00002702-\U000027B0\U0000FE00-\U0000FE0F'
        r'\U0000200D\U00002600-\U000026FF\U00002700-\U000027BF]'
    )
    emoji_count = len(emoji_pattern.findall(text))
    if emoji_count > 5:
        errors.append(f"이모지 과다: {emoji_count}개 (최대 5개)")

    # 광고성 과도 체크
    ad_words = ["최저가", "할인", "구매링크", "무료배송", "선착순", "한정수량",
                "지금 바로 구매", "클릭하세요", "www.", "http"]
    ad_count = sum(1 for w in ad_words if w in text)
    if ad_count >= 3:
        errors.append(f"광고성 과도: 광고 키워드 {ad_count}개 발견")

    # 페르소나 유지 체크 -- 경어체/반말 혼용 체크
    formal = len(re.findall(r'(?:합니다|습니다|입니다|세요|시오)', text))
    casual = len(re.findall(r'(?:거든|잖아|했음|인듯|ㅋㅋ|ㅎㅎ|임다)', text))
    if formal > 3 and casual > 3:
        errors.append("말투 혼용: 존댓말과 반말이 섞여 있음")

    return errors


def run(args):
    post_type = args.type
    keyword = args.keyword
    product = {
        "name": args.product_name or "",
        "brand_keyword": args.brand_keyword or "",
        "usp": args.usp or "",
        "target": args.target or "",
        "ingredients": args.ingredients or "",
    }
    selling_logic = args.selling_logic or "shuffle"
    forbidden = args.forbidden or ""

    # -- 서버 확인 --
    try:
        r = requests.get(BASE, timeout=5)
        if r.status_code != 200:
            print("서버 응답 없음")
            sys.exit(1)
    except Exception:
        print("서버 연결 실패 (http://localhost:8000)")
        sys.exit(1)

    print(f"채널: 쓰레드 | 유형: {post_type} | 키워드: {keyword}")
    print("=" * 60)

    # -- STEP 1: 콘텐츠 생성 --
    final_text = None
    retry = 0

    while retry <= MAX_RETRIES:
        tag = f" (재시도 {retry})" if retry > 0 else ""
        print(f"\nSTEP 1: 콘텐츠 생성 중{tag}...")

        body = {
            "type": post_type,
            "account_id": "",
            "keywords": [keyword] if post_type == "traffic" else [],
            "product": product,
            "selling_logic": selling_logic,
            "forbidden": forbidden,
            "count": 1,
            "ref_posts": [],
        }

        try:
            r = requests.post(
                f"{BASE}/api/threads/generate",
                json=body,
                stream=True,
                timeout=120,
            )
        except Exception as e:
            print(f"API 호출 실패: {e}")
            retry += 1
            if retry > MAX_RETRIES:
                print(f"{MAX_RETRIES}회 재시도 초과. 중단.")
                sys.exit(1)
            continue

        results = parse_sse_stream(r)

        # 에러 체크
        err_event = get_last_event(results, "error")
        if err_event:
            print(f"  생성 에러: {err_event.get('message', '알 수 없는 에러')}")
            retry += 1
            if retry > MAX_RETRIES:
                print(f"{MAX_RETRIES}회 재시도 초과. 중단.")
                sys.exit(1)
            continue

        # 결과 추출
        result_events = get_events_by_type(results, "result")
        if not result_events:
            print("  결과 없음")
            retry += 1
            if retry > MAX_RETRIES:
                print(f"{MAX_RETRIES}회 재시도 초과. 중단.")
                sys.exit(1)
            continue

        data = result_events[0].get("data", {})
        text = data.get("full_text", "") or data.get("text", "")

        if not text.strip():
            print("  빈 텍스트 반환됨")
            retry += 1
            if retry > MAX_RETRIES:
                print(f"{MAX_RETRIES}회 재시도 초과. 중단.")
                sys.exit(1)
            continue

        print(f"  생성 완료: {len(text)}자")

        # -- STEP 2: 규칙 검수 --
        print("\nSTEP 2: 규칙 검수...")
        errs = rule_validate(text)

        if errs:
            print(f"  FAIL: {errs}")
            retry += 1
            if retry > MAX_RETRIES:
                print(f"  {MAX_RETRIES}회 초과. 현재 버전 사용.")
                final_text = text
                break
            print(f"  -> 재생성 {retry}/{MAX_RETRIES}")
            continue

        print(f"  PASS: {len(text)}자, 규칙 통과")
        final_text = text
        break

    if final_text is None:
        print("콘텐츠 생성 실패. 중단.")
        sys.exit(1)

    # -- STEP 3: job_state.json 저장 --
    print("\nSTEP 3: 상태 저장...")
    state_path = "/Users/iconlms/Desktop/안티그래비티/job_state.json"
    try:
        with open(state_path, "r") as f:
            state = json.load(f)
    except Exception:
        state = {"jobs": []}

    job = {
        "job_id": f"threads-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "channel": "threads",
        "type": post_type,
        "status": "approved",
        "keyword": keyword,
        "dedup_key": f"threads:{keyword}:{datetime.now().strftime('%Y%m%d')}",
        "revision_count": retry,
        "char_count": len(final_text),
        "manual_version": "threads-v1",
        "prompt_version": datetime.now().strftime("%Y-%m-%d"),
        "created_at": datetime.now().isoformat(),
    }
    state["jobs"].append(job)
    with open(state_path, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"  저장 완료: {job['job_id']}")

    # -- 최종 보고 --
    print("\n" + "=" * 60)
    print("최종 보고")
    print("=" * 60)
    print(f"유형: {post_type}")
    print(f"키워드: {keyword}")
    print(f"글자수: {len(final_text)}자 | 재시도: {retry}회")
    print(f"\n--- 본문 ---")
    print(final_text)
    print(f"\n저장: {job['job_id']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="쓰레드 콘텐츠 파이프라인")
    p.add_argument("--type", required=True, help="daily 또는 traffic")
    p.add_argument("--keyword", required=True, help="키워드")
    p.add_argument("--product-name", default="", help="제품명")
    p.add_argument("--brand-keyword", default="", help="브랜드 키워드")
    p.add_argument("--usp", default="", help="USP")
    p.add_argument("--target", default="", help="타겟")
    p.add_argument("--ingredients", default="", help="성분")
    p.add_argument("--selling-logic", default="shuffle", help="셀링 로직 (shuffle/sympathy/review)")
    p.add_argument("--forbidden", default="", help="금지어")
    run(p.parse_args())
