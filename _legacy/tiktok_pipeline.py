"""틱톡 스크립트 파이프라인 -- /tiktok 커맨드에서 호출. 끝까지 자동 실행."""
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


def clean_script(raw):
    """프롬프트 출력에서 섹션 헤더, 타이밍, 연출 메모를 제거하여 순수 대사만 추출."""
    lines = raw.strip().split("\n")
    cleaned = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        # 섹션 헤더 제거: [후킹], [문제 공감], [전환점], [마무리] + 타이밍
        if re.match(r'^\[(?:후킹|문제\s*공감|전환점|마무리)\]', s):
            continue
        # [연출: ...] 메모 제거
        if re.match(r'^\[연출[:：]', s):
            continue
        # 인라인 따옴표 제거
        s = s.strip('"').strip('"').strip('"')
        if s:
            cleaned.append(s)
    return "\n".join(cleaned)


def rule_validate(script_text):
    """규칙 검수. 실패 항목 리스트 반환. 빈 리스트 = PASS."""
    errors = []
    text = clean_script(script_text)
    c = len(text)
    if c < 200:
        errors.append(f"글자수 부족: {c}자 (최소 200)")
    if c > 500:
        errors.append(f"글자수 초과: {c}자 (최대 500)")

    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    first = lines[0] if lines else ""
    hooks = ["?", "아셨", "솔직히", "진짜", "제가", "그날", "어느 날",
             "갑자기", "했는데", "었는데", "이었", "그때", "있었",
             "아시", "근데", "혹시", "알고", "요즘", "나도"]
    if not any(p in first for p in hooks):
        errors.append("첫 문장 훅 부족")

    if re.search(r'[\U0001F600-\U0001F9FF\U0001FA00-\U0001FAFF\U00002702-\U000027B0]', text):
        errors.append("이모지 발견")
    if re.search(r'\[(연출|자막|장면|화면|전환|효과)\]', text):
        errors.append("메타 표기 발견")

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
    appeal = args.appeal
    buying_one = args.buying_one
    forbidden = args.forbidden or ""

    # -- 서버 확인 --
    try:
        r = requests.get(BASE, timeout=5)
        if r.status_code != 200:
            print("[ERROR] 서버 응답 없음")
            sys.exit(1)
    except Exception:
        print("[ERROR] 서버 연결 실패 (http://localhost:8000)")
        sys.exit(1)

    # -- STEP 1: 스크립트 생성 + 검수 루프 --
    script_text = ""
    revision = 0
    while revision <= MAX_REVISIONS:
        tag = f" (리비전 {revision})" if revision > 0 else ""
        print(f"\nSTEP 1: 틱톡 스크립트 생성{tag}...")

        payload = {
            "keywords": [{"keyword": keyword, "page_id": ""}],
            "product": product,
            "appeal": appeal,
            "buying_one": buying_one,
            "forbidden": forbidden,
        }
        r = requests.post(f"{BASE}/api/tiktok/generate",
                          json=payload, stream=True, timeout=120)
        results = parse_sse_stream(r)

        result_d = get_data(results, "result")
        if not result_d:
            err = get_data(results, "error")
            print(f"[ERROR] 스크립트 생성 실패: {err}")
            sys.exit(1)

        data = result_d.get("data", result_d)
        script_text = data.get("script", "")
        print(f"  [OK] {len(script_text)}자 생성")

        # -- STEP 2: 규칙 검수 --
        print("STEP 2: 규칙 검수...")
        errs = rule_validate(script_text)
        if errs:
            print(f"  [FAIL] {errs}")
            revision += 1
            if revision > MAX_REVISIONS:
                print(f"  [WARN] {MAX_REVISIONS}회 초과. 현재 버전 사용.")
                break
            print(f"  -> 리비전 {revision}/{MAX_REVISIONS}")
            continue
        print(f"  [PASS] {len(script_text)}자, 훅 O")
        break

    # -- STEP 3: job_state 저장 --
    state_path = "/Users/iconlms/Desktop/안티그래비티/job_state.json"
    try:
        state = json.load(open(state_path))
    except Exception:
        state = {"jobs": []}

    job = {
        "job_id": f"tiktok-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "channel": "tiktok",
        "status": "approved",
        "keyword": keyword,
        "dedup_key": f"tiktok:{keyword}:{datetime.now().strftime('%Y%m%d')}",
        "revision_count": revision,
        "char_count": len(script_text),
        "manual_version": "tiktok-v1",
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
    print(f"글자수: {len(script_text)}자 | 리비전: {revision}회")
    print(f"\n--- 스크립트 ---")
    print(script_text)
    print(f"\n[OK] 저장: {job['job_id']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--keyword", required=True)
    p.add_argument("--product-name", required=True)
    p.add_argument("--brand-keyword", required=True)
    p.add_argument("--usp", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--ingredients", required=True)
    p.add_argument("--appeal", required=True)
    p.add_argument("--buying-one", required=True)
    p.add_argument("--forbidden", default="")
    run(p.parse_args())
