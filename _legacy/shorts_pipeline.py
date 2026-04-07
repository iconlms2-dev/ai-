"""숏츠 파이프라인 — /shorts 커맨드에서 호출. 끝까지 자동 실행."""
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


def rule_validate(script_text):
    """규칙 검수. 실패 항목 리스트 반환. 빈 리스트 = PASS."""
    errors = []
    c = len(script_text)
    if c < 300:
        errors.append(f"글자수 부족: {c}자 (최소 300)")
    if c > 800:
        errors.append(f"글자수 초과: {c}자 (최대 800)")

    lines = [l.strip() for l in script_text.strip().split("\n") if l.strip()]
    first = lines[0] if lines else ""
    hooks = ["?", "아셨", "솔직히", "진짜", "제가", "그날", "어느 날",
             "갑자기", "했는데", "었는데", "이었", "그때", "있었"]
    if not any(p in first for p in hooks):
        errors.append("첫 문장 훅 부족")

    tail = " ".join(lines[-2:]) if len(lines) >= 2 else (lines[-1] if lines else "")
    cta_words = ["확인", "링크", "검색", "프로필", "클릭", "터치", "보세요"]
    if not any(w in tail for w in cta_words):
        errors.append("CTA 없음")

    if re.search(r'[\U0001F600-\U0001F9FF\U0001FA00-\U0001FAFF\U00002702-\U000027B0]', script_text):
        errors.append("이모지 발견")
    if re.search(r'\[(연출|자막|장면|화면|전환|효과)\]', script_text):
        errors.append("메타 표기 발견")

    return errors


def run(args):
    material = {
        "product": args.product,
        "target": args.target,
        "problem": args.problem,
        "emotion": args.emotion,
        "trust": args.trust,
        "cta": args.cta,
    }
    content_type = args.type
    length = args.length

    # ── 서버 확인 ──
    try:
        r = requests.get(BASE, timeout=5)
        if r.status_code != 200:
            print("❌ 서버 응답 없음")
            sys.exit(1)
    except Exception:
        print("❌ 서버 연결 실패 (http://localhost:8000)")
        sys.exit(1)

    # ── STEP 1: 주제 생성 ──
    print("STEP 1: 주제 생성 중...")
    r = requests.post(f"{BASE}/api/shorts/topics",
                       json={"material": material, "type": content_type},
                       stream=True, timeout=120)
    results = parse_sse_stream(r)
    topics_d = get_data(results, "topics")
    if not topics_d:
        err = get_data(results, "error")
        print(f"❌ 주제 생성 실패: {err}")
        sys.exit(1)

    topics_text = topics_d["text"]
    numbered = [l.strip() for l in topics_text.split("\n")
                if l.strip() and re.match(r'^\d+\.', l.strip())]
    raw_topic = numbered[0] if numbered else topics_text.split("\n")[0]
    topic = re.sub(r'^\d+\.\s*', '', raw_topic).split("—")[0].strip().strip('"').strip('"').strip('"').strip('*')
    print(f"  ✅ 주제 선택: {topic[:60]}")

    # ── STEP 2-3: 대본 생성 + 검수 루프 ──
    script_text = ""
    revision = 0
    while revision <= MAX_REVISIONS:
        tag = f" (리비전 {revision})" if revision > 0 else ""
        print(f"\nSTEP 2: 대본 생성{tag}...")
        r = requests.post(f"{BASE}/api/shorts/script",
                           json={"material": material, "type": content_type,
                                 "topic": topic, "length": length},
                           stream=True, timeout=120)
        results = parse_sse_stream(r)
        script_d = get_data(results, "script")
        if not script_d:
            err = get_data(results, "error")
            print(f"❌ 대본 생성 실패: {err}")
            sys.exit(1)

        script_text = script_d["text"]
        print(f"  ✅ {len(script_text)}자 생성")

        print("STEP 3: 규칙 검수...")
        errs = rule_validate(script_text)
        if errs:
            print(f"  ❌ FAIL: {errs}")
            revision += 1
            if revision > MAX_REVISIONS:
                print(f"  ⚠️ {MAX_REVISIONS}회 초과. 현재 버전 사용.")
                break
            print(f"  → 리비전 {revision}/{MAX_REVISIONS}")
            continue
        print(f"  ✅ PASS: {len(script_text)}자, 훅 O, CTA O")
        break

    # ── STEP 4: 훅 생성 ──
    print("\nSTEP 4: 훅 생성 중...")
    r = requests.post(f"{BASE}/api/shorts/hooks",
                       json={"script": script_text},
                       stream=True, timeout=120)
    results = parse_sse_stream(r)
    hooks_d = get_data(results, "hooks")
    hooks_text = hooks_d["text"] if hooks_d else ""
    hook_lines = [l.strip() for l in hooks_text.split("\n")
                  if re.match(r'^\d+\.', l.strip())]
    print(f"  ✅ 훅 {len(hook_lines)}개 생성")

    # ── STEP 5: job_state 저장 ──
    state_path = "/Users/iconlms/Desktop/안티그래비티/job_state.json"
    state = json.load(open(state_path))
    job = {
        "job_id": f"shorts-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "channel": "shorts",
        "status": "approved",
        "topic": topic,
        "dedup_key": f"shorts:{material['product']}:{datetime.now().strftime('%Y%m%d')}",
        "revision_count": revision,
        "char_count": len(script_text),
        "hook_count": len(hook_lines),
        "manual_version": "shorts-v1",
        "prompt_version": datetime.now().strftime("%Y-%m-%d"),
        "created_at": datetime.now().isoformat(),
    }
    state["jobs"].append(job)
    with open(state_path, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    # ── 최종 보고 ──
    print("\n" + "=" * 60)
    print("📋 최종 보고")
    print("=" * 60)
    print(f"주제: {topic}")
    print(f"글자수: {len(script_text)}자 | 리비전: {revision}회 | 훅: {len(hook_lines)}개")
    print(f"\n--- 대본 ---")
    print(script_text)
    print(f"\n--- 훅 (상위 5개) ---")
    for h in hook_lines[:5]:
        print(f"  {h}")
    if len(hook_lines) > 5:
        print(f"  ... 외 {len(hook_lines) - 5}개")
    print(f"\n✅ 저장: {job['job_id']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--product", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--problem", required=True)
    p.add_argument("--emotion", required=True)
    p.add_argument("--trust", required=True)
    p.add_argument("--cta", required=True)
    p.add_argument("--type", default="썰형")
    p.add_argument("--length", type=int, default=600)
    run(p.parse_args())
