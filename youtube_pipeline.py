"""유튜브 댓글 파이프라인 -- /youtube 커맨드에서 호출. 끝까지 자동 실행."""
import argparse, requests, json, re, sys
from datetime import datetime

BASE = "http://localhost:8000"
MAX_REVISIONS = 3


def parse_sse_stream(response):
    """SSE 스트림에서 data: 라인 파싱"""
    results = []
    for line in response.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            try:
                results.append(json.loads(line[6:]))
            except Exception:
                pass
    return results


def get_data(results, type_key):
    """결과 리스트에서 특정 type의 마지막 항목 반환"""
    for r in reversed(results):
        if r.get("type") == type_key:
            return r
    return None


def get_all_data(results, type_key):
    """결과 리스트에서 특정 type의 모든 항목 반환"""
    return [r for r in results if r.get("type") == type_key]


def rule_validate(comment_text, video_title):
    """규칙 검수. 실패 항목 리스트 반환. 빈 리스트 = PASS."""
    errors = []

    # 글자수 체크 (50~200자)
    c = len(comment_text.strip())
    if c < 50:
        errors.append(f"글자수 부족: {c}자 (최소 50)")
    if c > 200:
        errors.append(f"글자수 초과: {c}자 (최대 200)")

    # 영상 제목 관련 단어 포함 체크
    # 불용어 제외, 실질적 키워드만 체크
    stopwords = {'이런', '저런', '어떤', '무슨', '모든', '정말', '진짜', '너무', '아주',
                 '그리고', '하지만', '그래서', '왜냐하면', '때문에', '그런데', '따라서',
                 '있는', '없는', '하는', '되는', '같은', '이렇게', '그렇게', '어떻게',
                 '분들은', '사람들', '여러분', '우리가', '이것은', '그것은', '무조건',
                 '드셔야', '나옵니다', '좋은', '먹으면', '알고', '합니다', '됩니다'}
    title_words = re.findall(r'[가-힣]+', video_title)
    meaningful_words = [w for w in title_words if len(w) >= 2 and w not in stopwords]
    if meaningful_words:
        found = any(w in comment_text for w in meaningful_words)
        if not found:
            # 부분 매칭도 허용 (예: "루테인의" 제목에서 "루테인" 댓글에 포함)
            found = any(
                any(mw[:len(mw)-1] in comment_text for mw in meaningful_words if len(mw) > 2)
                for _ in [1]
            )
        if not found:
            errors.append(f"영상 제목 관련 단어 미포함 (제목 키워드: {meaningful_words[:5]})")

    # 스팸성 체크 (URL/링크만 — @멘션은 유튜브 댓글에서 정상)
    spam_patterns = [r'http[s]?://', r'www\.', r'\.com/', r'\.kr/']
    for pat in spam_patterns:
        if re.search(pat, comment_text):
            errors.append(f"스팸성 패턴 발견: {pat}")
            break

    # 광고 티 체크
    ad_words = ['구매하세요', '지금 바로', '할인', '최저가', '무료배송', '이벤트', '쿠폰']
    for w in ad_words:
        if w in comment_text:
            errors.append(f"광고성 단어 발견: {w}")
            break

    return errors


def parse_comments_from_text(comment_text):
    """3단 시나리오 텍스트에서 개별 댓글 추출"""
    comments = []

    # 방법1: "댓글N (라벨):" 헤더 기반 분리
    pattern = r'댓글\d[^:]*:\s*\n(.*?)(?=\n댓글\d|$)'
    matches = re.findall(pattern, comment_text, re.DOTALL)
    if matches:
        for m in matches:
            # 각 댓글 내용에서 실제 텍스트만 추출
            lines = []
            for line in m.strip().split('\n'):
                stripped = line.strip()
                if not stripped:
                    continue
                # (밑밥), (해결사), (쐐기) 같은 라벨 줄 스킵
                if re.match(r'^\(?(밑밥|해결사|쐐기)\)?$', stripped):
                    continue
                lines.append(stripped)
            text = ' '.join(lines).strip()
            # @로 시작하는 답글 형태면 @ 부분 제거
            text = re.sub(r'^@\S*\s*', '', text).strip()
            if text and len(text) > 5:
                comments.append(text)

    # 방법2: "1단계", "2단계", "3단계" 또는 번호 기반
    if not comments:
        pattern2 = r'(?:1단계|2단계|3단계|\d+\.)[^\n]*\n(.*?)(?=(?:1단계|2단계|3단계|\d+\.)|$)'
        matches2 = re.findall(pattern2, comment_text, re.DOTALL)
        for m in matches2:
            lines = []
            for line in m.strip().split('\n'):
                stripped = line.strip()
                if not stripped:
                    continue
                if re.match(r'^\(?(밑밥|해결사|쐐기)\)?$', stripped):
                    continue
                lines.append(stripped)
            text = ' '.join(lines).strip()
            text = re.sub(r'^@\S*\s*', '', text).strip()
            if text and len(text) > 5:
                comments.append(text)

    # 방법3: 줄 기반 파싱 (최후 수단)
    if not comments:
        lines = comment_text.strip().split('\n')
        current = []
        for line in lines:
            stripped = line.strip()
            if re.match(r'(댓글\d|1단계|2단계|3단계|\d+\.\s)', stripped):
                if current:
                    text = ' '.join(current).strip()
                    text = re.sub(r'^@\S*\s*', '', text).strip()
                    if text and len(text) > 5:
                        comments.append(text)
                current = []
            elif stripped and not re.match(r'^\(?(밑밥|해결사|쐐기)\)?$', stripped):
                current.append(stripped)
        if current:
            text = ' '.join(current).strip()
            text = re.sub(r'^@\S*\s*', '', text).strip()
            if text and len(text) > 5:
                comments.append(text)

    return comments


def run(args):
    keyword = args.keyword
    brand_keyword = args.brand_keyword
    count = args.count

    # -- 서버 확인 --
    try:
        r = requests.get(BASE, timeout=5)
        if r.status_code != 200:
            print("서버 응답 없음")
            sys.exit(1)
    except Exception:
        print("서버 연결 실패 (http://localhost:8000)")
        sys.exit(1)

    # -- STEP 1: 영상 검색 --
    print("STEP 1: 영상 검색 중...")
    r = requests.post(f"{BASE}/api/youtube/search-videos",
                      json={"keyword": keyword, "count": 5},
                      timeout=60)
    if r.status_code != 200:
        print(f"영상 검색 실패: {r.text}")
        sys.exit(1)

    search_result = r.json()
    if 'error' in search_result:
        print(f"영상 검색 에러: {search_result['error']}")
        sys.exit(1)

    videos = search_result.get('videos', [])
    if not videos:
        print("검색 결과 없음")
        sys.exit(1)

    print(f"  검색 완료: {len(videos)}개 영상 발견")

    # -- STEP 2: 상위 3개 영상 선택 + 상세 정보 크롤링 --
    top_videos = videos[:3]
    print(f"\nSTEP 2: 상위 {len(top_videos)}개 영상 상세 정보 수집...")

    enriched_videos = []
    for i, v in enumerate(top_videos):
        vid_url = v.get('url', f"https://www.youtube.com/watch?v={v.get('id', '')}")
        print(f"  [{i+1}/{len(top_videos)}] {v.get('title', '제목 없음')[:50]}")

        # fetch-info로 제목/설명 크롤링
        try:
            info_r = requests.post(f"{BASE}/api/youtube/fetch-info",
                                   json={"url": vid_url}, timeout=15)
            if info_r.status_code == 200:
                info = info_r.json()
                enriched_videos.append({
                    'title': info.get('title') or v.get('title', ''),
                    'description': info.get('description', ''),
                    'link': vid_url,
                    'script': info.get('transcript', ''),
                })
            else:
                enriched_videos.append({
                    'title': v.get('title', ''),
                    'description': '',
                    'link': vid_url,
                    'script': '',
                })
        except Exception:
            enriched_videos.append({
                'title': v.get('title', ''),
                'description': '',
                'link': vid_url,
                'script': '',
            })

    print(f"  상세 정보 수집 완료: {len(enriched_videos)}개")

    # -- STEP 3-4: 댓글 생성 + 검수 루프 --
    all_results = []
    revision = 0

    for attempt in range(MAX_REVISIONS + 1):
        tag = f" (리비전 {attempt})" if attempt > 0 else ""
        print(f"\nSTEP 3: 댓글 생성{tag}...")

        r = requests.post(f"{BASE}/api/youtube/generate",
                          json={
                              "videos": enriched_videos,
                              "brand_keyword": brand_keyword,
                              "product_name": brand_keyword,
                          },
                          stream=True, timeout=300)
        results = parse_sse_stream(r)

        # 에러 체크
        err = get_data(results, "error")
        if err:
            print(f"댓글 생성 실패: {err.get('message', err)}")
            sys.exit(1)

        # 결과 수집
        result_items = get_all_data(results, "result")
        if not result_items:
            print("생성 결과 없음")
            sys.exit(1)

        print(f"  {len(result_items)}개 영상 댓글 생성 완료")

        # STEP 4: 규칙 검수
        print("\nSTEP 4: 규칙 검수...")
        all_pass = True
        validated_results = []

        for item in result_items:
            data = item.get("data", item)
            title = data.get("title", "")
            comment_text = data.get("comment", "")
            comments = parse_comments_from_text(comment_text)

            video_errors = []
            valid_comments = []
            for ci, c in enumerate(comments[:count]):
                errs = rule_validate(c, title)
                if errs:
                    video_errors.extend([f"댓글{ci+1}: {e}" for e in errs])
                    all_pass = False
                valid_comments.append(c)

            validated_results.append({
                "title": title,
                "link": data.get("link", ""),
                "summary": data.get("summary", ""),
                "comment_raw": comment_text,
                "comments": valid_comments,
                "errors": video_errors,
            })

            if video_errors:
                print(f"  [{title[:30]}] FAIL: {video_errors}")
            else:
                print(f"  [{title[:30]}] PASS")

        if all_pass:
            all_results = validated_results
            revision = attempt
            print(f"\n  전체 PASS")
            break
        else:
            revision = attempt + 1
            if revision > MAX_REVISIONS:
                print(f"\n  {MAX_REVISIONS}회 초과. 현재 버전 사용.")
                all_results = validated_results
                break
            print(f"  -> 리비전 {revision}/{MAX_REVISIONS}")
            all_results = validated_results
            continue

    # -- STEP 5: job_state.json 저장 --
    state_path = "/Users/iconlms/Desktop/안티그래비티/job_state.json"
    try:
        state = json.load(open(state_path))
    except Exception:
        state = {"jobs": []}

    total_comments = sum(len(r["comments"]) for r in all_results)
    job = {
        "job_id": f"youtube-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "channel": "youtube",
        "status": "approved",
        "keyword": keyword,
        "brand_keyword": brand_keyword,
        "dedup_key": f"youtube:{keyword}:{datetime.now().strftime('%Y%m%d')}",
        "revision_count": revision,
        "video_count": len(all_results),
        "comment_count": total_comments,
        "manual_version": "youtube-v1",
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
    print(f"브랜드: {brand_keyword}")
    print(f"영상: {len(all_results)}개 | 댓글: {total_comments}개 | 리비전: {revision}회")

    for i, res in enumerate(all_results):
        print(f"\n--- 영상 {i+1}: {res['title'][:60]} ---")
        print(f"링크: {res['link']}")
        if res.get('summary'):
            print(f"요약: {res['summary'][:100]}...")
        for ci, c in enumerate(res['comments'][:count]):
            label = ['밑밥', '해결사', '쐐기'][ci] if ci < 3 else f'{ci+1}'
            char_count = len(c)
            print(f"\n  댓글{ci+1} ({label}) [{char_count}자]:")
            print(f"  {c}")

    print(f"\n저장: {job['job_id']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="유튜브 댓글 파이프라인")
    p.add_argument("--keyword", required=True, help="검색 키워드")
    p.add_argument("--brand-keyword", required=True, help="브랜드 키워드")
    p.add_argument("--count", type=int, default=3, help="영상당 댓글 수 (기본 3)")
    run(p.parse_args())
