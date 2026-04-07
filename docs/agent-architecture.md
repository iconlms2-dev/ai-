# 에이전틱 아키텍처 전체 설계서

## 전체 시스템 구조

```
[사장님] ─── 디스코드/슬랙 (Phase 3) 또는 Claude Code CLI (Phase 1~2)
    │
    │  "숏츠 3개 만들어" / "블로그 5개" / "이번 주 전부" / "새 기능 추가해"
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  메인 세션 (Claude Code)                             │
│  ┌─────────────────────────────────────────────┐    │
│  │  CLAUDE.md (하네스 = 강제 규칙)              │    │
│  │  - 라우팅 규칙                               │    │
│  │  - 채널별 품질 기준                           │    │
│  │  - 학습 루프 (실수→규칙 추가)                 │    │
│  │  - 도구 경계                                  │    │
│  └─────────────────────────────────────────────┘    │
│                                                      │
│  운영 모드: 파이프라인 에이전트 spawn                  │
│  개발 모드: 직접 코드 수정 + 테스트 + 배포             │
└──────────────┬──────────────────────────────────────┘
               │
    ┌──────────┼──────────┬──────────┬──────────┐
    ▼          ▼          ▼          ▼          ▼
[shorts]  [blog]    [cafe-seo]  [threads]   ... 10개 파이프라인
    │
    ├→ data-researcher
    ├→ pattern-extractor
    ├→ strategist
    ├→ script-writer
    ├→ script-reviewer  ←── 피드백 루프
    ├→ tts-converter
    └→ notion-saver
```

---

## 1. 에이전트 구조 (agents/)

### 1-1. 파이프라인 에이전트 (L1) — 채널별 오케스트레이터

각 파이프라인은 해당 채널의 전체 워크플로우를 관리한다.
서브에이전트를 순서대로 spawn하고, 결과를 다음 단계에 전달한다.

```
.claude/agents/
  ├── shorts-pipeline.md          # 숏츠 제작
  ├── blog-pipeline.md            # 블로그 원고
  ├── cafe-seo-pipeline.md        # 카페SEO 원고
  ├── cafe-viral-pipeline.md      # 카페바이럴
  ├── jisikin-pipeline.md         # 지식인 Q&A
  ├── youtube-pipeline.md         # 유튜브 댓글
  ├── tiktok-pipeline.md          # 틱톡 스크립트
  ├── community-pipeline.md       # 커뮤니티 침투
  ├── powercontent-pipeline.md    # 파워컨텐츠
  └── threads-pipeline.md         # 쓰레드
```

#### 각 파이프라인의 단계 상세

**shorts-pipeline.md (숏츠)**
```
Step 1. 벤치마킹     → data-researcher → pattern-extractor
Step 2. 전략         → strategist → hook-designer
Step 3. 대본         → script-writer → script-reviewer → (FAIL시 재작성)
Step 4. 음성         → tts-converter
Step 5. 저장         → notion-saver
Step 6. 보고         → 사장님께 결과 요약
```
사용하는 server.py API:
- `/api/shorts/topics`, `/api/shorts/script`, `/api/shorts/hooks`
- `/api/shorts/tts`, `/api/shorts/voices`
- `/api/shorts/download/{filename}`
현재 프롬프트 빌더: `_build_shorts_topics_prompt`, `_build_shorts_script_prompt`, `_build_shorts_hooks_prompt`

**blog-pipeline.md (블로그)**
```
Step 1. 분석         → keyword-analyzer (SERP + 상위글 분석)
Step 2. 전략         → strategist (구매여정 + 접점 설계)
Step 3. 제목         → title-generator → forbidden-checker
Step 4. 본문         → script-writer → script-reviewer → (FAIL시 재작성)
Step 5. 저장         → notion-saver
Step 6. 보고
```
사용하는 server.py API:
- `/api/keywords/analyze`, `/api/keywords/contact-point`
- `/api/blog/generate`, `/api/blog/check-forbidden`, `/api/blog/fix-forbidden`
- `/api/blog/save-notion`
현재 프롬프트 빌더: `_build_blog_title_prompt`, `_build_blog_body_prompt`

**cafe-seo-pipeline.md (카페SEO)**
```
Step 1. 분석         → keyword-analyzer
Step 2. 전략         → strategist
Step 3. 제목+본문    → title-generator → script-writer → script-reviewer
Step 4. 댓글         → comment-writer → script-reviewer
Step 5. 이미지       → (server.py 기존 이미지 수집 활용)
Step 6. 저장         → notion-saver
Step 7. 보고
```
사용하는 server.py API:
- `/api/cafe/notion-keywords`, `/api/cafe/generate`
- `/api/cafe/save-notion`, `/api/cafe/docx`
현재 프롬프트 빌더: `_build_cafe_title_prompt`, `_build_cafe_body_prompt`, `_build_cafe_comments_prompt`

**cafe-viral-pipeline.md (카페바이럴)**
```
Step 1. 1단계 생성   → script-writer (관심 유발)
Step 2. 2단계 생성   → script-writer (문제 인식)
Step 3. 3단계 생성   → script-writer (솔루션 제시)
Step 4. 품질 검수    → script-reviewer (3단계 전체)
Step 5. 저장         → notion-saver
Step 6. 보고
```
사용하는 server.py API:
- `/api/viral/generate`, `/api/viral/save-notion`
현재 프롬프트 빌더: `_build_viral_stage1_prompt`, `_build_viral_stage2_prompt`, `_build_viral_stage3_prompt`

**jisikin-pipeline.md (지식인)**
```
Step 1. 분석         → keyword-analyzer
Step 2. 질문 생성    → title-generator (질문 제목) → script-writer (질문 본문)
Step 3. 답변 생성    → script-writer (답변)
Step 4. 품질 검수    → script-reviewer
Step 5. 저장         → notion-saver
Step 6. 보고
```
사용하는 server.py API:
- `/api/jisikin/notion-keywords`, `/api/jisikin/generate`, `/api/jisikin/generate-direct`
- `/api/jisikin/save-notion`
현재 프롬프트 빌더: `_build_jisikin_title_prompt`, `_build_jisikin_body_prompt`, `_build_jisikin_answers_prompt`, `_build_jisikin_direct_answer_prompt`

**youtube-pipeline.md (유튜브 댓글)**
```
Step 1. 영상 검색    → data-researcher (YouTube 검색)
Step 2. 영상 분석    → video-analyst (영상 정보 수집)
Step 3. 댓글 생성    → comment-writer → script-reviewer
Step 4. 자동 게시    → youtube-poster (선택사항, HITL)
Step 5. 저장         → notion-saver
Step 6. 보고
```
사용하는 server.py API:
- `/api/youtube/search-videos`, `/api/youtube/fetch-video-details`
- `/api/youtube/generate`, `/api/youtube/save-notion`
- `/api/youtube/auto-post` (자동 게시)
현재 프롬프트 빌더: `_build_youtube_summary_prompt`, `_build_youtube_comment_prompt`

**tiktok-pipeline.md (틱톡)**
```
Step 1. 분석         → keyword-analyzer
Step 2. 스크립트     → script-writer → script-reviewer
Step 3. 저장         → notion-saver
Step 4. 보고
```
사용하는 server.py API:
- `/api/tiktok/notion-keywords`, `/api/tiktok/generate`, `/api/tiktok/save-notion`
현재 프롬프트 빌더: `_build_tiktok_prompt`

**community-pipeline.md (커뮤니티 침투)**
```
Step 1. 전략 수립    → strategist (커뮤니티 + 전략 유형 결정)
Step 2. 게시글 생성  → script-writer → script-reviewer
Step 3. 댓글 생성    → comment-writer → script-reviewer
Step 4. 저장         → notion-saver
Step 5. 보고
```
사용하는 server.py API:
- `/api/community/generate`, `/api/community/save-notion`
현재 프롬프트 빌더: `_build_community_post_prompt`, `_build_community_comments_prompt`

**powercontent-pipeline.md (파워컨텐츠)**
```
Step 1. 레퍼런스 수집 → data-researcher (경쟁 광고 크롤링)
Step 2. 분석          → pattern-extractor (레퍼런스 분석)
Step 3. 광고 카피     → script-writer (광고 제목 + 설명)
Step 4. 본문 생성     → script-writer (장문 본문) → script-reviewer
Step 5. DOCX 출력     → (server.py 기존 기능)
Step 6. 저장          → notion-saver
Step 7. 보고
```
사용하는 server.py API:
- `/api/powercontent/analyze`, `/api/powercontent/generate`
- `/api/powercontent/docx`, `/api/powercontent/save-notion`
현재 프롬프트 빌더: `_build_pc_analysis_prompt`, `_build_pc_ad_prompt`, `_build_pc_body_prompt`

**threads-pipeline.md (쓰레드)**
```
Step 1. 레퍼런스 수집 → data-researcher (쓰레드 크롤링)
Step 2. 유형 선택     → strategist (일상글/물길글/댓글)
Step 3. 콘텐츠 생성   → script-writer → script-reviewer
Step 4. 발행          → threads-publisher (HITL: 승인 후 발행)
Step 5. 저장          → notion-saver
Step 6. 보고
```
사용하는 server.py API:
- `/api/threads/crawl-reference`, `/api/threads/generate`, `/api/threads/generate-comment`
- `/api/threads/publish`, `/api/threads/save-notion`, `/api/threads/schedule`
현재 프롬프트 빌더: `_build_threads_daily_prompt`, `_build_threads_traffic_prompt`, `_build_threads_comment_prompt`

---

### 1-2. 서브에이전트 (L2) — 전문 작업자

각 서브에이전트는 **하나의 전문 영역만** 담당. 여러 파이프라인에서 재사용.

```
.claude/agents/
  │
  │  ── 리서치 ──
  ├── data-researcher.md         # 외부 데이터 수집 (URL 크롤링, 검색)
  ├── pattern-extractor.md       # 수집된 데이터에서 패턴/팩트 추출
  ├── keyword-analyzer.md        # 키워드 SERP 분석 + 경쟁강도 + 상위글 분석
  ├── video-analyst.md           # 영상 정보 분석 (유튜브 메타데이터)
  │
  │  ── 전략 ──
  ├── strategist.md              # 컨셉/전략 수립, 구매여정 분석
  ├── hook-designer.md           # 훅/인트로/CTR 설계
  │
  │  ── 생성 ──
  ├── title-generator.md         # 제목 생성 (블로그, 카페, 지식인)
  ├── script-writer.md           # 본문/대본 작성 (모든 채널 공통)
  ├── comment-writer.md          # 댓글 생성 (카페, 유튜브, 커뮤니티)
  │
  │  ── 검수 ──
  ├── script-reviewer.md         # 품질 검수 (규칙 + AI 평가)
  ├── forbidden-checker.md       # 금칙어/SelfMoa 체크
  │
  │  ── 배포 ──
  ├── tts-converter.md           # TTS 음성 + SRT 자막 생성
  ├── notion-saver.md            # Notion DB 저장
  ├── youtube-poster.md          # 유튜브 자동 댓글 게시
  ├── threads-publisher.md       # 쓰레드 자동 발행
  │
  │  ── 기존 유지 ──
  ├── code-reviewer.md           # 코드 리뷰
  └── debugger.md                # 디버깅
```

#### 서브에이전트 상세 — 각각이 뭘 하는지

**data-researcher.md**
```
역할: 외부 데이터 수집 전문가
입력: 검색 키워드, URL 목록, 수집 범위
출력: {urls: [...], raw_data: [...], summary: "..."}
사용 도구: WebFetch, Bash(curl), WebSearch
도구 경계: 읽기 전용. 파일 수정 불가. 수집만 함.
호출하는 파이프라인: shorts, powercontent, threads, youtube
```

**pattern-extractor.md**
```
역할: 수집된 데이터에서 패턴과 핵심 팩트 추출
입력: data-researcher의 출력 (raw_data)
출력: {patterns: [...], facts: [...], avoid: [...]}
사용 도구: Claude API (분석 요청)
도구 경계: 읽기 전용. 분석만 함.
호출하는 파이프라인: shorts, powercontent
```

**keyword-analyzer.md**
```
역할: 키워드 SERP 분석 + 경쟁강도 판단 + 상위글 분석
입력: keyword, 분석 깊이
출력: {
  search_volume: {pc, mobile},
  competition: "상/중/하",
  top_articles: [{url, date, photo_count, keyword_repeat}],
  serp_sections: [...],
  contact_point: "인지/탐색/비교/결정"
}
사용 도구: Bash(server.py API 호출)
  - /api/keywords/analyze
  - /api/keywords/search-volume
  - /api/keywords/contact-point
도구 경계: 읽기 전용. server.py API 호출만.
호출하는 파이프라인: blog, cafe-seo, jisikin, tiktok
```

**video-analyst.md**
```
역할: 유튜브 영상 정보 수집 및 분석
입력: 검색 키워드 또는 영상 URL
출력: {videos: [{title, channel, views, description, script}]}
사용 도구: Bash(server.py API)
  - /api/youtube/search-videos
  - /api/youtube/fetch-video-details
도구 경계: 읽기 전용.
호출하는 파이프라인: youtube, shorts(벤치마킹)
```

**strategist.md**
```
역할: 마케팅 전략 수립 + 컨셉 설계
입력: 키워드 분석 결과, 제품 정보, 채널 특성
출력: {
  concepts: [{title, angle, emotion, hook}],  // 3개 제안
  contact_point: "비교/탐색/...",
  strategy: "...",
  recommended: 0  // 추천 인덱스
}
사용 도구: Claude API
도구 경계: 분석만. 콘텐츠 생성 안함.
호출하는 파이프라인: shorts, blog, cafe-seo, community, threads
HITL: 컨셉 3개 제안 → 사용자 선택
```

**hook-designer.md**
```
역할: CTR 훅, 인트로, 썸네일 문구 설계
입력: 전략 결과, 타겟 감정
출력: {hooks: [{text, type, target_emotion}], thumbnail_texts: [...]}
사용 도구: Claude API
도구 경계: 설계만.
호출하는 파이프라인: shorts, powercontent
```

**title-generator.md**
```
역할: 제목 생성 전문가
입력: keyword, channel, strategy, product
출력: {title: "...", alternatives: ["...", "..."]}
사용 도구: Bash(server.py API) 또는 Claude API 직접
도구 경계: 제목만 생성. 본문 생성 안함.
호출하는 파이프라인: blog, cafe-seo, jisikin
```

**script-writer.md**
```
역할: 본문/대본 작성 (가장 핵심적인 서브에이전트)
입력: {
  channel: "shorts/blog/cafe-seo/...",
  keyword, strategy, product,
  constraints: {min_length, max_length, keyword_count, ...},
  revision_feedback: null 또는 "이전 피드백 내용"
}
출력: {content: "...(본문)", word_count: N, structure: {...}}
사용 도구: Bash(server.py API) — 채널별 generate 엔드포인트
  - /api/blog/generate, /api/cafe/generate, /api/shorts/script, ...
도구 경계: Claude API 호출만. 파일 쓰기 불가.
호출하는 파이프라인: 전체 10개 (모든 채널)
피드백 루프: script-reviewer에서 FAIL → revision_feedback와 함께 재호출
```

**comment-writer.md**
```
역할: 댓글 생성 전문가
입력: 본문 내용, 채널, 브랜드 키워드
출력: {comments: [{text, persona, tone}]}
사용 도구: Claude API
도구 경계: 댓글만 생성.
호출하는 파이프라인: cafe-seo, youtube, community, threads
```

**script-reviewer.md**
```
역할: 콘텐츠 품질 검수 (규칙 + AI 평가) ★ 피드백 루프의 핵심
입력: {channel, content, keyword, context}
처리:
  1차 — 규칙 기반 검수 (CLAUDE.md 품질 기준 참조)
  2차 — AI 평가 (Claude API로 채점)
출력: {
  rules_pass: true/false,
  rules_detail: {글자수: "OK", 키워드: "부족", ...},
  ai_score: 8.2,
  ai_feedback: "3번째 문단 흐름 개선 필요",
  overall: "PASS/FAIL",
  revision_guide: "구체적 개선 지침"
}
사용 도구: Read(CLAUDE.md), Bash(server.py API), Claude API
도구 경계: 평가만. 콘텐츠 수정 불가.
호출하는 파이프라인: 전체 10개
```

**forbidden-checker.md**
```
역할: 금칙어/광고성 표현 체크
입력: 텍스트
출력: {pass: true/false, found: ["단어1", "단어2"], fixed_text: "..."}
사용 도구: Bash(server.py API) — /api/blog/check-forbidden, /api/blog/fix-forbidden
도구 경계: 체크만. 본문 직접 수정 안함 (수정 제안만).
호출하는 파이프라인: blog, cafe-seo, powercontent
```

**tts-converter.md**
```
역할: 대본 → TTS 음성 + SRT 자막 변환
입력: script_text, voice_id, words_per_segment
출력: {audio_url, srt_url, txt_url}
사용 도구: Bash(server.py API) — /api/shorts/tts
도구 경계: TTS 변환만. 대본 수정 안함.
호출하는 파이프라인: shorts
```

**notion-saver.md**
```
역할: 생성된 콘텐츠를 Notion DB에 저장
입력: {channel, content, metadata}
출력: {success, notion_page_id, notion_url}
사용 도구: Bash(server.py API) — /api/*/save-notion
도구 경계: Notion 저장만. 콘텐츠 수정 불가.
호출하는 파이프라인: 전체 10개
```

**youtube-poster.md**
```
역할: 유튜브 댓글 자동 게시
입력: comments, video_urls, account
출력: {posted: N, failed: N, details: [...]}
사용 도구: Bash(server.py API) — /api/youtube/auto-post
도구 경계: 게시만. HITL 필수 (사장님 승인 후 게시).
호출하는 파이프라인: youtube
```

**threads-publisher.md**
```
역할: 쓰레드 자동 발행
입력: content, account, schedule
출력: {published: true/false, post_url, scheduled_at}
사용 도구: Bash(server.py API) — /api/threads/publish, /api/threads/schedule
도구 경계: 발행만. HITL 필수.
호출하는 파이프라인: threads
```

---

### 1-3. 서브에이전트 재사용 매트릭스

어떤 서브에이전트가 어떤 파이프라인에서 쓰이는지:

| 서브에이전트 | shorts | blog | cafe-seo | cafe-viral | jisikin | youtube | tiktok | community | powercontent | threads |
|-------------|--------|------|----------|------------|---------|---------|--------|-----------|-------------|---------|
| data-researcher | O | | | | | O | | | O | O |
| pattern-extractor | O | | | | | | | | O | |
| keyword-analyzer | | O | O | | O | | O | | | |
| video-analyst | O | | | | | O | | | | |
| strategist | O | O | O | | | | | O | | O |
| hook-designer | O | | | | | | | | O | |
| title-generator | | O | O | | O | | | | | |
| **script-writer** | **O** | **O** | **O** | **O** | **O** | | **O** | **O** | **O** | **O** |
| comment-writer | | | O | | | O | | O | | O |
| **script-reviewer** | **O** | **O** | **O** | **O** | **O** | **O** | **O** | **O** | **O** | **O** |
| forbidden-checker | | O | O | | | | | | O | |
| tts-converter | O | | | | | | | | | |
| **notion-saver** | **O** | **O** | **O** | **O** | **O** | **O** | **O** | **O** | **O** | **O** |
| youtube-poster | | | | | | O | | | | |
| threads-publisher | | | | | | | | | | O |

**가장 많이 재사용되는 에이전트:** script-writer, script-reviewer, notion-saver (전체 채널)

---

## 2. 스킬 구조 (commands/)

스킬 = 사용자가 `/명령어`로 직접 호출하는 트리거.
에이전트는 내부적으로 알아서 실행되지만, 스킬은 사용자 진입점.

```
.claude/commands/
  │
  │  ── 채널 파이프라인 트리거 ──
  ├── shorts.md              # /shorts → shorts-pipeline 실행
  ├── blog.md                # /blog → blog-pipeline 실행
  ├── cafe-seo.md            # /cafe-seo
  ├── cafe-viral.md          # /cafe-viral
  ├── jisikin.md             # /jisikin
  ├── youtube.md             # /youtube
  ├── tiktok.md              # /tiktok
  ├── community.md           # /community
  ├── powercontent.md        # /powercontent
  ├── threads.md             # /threads
  │
  │  ── 일괄/운영 ──
  ├── batch.md               # /batch → 여러 파이프라인 일괄 실행
  ├── analyze.md             # /analyze → 키워드 분석만 단독 실행
  ├── report.md              # /report → 주간 리포트 생성
  │
  │  ── 개발/배포 (기존) ──
  ├── restart.md             # /restart → 서버 재시작
  ├── deploy.md              # /deploy → 검증 + 안내서 + 재시작
  ├── verify.md              # /verify → 코드 검증
  ├── code-review.md         # /code-review → 코드 리뷰어 실행
  ├── debug.md               # /debug → 디버거 실행
  │
  │  ── 유틸 (기존) ──
  ├── review.md              # /review → Gemini 교차검증
  ├── update-manual.md       # /update-manual → 안내서 동기화
  └── test-keyword.md        # /test-keyword → 키워드 테스트
```

#### 스킬 예시: shorts.md

```markdown
---
description: 숏츠 콘텐츠 파이프라인 실행. 소재 입력 → 벤치마킹 → 전략 → 대본 → TTS → 저장
---

숏츠 콘텐츠를 생성합니다.

1. 사용자에게 소재 정보를 질문합니다:
   - 제품명, 타겟 고객, 핵심 문제, 유발 감정, 신뢰 근거, CTA
   - 콘텐츠 유형 (정보형/썰형)
   - 또는 기존 프리셋 선택

2. shorts-pipeline 에이전트를 spawn합니다.

3. 파이프라인 완료 후 결과를 사용자에게 보고합니다.
```

#### 스킬 예시: batch.md

```markdown
---
description: 이번 주 콘텐츠를 일괄 생성. Notion에서 미생성 키워드를 가져와 채널별 파이프라인 순차 실행
---

일괄 콘텐츠 생성을 실행합니다.

1. Notion DB에서 '생산 상태 = 미생성' 키워드 목록을 가져옵니다
   - /api/batch/keywords

2. 키워드별 배정된 채널을 확인합니다.

3. 채널별로 그룹핑하여 해당 파이프라인을 순차 실행합니다:
   - 블로그 키워드 → blog-pipeline ×N
   - 카페SEO 키워드 → cafe-seo-pipeline ×N
   - ...

4. 전체 완료 후 요약 보고:
   - "총 32개 콘텐츠 생성 완료. 블로그 5, 카페 10, 숏츠 3..."
   - 품질 평균 점수
   - FAIL/재시도 횟수
```

---

## 3. 훅 구조

### 3-1. 시스템 훅 (settings.local.json에 설정 — 자동 강제 실행)

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit",
        "hooks": [
          {
            "type": "command",
            "command": "if echo \"$CLAUDE_TOOL_INPUT\" | grep -q 'server.py'; then python3 -c \"import py_compile; py_compile.compile('server.py', doraise=True)\" 2>&1; fi"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit",
        "hooks": [
          {
            "type": "command",
            "command": "if echo \"$CLAUDE_TOOL_INPUT\" | grep -q 'server.py'; then python3 -c \"import py_compile; py_compile.compile('server.py', doraise=True)\" 2>&1; fi"
          }
        ]
      }
    ]
  }
}
```

**설명:**
- server.py를 Edit(수정)하기 **전에** 문법 검사 → 깨진 상태에서 수정 시작 방지
- server.py를 Edit(수정)한 **후에** 문법 검사 → 깨진 코드가 남아있지 않도록

### 3-2. 파이프라인 내부 훅 (에이전트 .md 파일에 명시)

각 파이프라인 에이전트의 .md 파일 안에 훅 규칙을 정의.
에이전트가 이 규칙을 읽고 **반드시** 따라야 함 (하네스 = 강제).

#### Pre 훅 (실행 전 체크)

```
[모든 파이프라인 공통]
PRE_PIPELINE:
  - 필수 입력값 검증 (빈 값 없는지)
  - server.py 실행 중인지 확인 (curl localhost:8000)
  - CLAUDE.md 품질 기준 로드

PRE_GENERATE (콘텐츠 생성 전):
  - 같은 키워드로 이미 생성된 콘텐츠 있는지 Notion 체크 → 중복 방지
  - 제품 정보 누락 없는지 확인

PRE_SAVE (저장 전):
  - 품질 검수 통과했는지 확인 (script-reviewer PASS 필수)
  - 금칙어 체크 통과했는지 확인
```

#### Post 훅 (실행 후 자동)

```
POST_GENERATE (콘텐츠 생성 후):
  - script-reviewer 자동 호출 (품질 검수 강제)
  - 품질 점수 기록 (로깅)

POST_REVIEW (검수 후):
  - FAIL이면 → revision_feedback와 함께 script-writer 재호출 (자동 리비전)
  - 재시도 횟수 카운트

POST_SAVE (저장 후):
  - 결과 요약 생성
  - 사장님께 보고 메시지 작성

POST_PIPELINE (파이프라인 완료 후):
  - 전체 실행 시간 기록
  - 품질 점수 이력에 추가
  - 리비전 횟수 기록
```

#### Stop 훅 (강제 중단)

```
STOP_CONDITIONS:
  - 금칙어 3개 이상 발견 → 중단 + 사용자 확인 요청
  - 3회 리비전 후에도 AI 점수 6.0 미만 → 중단 + "수동 검토 필요"
  - API 에러 3회 연속 → 중단 + 에러 보고
  - 예상 비용 초과 → 중단 + 사용자 확인 (Claude API 토큰)
```

#### Notification 훅 (알림)

```
NOTIFY:
  - 각 Step 완료 시: "Step 2/5 완료: 전략 수립됨"
  - 품질 검수 결과: "품질 8.2/10 PASS" 또는 "품질 5.8/10 FAIL → 리비전 시작"
  - 파이프라인 완료: "✅ 숏츠 대본 완료. 품질 8.5. Notion 저장됨."
  - 에러 발생: "⚠️ TTS API 타임아웃. 재시도 중 (2/3)"
```

---

## 4. 피드백 루프 구조

### 4-1. 콘텐츠 피드백 루프 (매 생성마다)

```
                    ┌──────────────────┐
                    │  script-writer   │
                    │  콘텐츠 생성     │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ script-reviewer  │
                    │ 1차: 규칙 체크   │
                    │ 2차: AI 평가     │
                    └────────┬─────────┘
                             │
                     ┌───────┴───────┐
                     │               │
                  PASS ≥7점      FAIL <7점
                     │               │
                     ▼               ▼
                  다음 단계     ┌──────────────┐
                  진행         │ revision_guide │
                              │ + 이전 대본을   │
                              │ 컨텍스트에 추가 │
                              └──────┬─────────┘
                                     │
                                     ▼
                              script-writer
                              (피드백 반영 재작성)
                                     │
                                     ▼
                              script-reviewer
                              (재검수)
                                     │
                              ┌──────┴──────┐
                              PASS        FAIL
                              │           (2회차)
                              ▼              │
                           다음 단계         ▼
                                      script-writer
                                      (2차 리비전)
                                           │
                                           ▼
                                      script-reviewer
                                      (3차 검수)
                                           │
                                    ┌──────┴──────┐
                                    PASS        FAIL
                                    │           (3회 실패)
                                    ▼              │
                                 다음 단계         ▼
                                              STOP 훅 발동
                                              → 최고점 결과 선택
                                              → 사장님께 수동 검토 요청
```

### 4-2. 채널별 품질 기준 (CLAUDE.md에 명시)

```
## 콘텐츠 품질 기준 (강제)

### 블로그
| 항목 | 규칙 | FAIL 조건 |
|------|------|----------|
| 글자수 | 2,200자 이상 | 미만이면 FAIL |
| 키워드 | 8회 이상 자연스럽게 포함 | 미만이면 FAIL |
| 소제목 | 4개 이상 | 미만이면 FAIL |
| 문단 | 8단락 이상 | 미만이면 FAIL |
| 사진 위치 | [사진] 태그 포함 | 없으면 FAIL |
| AI 점수 | 7.0 이상 | 미만이면 FAIL |

### 카페SEO
| 항목 | 규칙 | FAIL 조건 |
|------|------|----------|
| 글자수 | 800~1,500자 | 범위 밖이면 FAIL |
| 키워드 | 3~6회 자연스럽게 | 범위 밖이면 FAIL |
| 댓글 | 3개 이상 | 미만이면 FAIL |
| 광고 티 | AI 판단 | "광고같다" 판정시 FAIL |
| AI 점수 | 7.0 이상 | 미만이면 FAIL |

### 숏츠 대본
| 항목 | 규칙 | FAIL 조건 |
|------|------|----------|
| 글자수 | 300~800자 | 범위 밖이면 FAIL |
| 훅 | 첫 문장에 훅 있어야 함 | 없으면 FAIL |
| CTA | 마지막에 CTA 있어야 함 | 없으면 FAIL |
| 구조 | 훅→문제→해결→CTA 흐름 | 흐름 깨지면 FAIL |
| AI 점수 | 7.0 이상 | 미만이면 FAIL |

### 카페바이럴
| 항목 | 규칙 | FAIL 조건 |
|------|------|----------|
| 3단계 구조 | 관심→문제→솔루션 | 단계 누락시 FAIL |
| 자연스러움 | AI 판단 | "광고같다" 판정시 FAIL |
| AI 점수 | 7.0 이상 | 미만이면 FAIL |

### 지식인
| 항목 | 규칙 | FAIL 조건 |
|------|------|----------|
| 질문/답변 분리 | 명확히 구분 | 혼재시 FAIL |
| 답변 길이 | 300자 이상 | 미만이면 FAIL |
| 전문성 | AI 판단 | "피상적" 판정시 FAIL |
| AI 점수 | 7.0 이상 | 미만이면 FAIL |

### 유튜브 댓글
| 항목 | 규칙 | FAIL 조건 |
|------|------|----------|
| 길이 | 50~200자 | 범위 밖이면 FAIL |
| 영상 관련성 | AI 판단 | "무관" 판정시 FAIL |
| 자연스러움 | AI 판단 | "봇같다" 판정시 FAIL |
| AI 점수 | 7.0 이상 | 미만이면 FAIL |

### 틱톡 스크립트
| 항목 | 규칙 | FAIL 조건 |
|------|------|----------|
| 글자수 | 200~500자 | 범위 밖이면 FAIL |
| 훅 | 있어야 함 | 없으면 FAIL |
| AI 점수 | 7.0 이상 | 미만이면 FAIL |

### 커뮤니티
| 항목 | 규칙 | FAIL 조건 |
|------|------|----------|
| 커뮤니티 톤 | 해당 커뮤니티 말투 | 맞지 않으면 FAIL |
| 광고 티 | AI 판단 | "광고같다" 판정시 FAIL |
| AI 점수 | 7.0 이상 | 미만이면 FAIL |

### 파워컨텐츠
| 항목 | 규칙 | FAIL 조건 |
|------|------|----------|
| 글자수 | 3,000자 이상 | 미만이면 FAIL |
| 광고 카피 | 제목+설명 포함 | 누락시 FAIL |
| SEO 키워드 | 10회 이상 | 미만이면 FAIL |
| AI 점수 | 7.0 이상 | 미만이면 FAIL |

### 쓰레드
| 항목 | 규칙 | FAIL 조건 |
|------|------|----------|
| 길이 | 100~500자 | 범위 밖이면 FAIL |
| 페르소나 | 설정된 페르소나 유지 | 벗어나면 FAIL |
| AI 점수 | 7.0 이상 | 미만이면 FAIL |
```

### 4-3. 하네스 성장 루프 (실수 → 규칙 추가)

```
## 학습 루프 (CLAUDE.md에 기록)

실수 발생 시 즉시 이 테이블에 추가한다.
quality-checker는 이 테이블의 모든 규칙을 참조하여 검수한다.

### 코드 실수
| 날짜 | 실수 | 추가된 규칙 |
|------|------|------------|
| 04-01 | bare except 사용 | except Exception 강제 |
| 04-01 | generate()에 에러 처리 없음 | SSE는 반드시 try/except |
| 04-01 | bot.close() 미호출 | 예외 시 반드시 close() |
| 04-01 | lock 없이 공유 상태 접근 | 공유 상태는 반드시 lock |

### 콘텐츠 실수
| 날짜 | 실수 | 채널 | 추가된 규칙 |
|------|------|------|------------|
| (운영하면서 자동 추가됨) | | | |

→ 이 테이블이 커질수록 = 하네스가 강해지는 것
→ 같은 실수가 구조적으로 반복 불가능해짐
```

### 4-4. AI 평가 프롬프트 (script-reviewer가 사용)

```
다음 {channel} 콘텐츠를 평가해주세요.

[평가 기준]
1. 자연스러움 (1~10): 실제 사람이 쓴 것처럼 자연스러운가?
2. 정보성 (1~10): 독자에게 유용한 정보를 제공하는가?
3. 채널 적합도 (1~10): {channel}의 특성에 맞는가?
4. 설득력 (1~10): 구매/행동을 유도하는가?
5. 구조 (1~10): 논리적 흐름이 있는가?

[출력 형식]
- 종합 점수: (5개 평균)
- 가장 약한 부분:
- 구체적 개선 방안:
- 수정이 필요한 문장/문단 지적:
```

---

## 5. 하네스 구조 (4요소 전체)

### 5-1. 컨텍스트 파일

```
CLAUDE.md (메인 하네스)
├─ 절대적 규칙
├─ 에이전트 라우팅 규칙
├─ 채널별 품질 기준 (위 4-2 내용)
├─ 학습 루프 테이블 (위 4-3 내용)
├─ 도구 경계 정의
└─ 프로젝트 상태

각 에이전트.md 파일
├─ 역할 정의
├─ 입력/출력 스펙
├─ 도구 경계 (읽기전용/쓰기전용 등)
├─ 훅 규칙
└─ HITL 포인트
```

### 5-2. CI/CD 게이트

```
[코드 레벨 — 자동]
├─ PreToolUse 훅: server.py 수정 전 문법 검사
├─ PostToolUse 훅: server.py 수정 후 문법 검사
├─ /verify: 코드 변경 후 전체 검증
└─ /deploy: 검증 → 안내서 → 재시작

[콘텐츠 레벨 — 자동]
├─ POST_GENERATE 훅: 생성 후 자동 품질 검수
├─ forbidden-checker: 금칙어 자동 체크
├─ script-reviewer: 규칙 + AI 품질 평가
└─ PRE_SAVE 훅: 검수 통과 안 하면 저장 불가
```

### 5-3. 명시적 도구 경계

```
[읽기 전용 에이전트]
  data-researcher    — 외부 데이터 수집만
  pattern-extractor  — 분석만
  keyword-analyzer   — 분석만
  video-analyst      — 분석만
  script-reviewer    — 평가만
  forbidden-checker  — 체크만

[생성 전용 에이전트]
  strategist         — 전략 텍스트 생성만
  hook-designer      — 훅 텍스트 생성만
  title-generator    — 제목 텍스트 생성만
  script-writer      — 본문 텍스트 생성만
  comment-writer     — 댓글 텍스트 생성만

[쓰기 전용 에이전트]
  notion-saver       — Notion 저장만
  youtube-poster     — 유튜브 게시만 (HITL 필수)
  threads-publisher  — 쓰레드 발행만 (HITL 필수)

[특수 도구 에이전트]
  tts-converter      — ElevenLabs API 호출만
```

### 5-4. 지속적 피드백 루프

```
매 콘텐츠 생성:
  생성 → 검수 → PASS/FAIL → (FAIL시) 피드백 반영 재생성

매 실수 발견:
  원인 분석 → CLAUDE.md 학습 루프에 규칙 추가
  → script-reviewer가 새 규칙 참조
  → 다음부터 같은 패턴 자동 감지

주기적 (Phase 3~4):
  품질 점수 이력 추적
  평균 점수 하락 시 알림
  프롬프트 최적화 필요 여부 판단
```

---

## 6. 전체 파일 트리 요약

```
.claude/
  agents/
    │  ── 파이프라인 (L1) ──
    ├── shorts-pipeline.md
    ├── blog-pipeline.md
    ├── cafe-seo-pipeline.md
    ├── cafe-viral-pipeline.md
    ├── jisikin-pipeline.md
    ├── youtube-pipeline.md
    ├── tiktok-pipeline.md
    ├── community-pipeline.md
    ├── powercontent-pipeline.md
    ├── threads-pipeline.md
    │
    │  ── 서브에이전트 (L2) ──
    ├── data-researcher.md
    ├── pattern-extractor.md
    ├── keyword-analyzer.md
    ├── video-analyst.md
    ├── strategist.md
    ├── hook-designer.md
    ├── title-generator.md
    ├── script-writer.md
    ├── comment-writer.md
    ├── script-reviewer.md
    ├── forbidden-checker.md
    ├── tts-converter.md
    ├── notion-saver.md
    ├── youtube-poster.md
    ├── threads-publisher.md
    │
    │  ── 기존 ──
    ├── code-reviewer.md
    └── debugger.md

  commands/
    │  ── 채널 트리거 ──
    ├── shorts.md
    ├── blog.md
    ├── cafe-seo.md
    ├── cafe-viral.md
    ├── jisikin.md
    ├── youtube.md
    ├── tiktok.md
    ├── community.md
    ├── powercontent.md
    ├── threads.md
    │  ── 운영 ──
    ├── batch.md
    ├── analyze.md
    ├── report.md
    │  ── 기존 ──
    ├── restart.md
    ├── deploy.md
    ├── verify.md
    ├── code-review.md
    ├── debug.md
    ├── review.md
    ├── update-manual.md
    └── test-keyword.md

  settings.local.json              ← 시스템 훅 (Pre/PostToolUse)

CLAUDE.md                          ← 하네스 본체 (품질기준, 학습루프, 라우팅)
```

총 파일 수: 에이전트 27개 + 스킬 23개 + 설정 2개 = **52개 .md 파일**
