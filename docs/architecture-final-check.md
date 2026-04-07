# 에이전틱 아키텍처 v4 — 구현 전 최종 점검

## 배경

1인 이커머스 사업자. 마케팅 자동화 프로그램(Python FastAPI 7,700줄 + HTML 7,089줄). 10개 채널 콘텐츠 자동 생성. 슬랙으로 AI 직원에게 지시 → 실행 → 승인 구조가 최종 목표.

## 리뷰 이력

- v1 (6.5/10): 프롬프트 체인, 상태관리 없음
- v2 (7.8/10): 상태저장소/항목별문턱/부분수정 추가
- v3 (8.4/10): Planning Loop/상태전이/원칙11개 추가. 범위 과다 지적
- v4 (8.9/10): 총괄 삭제, 채널별 독립 구조, Phase 1 숏츠만으로 축소

4번의 리뷰를 거치면서 수정한 핵심:
1. 총괄 오케스트레이터 → 삭제 (채널별 독립)
2. 에이전트 33개 한꺼번에 → Phase 1은 숏츠만
3. 총점 7.0 → 항목별 하한선
4. 전체 재생성 → 원인별 부분 수정
5. AI가 전체 흐름 관리 → 상태 전이는 코드 강제, 판단은 AI
6. CLAUDE.md 비대 → 60줄 지도, 상세는 agent.md/manual로 분리
7. Planning Loop/분석팀/운영팀 → Phase 3로 이동
8. 프롬프트 품질보다 파이프라인 작동 확인이 Phase 1 목표

## v4 확정 설계

### 구조

```
[나] → /shorts, /blog 등으로 직접 실행 (총괄 없음)

각 채널 = 독립 오케스트레이터:
  {채널}-pipeline.md → 서브에이전트들 spawn → 결과

슬랙(Phase 3): 봇이 명령을 대신 호출하는 껍데기
```

### Phase 1에서 만드는 것 (이것만)

```
1. CLAUDE.md                  — 60줄 하네스
2. shorts-pipeline.md         — 숏츠 오케스트레이터
3. strategist.md              — 전략 수립 서브에이전트
4. script-writer.md           — 대본 작성 서브에이전트
5. script-reviewer.md         — 품질 검수 서브에이전트
6. shorts-manual.md           — 숏츠 채널 매뉴얼
7. /shorts 커맨드 (shorts.md) — 트리거 스킬
8. rule-validator              — 코드 검사기 (글자수/훅/CTA)
9. job_state.json + 상태 전이  — 작업 상태 관리
10. PostToolUse 훅             — 코드 수정 후 자동 문법검사
```

### Phase 1 성공 기준

```
1. /shorts 실행 → 숏츠 대본이 끝까지 생성되는가
2. 검수 → 부분수정 → 재검수 루프가 작동하는가
3. 상태 전이가 강제되는가 (검수 없이 저장 불가)
4. 세션 끊겨도 이어가기가 되는가
5. 프롬프트 교체가 결과물에 즉시 반영되는가
```

### Phase 1에서 안 만드는 것

```
나머지 9개 채널 파이프라인 → Phase 2
분석팀 (performance, report, sales) → Phase 3
운영팀 (scheduler, accounts, utm, photo, ad) → Phase 3
Planning Loop (성과→재계획) → Phase 3
슬랙 봇 → Phase 3
```

### 서브에이전트 (Phase 1에서 쓰는 것만)

| 에이전트 | 역할 | 도구 경계 |
|---------|------|----------|
| strategist | 컨셉 3세트 + 훅 설계 | 생성전용 |
| script-writer | 대본 작성 + 피드백 반영 재작성 | 생성전용 |
| script-reviewer | 규칙검사(코드) + AI평가 → 부분수정 지시 | 읽기전용 |

### 도구 어댑터 (Phase 1)

| 어댑터 | 역할 |
|--------|------|
| tts-converter | server.py /api/shorts/tts 호출 |
| notion-saver | server.py /api/shorts 관련 저장 |

### 숏츠 파이프라인 흐름

```
/shorts 실행
  ↓
[shorts-pipeline.md]
  ├─ Step 1: 소재 입력 (사용자에게 질문 또는 프리셋)
  ├─ Step 2: 전략 수립 (strategist) → 컨셉 3개 → HITL 선택
  ├─ Step 3: 대본 작성 (script-writer)
  │    ↓
  │  [rule-validator] 글자수/훅/CTA 체크 (코드, 비용 0)
  │    → 실패 시 해당 항목만 수정 지시
  │    → 통과 시 ↓
  │  [script-reviewer] AI 평가 (항목별 하한선)
  │    → FAIL → 원인별 부분 수정 (최대 3회)
  │    → PASS ↓
  ├─ Step 4: TTS (tts-converter) → 음성 + 자막
  ├─ Step 5: 저장 (notion-saver) → HITL 승인 후
  └─ 완료 보고
```

### 상태 전이 (코드 강제)

```
draft → under_review → revision → under_review
under_review → approved → publish_ready → published
건너뛰기 불가. 역행 불가. 승인 없이 발행 불가.
부분 수정 3회 초과 → HITL.
전략 되돌림 1회 초과 → HITL.
```

### 피드백 루프

```
Level 0 (코드): PostToolUse훅 → 문법검사 → 실패 시 자체수정
Level 1 (콘텐츠): rule-validator(코드) → script-reviewer(AI) → 부분수정
Level 2 (파이프라인): 작업 완료 후 교훈 기록
Level 3 (시스템): Phase 3에서 구현
```

### CLAUDE.md (60줄 이하)

```
금지: .env 커밋, API키 하드코딩, 검수 미통과 저장, 승인 없이 발행
상태 전이: draft→under_review→revision→approved→publish_ready→published
품질 게이트: 규칙(코드)→AI→항목별 하한선. 부분수정 3회, 전략되돌림 1회.
컨텍스트: 해당 채널 매뉴얼만 로드. 안 바뀌는 것 앞, 바뀌는 것 뒤.
학습 루프: 실수→규칙 추가 테이블 (하네스 성장)
```

### 훅

```
시스템: PostToolUse — server.py 수정 후 문법검사 (성공=무출력, 실패=에러)
파이프라인: PRE(중복체크, 상태확인) POST(검수자동) STOP(3회→HITL) NOTIFY(보고)
```

### 컨텍스트 전략

```
CLAUDE.md (60줄) → 모든 에이전트
agent.md → 해당 에이전트만
channel-manual → 해당 채널 작업 시에만
다른 채널 매뉴얼 안 읽음
```

### 채널 매뉴얼 필수 5섹션

```
1. 목적
2. 금지 (예시 포함)
3. 좋은 예시 3개
4. 품질 기준표 (항목별 하한선)
5. 실패 패턴
```

### 설계 원칙 (이 원칙에 따라 만듦)

1. 프롬프트는 부탁, 하네스는 강제
2. 실패할 때마다 하네스 한 줄 추가
3. CLAUDE.md는 지도(60줄), 설명서 아님
4. 자동 교정 루프
5. 성공은 조용히, 실패만 시끄럽게
6. 컨텍스트는 전략적으로
7. 복잡한 작업은 분할 위임
8. 테스트 없으면 에이전트는 거짓말한다
9. 결과를 빠르게 검증 가능하면 위임
10. GIGO
11. 모델이 똑똑해질수록 하네스는 단순해져야

### 프로젝트 구조

```
안티그래비티/                  ← 한 프로젝트
  .claude/
    agents/                   ← 파이프라인 + 서브에이전트
    commands/                 ← /shorts 등 스킬
    channel-manuals/          ← 채널별 매뉴얼
    settings.local.json       ← 훅
  server.py                   ← 기존 백엔드 (그대로 유지)
  dashboard.html              ← 기존 프론트 (그대로 유지)
  CLAUDE.md                   ← 하네스
  job_state.json              ← 작업 상태
```

### 이후 로드맵

```
Phase 1: 숏츠 파일럿 (지금)
Phase 2: 나머지 9채널 (서브에이전트 재사용 + /batch)
Phase 3: 슬랙 봇 + 분석/운영 에이전트 + Planning Loop
```

---

## 최종 점검 요청

이 설계대로 Phase 1 구현을 시작하려 한다. 마지막으로 다음을 확인해줘:

### 1. Phase 1 실행 가능성
- 위 10개 파일로 숏츠 파일럿을 시작하기에 충분한가?
- 빠진 것이 있는가?
- 이 범위가 "작지만 완결된 단위"인가?

### 2. 가장 먼저 부딪힐 문제
- 구현 시작하면 가장 먼저 막힐 곳은 어디인가?
- 그걸 미리 방지할 수 있는가?

### 3. 전체 방향
- v1(6.5) → v2(7.8) → v3(8.4) → v4(8.9)로 왔다. 방향이 맞는가?
- 구현 시작해도 되는가?
- 마지막으로 한 마디 해줘.

이번이 진짜 마지막 리뷰다. 구현 들어간다.
