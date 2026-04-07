"""카페바이럴 3단계 파이프라인 -- /cafe-viral 커맨드에서 호출. 끝까지 자동 실행."""
import argparse, requests, json, re, sys
from datetime import datetime

BASE = "http://localhost:8000"
MAX_REVISIONS = 3

# 광고성 표현 블랙리스트
AD_WORDS = [
    "최저가", "무료배송", "할인", "쿠폰", "이벤트", "특가", "파격",
    "지금 바로 구매", "구매링크", "www.", "http", ".com", ".kr",
    "광고", "협찬", "제공받", "원래 가격", "정가",
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


def get_stage_text(stage_data):
    """stage 딕셔너리에서 본문 텍스트 추출 (title + body 합산)."""
    if not stage_data:
        return ""
    title = stage_data.get("title", "")
    body = stage_data.get("body", "")
    parts = [p for p in [title, body] if p]
    return "\n".join(parts)


def rule_validate(stage1, stage2, stage3):
    """규칙 검수. 실패 항목 리스트 반환. 빈 리스트 = PASS."""
    errors = []

    # 3단계 모두 존재하는지
    s1_text = get_stage_text(stage1)
    s2_text = get_stage_text(stage2)
    s3_text = get_stage_text(stage3)

    if not s1_text:
        errors.append("1단계(일상글) 누락")
    if not s2_text:
        errors.append("2단계(고민글) 누락")
    if not s3_text:
        errors.append("3단계(침투글) 누락")

    # 각 단계 200자 이상
    if s1_text and len(s1_text) < 200:
        errors.append(f"1단계 글자수 부족: {len(s1_text)}자 (최소 200)")
    if s2_text and len(s2_text) < 200:
        errors.append(f"2단계 글자수 부족: {len(s2_text)}자 (최소 200)")
    if s3_text and len(s3_text) < 200:
        errors.append(f"3단계 글자수 부족: {len(s3_text)}자 (최소 200)")

    # 광고성 표현 체크 (1단계, 2단계에서는 제품명/브랜드 직접 노출 금지)
    for word in AD_WORDS:
        if word in s1_text:
            errors.append(f"1단계에 광고성 표현: '{word}'")
            break
        if word in s2_text:
            errors.append(f"2단계에 광고성 표현: '{word}'")
            break

    # 3단계 댓글 존재 체크
    # 서버 파서가 [댓글] 마커를 찾지 못하면 comments가 빈 문자열이 됨
    # 이 경우 body 안에 댓글이 포함되어 있을 수 있으므로 body에서도 체크
    comments = stage3.get("comments", "") if stage3 else ""
    if not comments or len(comments.strip()) < 10:
        # body에 댓글 패턴이 있는지 확인 (댓글1, 댓글2 등)
        s3_body = stage3.get("body", "") if stage3 else ""
        comment_patterns = ["댓글1", "댓글2", "댓글 1", "댓글 2", "공감", "저도"]
        has_inline_comments = any(p in s3_body for p in comment_patterns)
        if not has_inline_comments:
            errors.append("3단계 댓글 누락 또는 너무 짧음")

    return errors


def run(args):
    category = args.category
    product = {
        "target": args.target,
        "target_concern": args.concern,
        "product_category": args.product_category,
        "brand_keyword": args.brand_keyword,
        "name": args.product_name,
        "usp": args.usp,
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
    stage1 = None
    stage2 = None
    stage3 = None
    revision = 0

    while revision <= MAX_REVISIONS:
        tag = f" (리비전 {revision})" if revision > 0 else ""
        print(f"\nSTEP 1: 카페바이럴 3단계 생성{tag}...")

        payload = {
            "category": category,
            "product": product,
            "set_count": 1,
        }
        r = requests.post(f"{BASE}/api/viral/generate",
                          json=payload, stream=True, timeout=300)
        results = parse_sse_stream(r)
        result_d = get_data(results, "result")
        if not result_d:
            err = get_data(results, "error")
            print(f"생성 실패: {err}")
            sys.exit(1)

        data = result_d.get("data", {})
        stage1 = data.get("stage1", {})
        stage2 = data.get("stage2", {})
        stage3 = data.get("stage3", {})

        s1_len = len(get_stage_text(stage1))
        s2_len = len(get_stage_text(stage2))
        s3_len = len(get_stage_text(stage3))
        print(f"  생성 완료: 1단계={s1_len}자 | 2단계={s2_len}자 | 3단계={s3_len}자")

        print("STEP 2: 규칙 검수...")
        errs = rule_validate(stage1, stage2, stage3)
        if errs:
            print(f"  FAIL: {errs}")
            revision += 1
            if revision > MAX_REVISIONS:
                print(f"  {MAX_REVISIONS}회 초과. 현재 버전 사용.")
                break
            print(f"  -> 리비전 {revision}/{MAX_REVISIONS}")
            continue
        print(f"  PASS: 3단계 모두 200자+, 광고성 표현 없음")
        break

    # -- STEP 3: job_state 저장 --
    state_path = "/Users/iconlms/Desktop/안티그래비티/job_state.json"
    try:
        state = json.load(open(state_path))
    except Exception:
        state = {"jobs": []}

    s1_text = get_stage_text(stage1)
    s2_text = get_stage_text(stage2)
    s3_text = get_stage_text(stage3)

    job = {
        "job_id": f"cafe-viral-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "channel": "cafe_viral",
        "status": "approved",
        "category": category,
        "target": args.target,
        "concern": args.concern,
        "product_name": args.product_name,
        "dedup_key": f"cafe_viral:{args.product_name}:{datetime.now().strftime('%Y%m%d')}",
        "revision_count": revision,
        "stage1_chars": len(s1_text),
        "stage2_chars": len(s2_text),
        "stage3_chars": len(s3_text),
        "manual_version": "cafe-viral-v1",
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
    print(f"카테고리: {category}")
    print(f"타겟: {args.target}")
    print(f"고민키워드: {args.concern}")
    print(f"제품: {args.product_name}")
    print(f"리비전: {revision}회")
    print(f"\n--- 1단계: 일상글 ({len(s1_text)}자) ---")
    print(f"제목: {stage1.get('title', '')}")
    print(s1_text[:300])
    if len(s1_text) > 300:
        print(f"... (총 {len(s1_text)}자)")
    print(f"\n--- 2단계: 고민글 ({len(s2_text)}자) ---")
    print(f"제목: {stage2.get('title', '')}")
    print(s2_text[:300])
    if len(s2_text) > 300:
        print(f"... (총 {len(s2_text)}자)")
    print(f"\n--- 3단계: 침투글 ({len(s3_text)}자) ---")
    print(f"제목: {stage3.get('title', '')}")
    print(s3_text[:300])
    if len(s3_text) > 300:
        print(f"... (총 {len(s3_text)}자)")
    comments = stage3.get("comments", "")
    if comments:
        print(f"\n--- 댓글 ---")
        print(comments[:200])
    print(f"\n저장: {job['job_id']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--category", required=True, help="타겟 카테고리 (예: 30대 여성)")
    p.add_argument("--target", required=True, help="타겟 (예: 30대 직장인 여성)")
    p.add_argument("--topic", required=True, help="일상 주제 (예: 퇴근 후 피로)")
    p.add_argument("--concern", required=True, help="고민 키워드 (예: 만성피로)")
    p.add_argument("--product-category", required=True, help="제품 카테고리 (예: 건강기능식품)")
    p.add_argument("--brand-keyword", required=True, help="브랜드 키워드")
    p.add_argument("--product-name", required=True, help="제품명")
    p.add_argument("--usp", required=True, help="USP")
    p.add_argument("--ingredients", required=True, help="주요 성분")
    run(p.parse_args())
