# 에이전틱 아키텍처 v3 검증 요청 (2차 리뷰 반영 + Planning Loop + 원칙 적용)

## 내 상황

1인 이커머스(건강기능식품) 사업자. 마케팅 자동화 프로그램을 직접 만들어 쓰고 있다. Python FastAPI 백엔드(7,700줄) + HTML 프론트엔드(7,089줄). 10개 채널 콘텐츠 자동 생성 + 분석/운영/광고 기능 보유.

## 내 목표

디스코드/슬랙으로 AI 직원들에게 지시 → AI가 알아서 실행 → 결과 보고 → 내가 승인. 진짜 회사 사장처럼. 콘텐츠 퀄리티 최우선. 개발도 AI가 직접 수행. 실수가 반복 불가능한 구조(하네스).

## 리뷰 이력

- **v1 리뷰 (6.5/10)**: 프롬프트 체인에 가깝다, 상태 관리 부재, 15개 과함, 코드가 흐름 관리해야
- **v2 리뷰 (7.8/10)**: 상태 저장소/항목별 문턱/부분 수정은 좋아짐. 그러나 AI 흐름 관리 여전히 위험, 15개 중 일부 합치거나 내려야, 상태 전이 강제 없음, Planning Loop 부재 지적

## v3에서 반영한 것

| v2 피드백 | v3 반영 |
|----------|---------|
| 상태 전이 규칙 없음 | 상태 전이표 추가. 코드로 강제. 건너뛰기/역행 불가 |
| Planning Loop 없음 | planning-loop-agent 추가. 시스템 전체 순환(목표분해→계획→실행→평가→재계획) |
| forbidden-checker를 코드로 | 코드 검사기로 전환 (에이전트에서 제거) |
| CLAUDE.md 비대화 우려 | 60줄 이하로 축소. 지도만. 상세는 agent.md/channel-manual로 분리 |
| writer 장기적 분화 필요 | 인지하되 Phase 1에서는 1개로 시작. 품질 보고 Phase 2에서 판단 |
| 전략 되돌림 무한루프 위험 | 1회 제한. 2회째 HITL |
| 발행 전 승인 필수 | 상태 전이표에서 approved → publish_ready에 HITL 강제 |
| manual/prompt 버전 기록 | job_state에 manual_version, prompt_version 추가 |

## v3에서 추가로 적용한 설계 원칙 11개

1. 프롬프트는 부탁, 하네스는 강제
2. 실패할 때마다 하네스 한 줄 추가
3. CLAUDE.md는 지도(60줄), 설명서 아님
4. 자동 교정 루프 (훅→테스트→자체수정)
5. 성공은 조용히, 실패만 시끄럽게
6. 컨텍스트는 전략적으로 (필요한 것만, 적시에)
7. 복잡한 작업은 분할 위임
8. 테스트 없으면 에이전트는 거짓말한다
9. 위임 판단: "결과를 빠르게 검증 가능한가?"
10. GIGO — 기획이 구리면 하네스도 소용없다
11. 모델이 똑똑해질수록 하네스는 단순해져야 한다

---

## v3 설계

### 전체 구조 + Planning Loop

```
┌─────────────────────────────────────────────────────┐
│                  Planning Loop (매주 순환)            │
│                                                      │
│   ① 목표 분해 ──→ ② 계획 수립 ──→ ③ 실행            │
│        ↑                              │              │
│        │                              ▼              │
│   ⑤ 재계획 ◄──── ④ 결과 평가 ◄───── 성과수집        │
└─────────────────────────────────────────────────────┘

① 키워드 분석 → 채널 배정 → 수량 결정
② 키워드별 전략 → 파이프라인 선택 → 우선순위
③ 콘텐츠팀 + 운영팀 + 분석팀 가동
④ 성과수집 → 노출/순위/매출 → 주간리포트
⑤ "블로그 노출 안 됨 → 키워드 교체"
   "카페가 효과 좋음 → 카페 비중 UP"
   → ①로 돌아감

담당: planning-loop-agent (신규)
트리거: /plan (수동) 또는 매주 월요일 자동
HITL: 계획 수립 후 "이번 주 계획 이렇습니다. 승인?"
```

### CLAUDE.md — 60줄 이하 (지도)

```
금지: .env 커밋, API키 하드코딩, 검수 미통과 저장, 승인 없이 발행
상태 전이: draft→under_review→revision→approved→publish_ready→published (건너뛰기/역행 불가)
품질 게이트: 규칙검사(코드) → AI평가 → 항목별 하한선. 부분수정 3회, 전략되돌림 1회, 초과시 HITL.
컨텍스트: 해당 채널 매뉴얼만 로드. 안 바뀌는 정보 앞에 고정.
학습 루프: 실수→규칙 추가 (테이블)
참조: docs/, channel-manuals/
```

상세는 agent.md와 channel-manual에 분리. CLAUDE.md는 보편 규칙만.

### 에이전트 계층

**시스템 (1개)**:
| 에이전트 | 역할 |
|---------|------|
| planning-loop-agent | 전체 Planning Loop ①~⑤ 순환 |

**콘텐츠팀 파이프라인 L1 (10개)**:
| 에이전트 | 단계 |
|---------|------|
| shorts-pipeline | 벤치마킹→전략→대본→검수(→부분수정)→TTS→저장 |
| blog-pipeline | 키워드분석→전략→제목→본문→검수(→부분수정)→저장 |
| cafe-seo-pipeline | 키워드분석→전략→제목+본문→댓글→검수→저장 |
| cafe-viral-pipeline | 1단계(관심)→2단계(문제)→3단계(솔루션)→검수→저장 |
| jisikin-pipeline | 키워드분석→질문→답변→검수→저장 |
| youtube-pipeline | 영상검색→분석→댓글생성→검수→(게시)→저장 |
| tiktok-pipeline | 키워드분석→스크립트→검수→저장 |
| community-pipeline | 전략→게시글→댓글→검수→저장 |
| powercontent-pipeline | 레퍼런스수집→분석→광고카피→본문→검수→저장 |
| threads-pipeline | 레퍼런스수집→유형선택→생성→검수→발행→저장 |

각 파이프라인 내부에도 미니 Planning Loop:
```
② 분석 결과 보고 계획 수립 → ③ 실행 → ④ 검수 평가
→ ⑤ 재계획(부분수정? 전략변경?) → 필요시 ②로
```

**콘텐츠팀 서브에이전트 L2 (10개)**:
| 에이전트 | 역할 | 도구 경계 | 사용 채널 수 |
|---------|------|----------|-------------|
| data-researcher | 외부 데이터 수집 | 읽기전용 | 4 |
| pattern-extractor | 패턴/팩트 추출 | 읽기전용 | 2 |
| keyword-analyzer | SERP+경쟁강도 | 읽기전용 | 4 |
| video-analyst | 영상 정보 분석 | 읽기전용 | 2 |
| strategist | 전략/컨셉 수립 | 생성전용 | 5 |
| hook-designer | 훅/CTR 설계 | 생성전용 | 2 |
| title-generator | 제목 생성 | 생성전용 | 3 |
| script-writer | 본문/대본 작성 | 생성전용 | 9 |
| comment-writer | 댓글 생성 | 생성전용 | 4 |
| script-reviewer | 품질 검수 | 읽기전용 | 10 |

**분석팀 (4개)**:
| 에이전트 | 역할 |
|---------|------|
| keyword-status-agent | 키워드 현황 관리 |
| performance-agent | 성과 수집+분석 |
| report-agent | 주간 리포트 |
| sales-analyst | Cafe24 매출 분석 |

**운영팀 (6개)**:
| 에이전트 | 역할 |
|---------|------|
| scheduler-agent | 스케줄+자동실행 |
| deploy-schedule-agent | 배포일정 |
| account-manager | 계정 상태/한도 |
| utm-manager | UTM 태그 |
| photo-manager | 사진 라이브러리 |
| ad-creative-agent | 광고소재 |

**개발팀 (2개, 기존)**:
code-reviewer, debugger

**도구 어댑터 (4개, 에이전트 아님)**:
tts-converter, notion-saver, youtube-poster, threads-publisher

**코드 검사기 (2개, 에이전트 아님)**:
forbidden-checker (금칙어), rule-validator (글자수/키워드횟수/구조)

**총합: 에이전트 33개 + 도구어댑터 4개 + 코드검사기 2개**

### 피드백 루프 (4레벨)

**Level 0 — 코드/하네스** (개발 시):
PostToolUse 훅 → 문법검사 → 실패 시 에이전트 자체 수정. 성공은 무출력.
실수 발생 → CLAUDE.md 학습 루프에 규칙 추가.

**Level 1 — 콘텐츠 단위** (파이프라인 내부):
생성 → rule-validator(코드, 비용 0) → 실패 항목만 부분 수정
→ script-reviewer(AI) → 항목별 하한선
→ FAIL → 원인 분류 → 규칙실패/구조실패/톤실패/전략실패별 대응
→ 부분 수정 3회, 전략 되돌림 1회. 초과 시 HITL.

**Level 2 — 파이프라인 단위** (작업 완료 후):
이번 작업 전체 평가 → 목표에 맞는가? → 교훈 기록 → 다음 작업에 적용

**Level 3 — 시스템 단위** (매주, Planning Loop):
성과수집 → 리포트 → 평가 → 재계획 → 다음 주 키워드/채널/전략 반영
planning-loop-agent 담당.

### 상태 관리

**job_state.json**:
```json
{
  "job_id": "shorts-20260406-001",
  "channel": "shorts",
  "status": "under_review",
  "current_step": 3,
  "dedup_key": "shorts:다이어트보조제:20260406",
  "steps": [
    {"step": 1, "name": "벤치마킹", "status": "완료", "artifact": "bench_001.json"},
    {"step": 2, "name": "전략", "status": "완료", "artifact": "strategy_001.json"},
    {"step": 3, "name": "대본", "status": "진행중", "artifact": null}
  ],
  "revision_count": 1,
  "strategy_rollback_count": 0,
  "last_error": null,
  "approval_status": null,
  "manual_version": "shorts-v1",
  "prompt_version": "2026-04-06",
  "created_at": "2026-04-06T10:30:00",
  "updated_at": "2026-04-06T10:45:00"
}
```

**상태 전이표 (코드로 강제)**:
```
draft → under_review → revision → under_review (재검수)
under_review → approved → publish_ready → published
건너뛰기 불가. 역행 불가 (revision→under_review 제외).
승인 없이 발행 불가 (approved 없이 publish_ready 전이 차단).
```

### 컨텍스트 전략

```
모든 에이전트: CLAUDE.md (60줄)
파이프라인: 자기 agent.md + 해당 채널 manual
서브에이전트: 자기 agent.md + 호출 시 전달받은 작업 컨텍스트만
→ 다른 에이전트의 규칙, 다른 채널 매뉴얼은 안 읽음
→ 캐시: 안 바뀌는 정보(제품, 브랜드) 앞에 고정, 바뀌는 정보 뒤에
```

### 채널 매뉴얼 (channel-manuals/*.md)

각 매뉴얼 필수 5섹션:
1. 목적 — 한 줄
2. 금지 — 절대 안 되는 것 + 예시
3. 좋은 예시 3개
4. 품질 기준표 — 항목별 하한선
5. 실패 패턴 — 과거 문제들
+ 버전, 최종수정일

### 훅

**시스템 훅 (settings.local.json)**:
- PostToolUse: server.py 수정 후 문법검사. 성공=무출력, 실패=에러 반환→자체수정.

**파이프라인 내부 훅**:
- PRE: 중복체크(dedup_key), 상태확인(draft인지)
- POST: rule-validator(코드) → 실패항목만 출력 → 통과 시 script-reviewer(AI)
- STOP: 부분수정 3회 초과, 전략되돌림 1회 초과, API에러 3회 → HITL

### 마이그레이션

Phase 1: 숏츠 파일럿 (CLAUDE.md + 숏츠 파이프라인 + 서브에이전트 + 상태관리 + 훅)
Phase 2: 채널 확장 (나머지 9개 + /batch)
Phase 3: 분석+운영+Planning Loop + 디스코드
Phase 4: 하네스 고도화

---

## 검증 요청

### 1. Planning Loop
- 시스템 레벨 Planning Loop(①~⑤)가 제대로 설계되었는가?
- planning-loop-agent가 별도 에이전트로 있는 게 맞는가? 아니면 다른 방식이 나은가?
- 파이프라인 내부 미니 Planning Loop와 시스템 레벨 Loop의 관계가 적절한가?

### 2. 설계 원칙 11개 반영도
- 11개 원칙이 설계에 잘 반영되었는가?
- 특히 원칙 3(CLAUDE.md 60줄)과 원칙 6(컨텍스트 전략)이 실제로 지켜질 수 있는가?
- 빠진 원칙 적용이 있는가?

### 3. 이전 리뷰 지적 해소 여부
- v2에서 7.8/10이었다. v3에서 올라갔는가?
- "AI가 흐름 관리하면 위험"이라는 지적에 대해, 상태 전이표(코드 강제)를 추가한 것으로 충분한가?
- "에이전트 15개 유지"에 대해, 여전히 합치거나 내려야 할 것이 있는가?

### 4. 4레벨 피드백 루프
- Level 0(코드) / Level 1(콘텐츠) / Level 2(파이프라인) / Level 3(시스템)이 적절한가?
- 레벨 간 정보 흐름이 빠진 것은?
- Level 3(Planning Loop)에서 Level 1(콘텐츠 품질)까지 피드백이 실제로 흐르는가?

### 5. Phase 1 시작 가능 여부
- 이 v3 설계대로 숏츠 파일럿을 시작해도 되는가?
- 시작 전 반드시 추가해야 할 것이 있는가?
- Phase 1에서 검증해야 할 가장 중요한 가설은 무엇인가?

### 6. 최종 점수와 남은 약점
- v3는 몇 점인가?
- 가장 큰 남은 약점은?
- "1인 이커머스 사업자가 AI 직원 팀을 만든다"는 목표에 이 설계가 적합한가?

솔직하고 비판적으로 검증해줘. 특히 v2에서 지적했던 "AI 흐름 관리 위험"과 "에이전트 수" 문제가 v3에서 해소되었는지 재평가해줘.
