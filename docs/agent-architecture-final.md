# 에이전틱 아키텍처 최종 설계서 (v4)

## 설계 원칙

1. 프롬프트는 부탁, 하네스는 강제
2. 실패할 때마다 하네스 한 줄 추가
3. CLAUDE.md는 지도(60줄 이하), 설명서 아님
4. 자동 교정 루프 (훅→테스트→에이전트 자체 수정)
5. 성공은 조용히, 실패만 시끄럽게
6. 컨텍스트는 전략적으로 (필요한 것만, 적시에)
7. 복잡한 작업은 분할 위임
8. 테스트 없으면 에이전트는 거짓말한다
9. "결과를 빠르게 검증 가능한가?" → Yes면 위임
10. GIGO — 기획이 구리면 하네스도 소용없다
11. 모델이 똑똑해질수록 하네스는 단순해져야 한다

---

## 핵심 구조: 채널별 독립 오케스트레이터

> 총괄 오케스트레이터 없음.
> 각 채널이 독립된 프로젝트처럼 운영됨.
> 사용자가 /shorts, /blog 등으로 직접 실행.
> (슬랙 봇은 Phase 3에서 이 명령을 대신 호출하는 껍데기)

```
[나 (사장)]
    │
    ├─ /shorts  → [숏츠 오케스트레이터] → 에이전트들 → 결과
    ├─ /blog    → [블로그 오케스트레이터] → 에이전트들 → 결과
    ├─ /cafe-seo → [카페SEO 오케스트레이터] → 에이전트들 → 결과
    ├─ ... (각 채널 독립)
    │
    └─ 슬랙 (Phase 3):
       "블로그 5개 숏츠 3개" → 봇이 /blog 5번, /shorts 3번 호출
```

**참고 프로젝트(유튜브 자동화)와 동일한 구조.**
참고 프로젝트가 유튜브 1개 채널에 대해 만든 것을, 우리는 10개 채널 각각에 만든다.

---

## 채널별 오케스트레이터 구조 (공통 패턴)

각 채널 오케스트레이터는 이 패턴을 따른다:

```
{채널}-pipeline.md (오케스트레이터)
  │
  ├─ Step: 조사/분석
  ├─ Step: 전략 수립
  ├─ Step: 콘텐츠 생성
  ├─ Step: 품질 검수 ←→ 부분 수정 루프
  ├─ Step: 저장/발행
  └─ 보고

사용하는 서브에이전트: 채널마다 다름 (재사용 가능)
참조하는 매뉴얼: 해당 채널 manual만
적용되는 훅: 공통 훅 + 채널 전용 훅
상태 관리: job_state.json (공통)
```

---

## 채널별 상세

### 숏츠 (Phase 1 — 첫 번째)

```
shorts-pipeline.md
  ├─ data-researcher → 유사 쇼츠 벤치마킹
  ├─ pattern-extractor → 패턴/팩트 추출
  ├─ strategist → 컨셉 3세트 + 훅 설계
  ├─ script-writer → 대본 작성
  ├─ script-reviewer → 품질 검수 ←→ 부분 수정
  ├─ tts-converter (도구어댑터) → TTS + 자막
  └─ notion-saver (도구어댑터) → 저장

매뉴얼: shorts-manual.md
스킬: /shorts
API: /api/shorts/*
```

### 블로그 (Phase 2)

```
blog-pipeline.md
  ├─ keyword-analyzer → SERP + 경쟁강도 + 상위글
  ├─ strategist → 구매여정 + 접점 설계
  ├─ title-generator → 제목 생성
  ├─ forbidden-checker (코드검사기) → 금칙어
  ├─ script-writer → 본문 작성
  ├─ script-reviewer → 품질 검수 ←→ 부분 수정
  └─ notion-saver → 저장

매뉴얼: blog-manual.md
스킬: /blog
API: /api/blog/*, /api/keywords/*
```

### 카페SEO (Phase 2)

```
cafe-seo-pipeline.md
  ├─ keyword-analyzer
  ├─ strategist
  ├─ title-generator → 제목
  ├─ script-writer → 본문
  ├─ comment-writer → 댓글 3개
  ├─ script-reviewer → 검수
  └─ notion-saver → 저장

매뉴얼: cafe-seo-manual.md
스킬: /cafe-seo
API: /api/cafe/*
```

### 카페바이럴 (Phase 2)

```
cafe-viral-pipeline.md
  ├─ script-writer → 1단계(관심) + 2단계(문제) + 3단계(솔루션)
  ├─ script-reviewer → 3단계 전체 검수
  └─ notion-saver → 저장

매뉴얼: cafe-viral-manual.md
스킬: /cafe-viral
API: /api/viral/*
```

### 지식인 (Phase 2)

```
jisikin-pipeline.md
  ├─ keyword-analyzer
  ├─ title-generator → 질문 제목
  ├─ script-writer → 질문 본문 + 답변
  ├─ script-reviewer → 검수
  └─ notion-saver → 저장

매뉴얼: jisikin-manual.md
스킬: /jisikin
API: /api/jisikin/*
```

### 유튜브 댓글 (Phase 2)

```
youtube-pipeline.md
  ├─ data-researcher → 영상 검색
  ├─ video-analyst → 영상 정보 분석
  ├─ comment-writer → 댓글 생성
  ├─ script-reviewer → 검수
  ├─ youtube-poster (도구어댑터, HITL) → 게시
  └─ notion-saver → 저장

매뉴얼: youtube-manual.md
스킬: /youtube
API: /api/youtube/*
```

### 틱톡 (Phase 2)

```
tiktok-pipeline.md
  ├─ keyword-analyzer
  ├─ script-writer → 스크립트
  ├─ script-reviewer → 검수
  └─ notion-saver → 저장

매뉴얼: tiktok-manual.md
스킬: /tiktok
API: /api/tiktok/*
```

### 커뮤니티 (Phase 2)

```
community-pipeline.md
  ├─ strategist → 커뮤니티 + 전략 유형
  ├─ script-writer → 게시글
  ├─ comment-writer → 댓글
  ├─ script-reviewer → 검수
  └─ notion-saver → 저장

매뉴얼: community-manual.md
스킬: /community
API: /api/community/*
```

### 파워컨텐츠 (Phase 2)

```
powercontent-pipeline.md
  ├─ data-researcher → 경쟁 광고 크롤링
  ├─ pattern-extractor → 레퍼런스 분석
  ├─ script-writer → 광고 카피 + 본문
  ├─ script-reviewer → 검수
  └─ notion-saver → 저장

매뉴얼: powercontent-manual.md
스킬: /powercontent
API: /api/powercontent/*
```

### 쓰레드 (Phase 2)

```
threads-pipeline.md
  ├─ data-researcher → 레퍼런스 크롤링
  ├─ strategist → 유형 선택 (일상/물길/댓글)
  ├─ script-writer → 콘텐츠 생성
  ├─ script-reviewer → 검수
  ├─ threads-publisher (도구어댑터, HITL) → 발행
  └─ notion-saver → 저장

매뉴얼: threads-manual.md
스킬: /threads
API: /api/threads/*
```

---

## 서브에이전트 (채널 간 재사용)

| 에이전트 | 역할 | 도구 경계 | 사용 채널 |
|---------|------|----------|----------|
| data-researcher | 외부 데이터 수집 | 읽기전용 | shorts, youtube, powercontent, threads |
| pattern-extractor | 패턴/팩트 추출 | 읽기전용 | shorts, powercontent |
| keyword-analyzer | SERP+경쟁강도 | 읽기전용 | blog, cafe-seo, jisikin, tiktok |
| video-analyst | 영상 정보 분석 | 읽기전용 | youtube, shorts |
| strategist | 전략/컨셉 수립 | 생성전용 | shorts, blog, cafe-seo, community, threads |
| hook-designer | 훅/CTR 설계 | 생성전용 | shorts, powercontent |
| title-generator | 제목 생성 | 생성전용 | blog, cafe-seo, jisikin |
| script-writer | 본문/대본 작성 | 생성전용 | 전체 (9채널) |
| comment-writer | 댓글 생성 | 생성전용 | cafe-seo, youtube, community, threads |
| script-reviewer | 품질 검수 | 읽기전용 | 전체 (10채널) |

## 도구 어댑터 (AI 판단 없음, 실행만)

| 어댑터 | 역할 | HITL |
|--------|------|------|
| tts-converter | ElevenLabs TTS | 불필요 |
| notion-saver | Notion DB 저장 | 불필요 |
| youtube-poster | 유튜브 게시 | 필수 |
| threads-publisher | 쓰레드 발행 | 필수 |

## 코드 검사기 (에이전트 아님)

| 검사기 | 역할 |
|--------|------|
| forbidden-checker | 금칙어 체크 |
| rule-validator | 글자수/키워드횟수/구조 |

---

## 분석/운영 기능 (Phase 3)

지금은 기존 대시보드로 사용. Phase 3에서 에이전트화:

```
분석: keyword-status-agent, performance-agent, report-agent, sales-analyst
운영: scheduler-agent, deploy-schedule-agent, account-manager, utm-manager, photo-manager, ad-creative-agent
계획: planning-loop-agent (성과→재계획 순환)
```

---

## 피드백 루프

### Level 0: 코드/하네스 (개발 시)
PostToolUse 훅 → 문법검사 → 실패 시 자체수정. 성공은 무출력.
실수 → CLAUDE.md 학습 루프에 규칙 추가.

### Level 1: 콘텐츠 단위 (파이프라인 내부)
생성 → rule-validator(코드) → 실패 항목만 부분 수정
→ script-reviewer(AI) → 항목별 하한선
→ FAIL → 원인별 대응 (규칙/구조/톤/전략)
→ 부분 수정 3회, 전략 되돌림 1회. 초과 시 HITL.

### Level 2: 파이프라인 단위 (작업 완료 후)
이번 작업 전체 평가 → 교훈 → 다음 작업에 적용

### Level 3: 시스템 단위 (Phase 3, 매주)
성과수집 → 리포트 → 재계획 → 다음 주 키워드/채널/전략 반영

---

## 상태 관리

### job_state.json
```json
{
  "job_id": "shorts-20260406-001",
  "channel": "shorts",
  "status": "under_review",
  "current_step": 3,
  "dedup_key": "shorts:다이어트보조제:20260406",
  "steps": [...],
  "revision_count": 1,
  "strategy_rollback_count": 0,
  "last_error": null,
  "approval_status": null,
  "manual_version": "shorts-v1",
  "prompt_version": "2026-04-06"
}
```

### 상태 전이표 (코드 강제)
```
draft → under_review → revision → under_review
under_review → approved → publish_ready → published
건너뛰기 불가. 역행 불가. 승인 없이 발행 불가.
```

---

## 훅

### 시스템 (settings.local.json)
- PostToolUse: server.py 수정 후 문법검사. 성공=무출력, 실패=에러→자체수정.

### 파이프라인 내부 (각 pipeline.md에 명시)
- PRE: 중복체크, 상태확인
- POST: rule-validator → script-reviewer
- STOP: 부분수정 3회 초과, 전략되돌림 1회 초과, API에러 3회
- NOTIFY: 단계별 진행, 품질점수, 완료 보고

---

## 컨텍스트 전략

- CLAUDE.md (60줄): 모든 에이전트가 읽음
- agent.md: 해당 에이전트만 읽음
- channel-manual: 해당 채널 작업 시에만 로드
- 다른 채널 매뉴얼은 안 읽음
- 안 바뀌는 정보(제품, 브랜드) 앞에 고정, 바뀌는 정보 뒤에

---

## 채널 매뉴얼 (channel-manuals/*.md)

필수 5섹션:
1. 목적 — 한 줄
2. 금지 — 절대 안 되는 것 + 예시
3. 좋은 예시 3개
4. 품질 기준표 — 항목별 하한선
5. 실패 패턴

---

## 마이그레이션

### Phase 1: 숏츠 파일럿
- CLAUDE.md (60줄)
- shorts-pipeline.md + 서브에이전트 (strategist, script-writer, script-reviewer)
- shorts-manual.md
- /shorts 커맨드
- rule-validator, job_state, 상태 전이
- PostToolUse 훅

### Phase 2: 채널 확장
- 나머지 9개 파이프라인 + 매뉴얼
- 서브에이전트 재사용 확인
- /batch 일괄 생성

### Phase 3: 슬랙 + 분석/운영 + Planning Loop
- 슬랙 봇 (명령 라우팅)
- 분석/운영 에이전트화
- planning-loop-agent (성과→재계획)
- 스케줄 자동실행
