"""지식인 Q&A 파이프라인 — /jisikin 커맨드에서 호출. 끝까지 자동 실행."""
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


def get_all_data(results, type_key):
    return [r for r in results if r.get("type") == type_key]


def rule_validate(q_title, q_body, answer1, answer2, keyword):
    """규칙 검수. 실패 항목 리스트 반환. 빈 리스트 = PASS."""
    errors = []

    # 답변 300자 이상 (answer1 기준, answer2는 보조)
    a1_len = len(answer1)
    if a1_len < 300:
        errors.append(f"답변1 글자수 부족: {a1_len}자 (최소 300)")

    a2_len = len(answer2)
    if a2_len < 200:
        errors.append(f"답변2 글자수 부족: {a2_len}자 (최소 200)")

    # Q/A 분리 확인: 질문과 답변이 실질적으로 다른 내용인지
    if q_body.strip() == answer1.strip():
        errors.append("질문과 답변이 동일함")

    # 키워드 포함 체크 (질문 제목 + 답변에 키워드가 있어야 함)
    kw_lower = keyword.lower()
    title_has = kw_lower in q_title.lower()
    answer_has = kw_lower in answer1.lower() or kw_lower in answer2.lower()
    if not title_has and not answer_has:
        errors.append(f"키워드 '{keyword}' 미포함 (제목/답변 모두 없음)")

    # 질문 제목이 비어있으면 안됨
    if len(q_title.strip()) < 5:
        errors.append(f"질문 제목 너무 짧음: {len(q_title.strip())}자")

    # 질문 본문이 비어있으면 안됨
    if len(q_body.strip()) < 20:
        errors.append(f"질문 본문 너무 짧음: {len(q_body.strip())}자")

    # 광고성 표현 체크
    ad_words = ["최고", "대박", "강추", "미쳤다", "링크", "바로가기", "구매하세요", "할인"]
    for w in ad_words:
        if w in answer1 or w in answer2:
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
    q_title = ""
    q_body = ""
    answer1 = ""
    answer2 = ""
    revision = 0

    while revision <= MAX_REVISIONS:
        tag = f" (리비전 {revision})" if revision > 0 else ""
        print(f"\nSTEP 1: 지식인 Q&A 생성{tag}...")

        payload = {
            "keywords": [{"keyword": keyword, "page_id": ""}],
            "product": product,
        }
        r = requests.post(f"{BASE}/api/jisikin/generate",
                          json=payload, stream=True, timeout=300)
        results = parse_sse_stream(r)

        result_d = get_data(results, "result")
        if not result_d:
            err = get_data(results, "error")
            print(f"생성 실패: {err}")
            sys.exit(1)

        data = result_d.get("data", result_d)
        q_title = data.get("q_title", "")
        q_body = data.get("q_body", "")
        answer1 = data.get("answer1", "")
        answer2 = data.get("answer2", "")

        print(f"  생성 완료: 제목={q_title[:50]}")
        print(f"  질문: {len(q_body)}자 | 답변1: {len(answer1)}자 | 답변2: {len(answer2)}자")

        print("STEP 2: 규칙 검수...")
        errs = rule_validate(q_title, q_body, answer1, answer2, keyword)
        if errs:
            print(f"  FAIL: {errs}")
            revision += 1
            if revision > MAX_REVISIONS:
                print(f"  {MAX_REVISIONS}회 초과. 현재 버전 사용.")
                break
            print(f"  -> 리비전 {revision}/{MAX_REVISIONS}")
            continue
        print(f"  PASS: 답변1 {len(answer1)}자, 답변2 {len(answer2)}자, 키워드 포함 확인")
        break

    # -- STEP 3: Notion 저장 --
    print("\nSTEP 3: Notion 저장...")
    save_payload = {
        "q_title": q_title,
        "q_body": q_body,
        "answer1": answer1,
        "answer2": answer2,
        "page_id": "",
    }
    try:
        r = requests.post(f"{BASE}/api/jisikin/save-notion",
                          json=save_payload, timeout=30)
        save_result = r.json()
        if save_result.get("success"):
            print("  Notion 저장 완료")
        else:
            print(f"  Notion 저장 실패: {save_result.get('error', '알 수 없음')}")
    except Exception as e:
        print(f"  Notion 저장 오류: {e}")

    # -- STEP 4: job_state 저장 --
    state_path = "/Users/iconlms/Desktop/안티그래비티/job_state.json"
    try:
        state = json.load(open(state_path))
    except Exception:
        state = {"jobs": []}

    job = {
        "job_id": f"jisikin-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "channel": "jisikin",
        "status": "approved",
        "keyword": keyword,
        "q_title": q_title,
        "dedup_key": f"jisikin:{keyword}:{datetime.now().strftime('%Y%m%d')}",
        "revision_count": revision,
        "answer1_len": len(answer1),
        "answer2_len": len(answer2),
        "manual_version": "jisikin-v1",
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
    print(f"질문 제목: {q_title}")
    print(f"질문 본문: {q_body[:200]}")
    if len(q_body) > 200:
        print(f"  ... (총 {len(q_body)}자)")
    print(f"\n--- 답변 1 (앞 300자) ---")
    print(answer1[:300])
    if len(answer1) > 300:
        print(f"  ... (총 {len(answer1)}자)")
    print(f"\n--- 답변 2 (앞 300자) ---")
    print(answer2[:300])
    if len(answer2) > 300:
        print(f"  ... (총 {len(answer2)}자)")
    print(f"\n답변1: {len(answer1)}자 | 답변2: {len(answer2)}자 | 리비전: {revision}회")
    print(f"저장: {job['job_id']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--keyword", required=True)
    p.add_argument("--product-name", required=True)
    p.add_argument("--brand-keyword", required=True)
    p.add_argument("--usp", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--ingredients", required=True)
    run(p.parse_args())
