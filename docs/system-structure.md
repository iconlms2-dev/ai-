# 시스템 전체 구조 (2026-04-08 기준, 계층 구조 활성화 반영)

## 1. 에이전트 (.claude/agents/) — 52개

### 역할 분리 원칙
- **pipeline** (opus): 흐름 제어만. writer/reviewer를 spawn하고 결과를 넘김. 콘텐츠 직접 생성/검수 안 함
- **strategist** (sonnet): 껍데기 상태. 향후 키워드별 전략 판단 로직 추가 시 활성화
- **writer** (sonnet): server.py API 호출 → 멘토 프롬프트로 콘텐츠 생성. job_state 수정 불가
- **reviewer** (sonnet): 1차 rule-validator(코드) + 2차 AI검수. PASS/FAIL 판정. 콘텐츠 수정 불가

### 총괄 (1개, model: opus)
| 에이전트 | 역할 |
|---------|------|
| master-orchestrator | 총괄 오케스트레이터 (사장). 멀티채널 배치 작업 분배, 우선순위 결정, 진행 보고 |

### 부장/팀장 (3개)
| 에이전트 | model | 역할 |
|---------|-------|------|
| content-lead | opus | **콘텐츠부장**. 12개 팀장(10채널 + 이미지 + 광고소재) 품질 관리 및 조율 |
| analytics-lead | sonnet | 분석팀장. 키워드 분석, 검색량 조회, 성과 수집, 리포트 생성 |
| ops-lead | sonnet | 운영팀장. 스케줄링, 배포, 계정 관리, 시스템 모니터링 |

### 채널별 팀장 — 흐름 제어 전용 (12개, model: opus)
| 에이전트 | 역할 | spawn 대상 (직원) |
|---------|------|-----------|
| shorts-pipeline | 숏츠 흐름 제어 + TTS | strategist, writer, reviewer |
| blog-pipeline | 블로그 흐름 제어 | writer, reviewer |
| cafe-seo-pipeline | 카페SEO 흐름 제어 | writer, reviewer |
| cafe-viral-pipeline | 카페바이럴 흐름 제어 | writer, reviewer |
| jisikin-pipeline | 지식인 흐름 제어 + Notion저장 | writer, reviewer |
| youtube-pipeline | 유튜브 흐름 제어 + 영상검색/수집 | writer, reviewer |
| tiktok-pipeline | 틱톡 흐름 제어 | writer, reviewer |
| community-pipeline | 커뮤니티 흐름 제어 | writer, reviewer |
| powercontent-pipeline | 파워컨텐츠 흐름 제어 | writer, reviewer |
| threads-pipeline | 쓰레드 흐름 제어 | writer, reviewer |
| image-pipeline | 이미지 크롤링(바이두/샤오홍슈), 모자이크, 라이브러리 관리 | (직접 처리) |
| ad-pipeline | 광고소재 크롤링, 분석, 생성 | (직접 처리) |

### 채널별 직원 (30개, model: sonnet)

| 채널 | strategist (전략) | writer (작성) | reviewer (검수) |
|------|------------------|--------------|----------------|
| shorts | **활성** (주제5개 생성) | **활성** (API호출) | **활성** (rule+AI+rollback) |
| blog | 껍데기 | **활성** (API호출) | **활성** (rule+AI) |
| cafe-seo | 껍데기 | **활성** (API호출) | **활성** (rule+AI) |
| cafe-viral | 껍데기 | **활성** (API호출) | **활성** (rule+AI) |
| jisikin | 껍데기 | **활성** (API호출) | **활성** (rule+AI) |
| youtube | 껍데기 | **활성** (API호출) | **활성** (rule+AI) |
| tiktok | 껍데기 | **활성** (API호출) | **활성** (rule+AI) |
| community | 껍데기 | **활성** (API호출) | **활성** (rule+AI) |
| powercontent | 껍데기 | **활성** (API호출) | **활성** (rule+AI) |
| threads | 껍데기 | **활성** (API호출) | **활성** (rule+AI) |

### 시스템 에이전트 (2개, model: sonnet)
| 에이전트 | 역할 |
|---------|------|
| code-reviewer | 코드 리뷰 (체크리스트 기반) |
| debugger | 에러 원인 분석 및 수정 |

### 유틸리티 에이전트 (4개)
| 에이전트 | 역할 |
|---------|------|
| keyword-analyzer | SERP 분석 + 경쟁 강도 + 상위글 분석 |
| data-researcher | 외부 소스 레퍼런스 수집 (읽기전용) |
| pattern-extractor | 레퍼런스에서 성공 패턴/팩트 추출 |
| video-analyst | YouTube 영상 정보 분석 |

---

## 2. 커맨드 (.claude/commands/) — 18개

### 콘텐츠 워크플로우 (10개)
| 커맨드 | 설명 |
|--------|------|
| /shorts | 숏츠 (소재→주제→대본→검수→TTS→저장) |
| /blog | 블로그 (키워드→제목→본문→검수→저장) |
| /cafe-seo | 카페SEO (키워드→제목→본문→댓글→검수→저장) |
| /cafe-viral | 카페바이럴 3단계 |
| /jisikin | 지식인 Q&A |
| /youtube | 유튜브 댓글 |
| /tiktok | 틱톡 스크립트 |
| /community | 커뮤니티 침투글 |
| /powercontent | 파워컨텐츠 (광고카피→랜딩본문→검수→저장) |
| /threads | 쓰레드 콘텐츠 |

### 시스템 (8개)
| 커맨드 | 설명 |
|--------|------|
| /deploy | 코드 변경→검증→안내서 반영→서버 재시작 |
| /verify | 코드 변경 후 검증 루프 |
| /restart | 서버 재시작 |
| /update-manual | 사용안내서 동기화 |
| /code-review | 코드 리뷰어 에이전트 실행 |
| /debug | 디버거 에이전트 실행 |
| /review | Gemini 교차검증 리뷰 프롬프트 생성 |
| /test-keyword | 테스트 키워드 분석 |

---

## 3. 채널 매뉴얼 (.claude/channel-manuals/) — 10개

| 매뉴얼 | 채널 |
|--------|------|
| blog-manual.md | 블로그 |
| cafe-seo-manual.md | 카페SEO |
| cafe-viral-manual.md | 카페바이럴 |
| community-manual.md | 커뮤니티 |
| jisikin-manual.md | 지식인 |
| powercontent-manual.md | 파워컨텐츠 |
| shorts-manual.md | 숏츠 |
| threads-manual.md | 쓰레드 |
| tiktok-manual.md | 틱톡 |
| youtube-manual.md | 유튜브 |

---

## 4. v2 파이프라인 (src/pipeline_v2/) — 15개 파일, 2656줄

### 공통 인프라 (4개)
| 파일 | 줄수 | 역할 |
|------|------|------|
| base_pipeline.py | 192 | BasePipeline (모든 워크플로우 부모 클래스) |
| state_machine.py | 177 | ProjectState (파일시스템 기반 상태 전이) |
| common.py | 106 | SSE 파싱, API 호출, AI 리뷰 유틸 |
| rule_validators.py | 344 | 채널별 규칙 기반 검수기 |
| tool_boundary.py | 163 | AI↔코드 경계 분리 |

### 채널별 워크플로우 (10개)
| 파일 | 클래스 | 줄수 | 단계 |
|------|--------|------|------|
| shorts.py | ShortsPipeline | 188 | input→benchmark→strategy→brief→script→review→audio→save (8) |
| blog.py | BlogPipeline | 146 | input→benchmark→strategy→brief→write→review→save (7) |
| cafe_seo.py | CafeSeoPipeline | 145 | input→benchmark→strategy→brief→write→review→save (7) |
| cafe_viral.py | CafeViralPipeline | 165 | input→benchmark→strategy→brief→write→review→save (7) |
| jisikin.py | JisikinPipeline | 163 | input→benchmark→strategy→brief→write→review→save (7) |
| youtube.py | YoutubePipeline | 246 | input→search→fetch_info→write→review→save (6) |
| tiktok.py | TiktokPipeline | 142 | input→benchmark→strategy→brief→write→review→save (7) |
| community.py | CommunityPipeline | 161 | input→benchmark→strategy→brief→write→review→save (7) |
| powercontent.py | PowercontentPipeline | 166 | input→benchmark→strategy→brief→write→review→save (7) |
| threads.py | ThreadsPipeline | 151 | input→benchmark→strategy→brief→write→review→save (7) |

### 상태 전이 (state_machine.py 강제)
```
draft → under_review → revision → under_review → approved → publish_ready → published
건너뛰기 불가. 역행 불가 (revision→under_review 제외). 승인 없이 발행 불가.
```

---

## 5. 서비스 계층 (src/services/) — 6개 파일

| 파일 | 역할 |
|------|------|
| config.py | 환경변수, 경로, 상수, ThreadPoolExecutor(3) |
| ai_client.py | Claude API 호출 + 토큰 추적 (api_usage.json) |
| notion_client.py | Notion DB 연동 (CRUD) |
| naver_search.py | 네이버 검색 API |
| selenium_pool.py | 브라우저 풀 관리 (생성/반환/close) |
| common.py | 공통 유틸 |

---

## 6. API 라우터 (src/api/) — 22개 라우터

### 콘텐츠 (10개)
| 라우터 | 프리픽스 | 함수 수 | 설명 |
|--------|---------|---------|------|
| blog.py | /api/blog | 13 | 생성, 금칙어, 노션 저장 |
| cafe.py | /api/cafe | 25 | 생성, 댓글, 노션 저장, DOCX |
| viral.py | /api/viral | 9 | 3단계 생성, 노션 저장 |
| jisikin.py | /api/jisikin | 13 | 생성, 노션 저장 |
| threads.py | /api/threads | 33 | 계정, 생성, 발행, 크롤링 |
| shorts.py | /api/shorts | 20 | 주제, 대본, 훅, TTS |
| tiktok.py | /api/tiktok | 6 | 생성, 노션 저장 |
| community.py | /api/community | 7 | 생성, 노션 저장 |
| powercontent.py | /api/powercontent | 10 | 분석, 생성, 노션 저장 |
| youtube.py | /api/youtube | 43 | 검색, 정보수집, 댓글생성, 자동게시 |

### 인프라/도구 (12개)
| 라우터 | 프리픽스 | 함수 수 | 설명 |
|--------|---------|---------|------|
| keywords.py | /api/keywords | 11 | 업로드, 확장, 검색량, 분석, 노션 저장 |
| batch.py | /api/batch | 5 | 다채널 일괄 생성 |
| schedule.py | /api/schedule, /api/report, /api/scheduler | 17 | 오늘/주간 스케줄, 리포트, 스케줄러 |
| photo.py | /api/photo | 15 | 번역, 크롤링, 모자이크 |
| ad.py | /api/ad | 13 | 크롤링, 분석, 생성 |
| cafe24.py | /api/cafe24 | 9 | 인증, 매출, 분석 |
| naver.py | /api/naver | 6 | 네이버 계정 CRUD |
| performance.py | /api/performance | 15 | 수집, 대시보드 |
| prompt_test.py | /api/prompt-test | 8 | 프롬프트 테스트 |
| status.py | /api/status | 7 | 서버 상태, 헬스체크 |
| static.py | /api/ | 4 | 정적 파일 서빙 (dashboard, 안내서) |

---

## 7. Slack 봇 (slack_bot.py) — 12개 채널 + HQ 에이전트

### 채널
```
#headquarters  — 총괄 (자연어 대화, Haiku로 의도 파악)
#shorts        — 숏츠 팀
#blog          — 블로그 팀
#cafe-seo      — 카페SEO 팀
#cafe-viral    — 카페바이럴 팀
#jisikin       — 지식인 팀
#youtube       — 유튜브 팀
#tiktok        — 틱톡 팀
#community     — 커뮤니티 팀
#powercontent  — 파워컨텐츠 팀
#threads       — 쓰레드 팀
#report        — 리포트/다이제스트
```

### 명령어
| 명령어 | 기능 |
|--------|------|
| !상태 | 서버/작업 현황 |
| !비용 | API 비용 조회 (이번 달/오늘/채널별) |
| !도움 | 전체 명령어 목록 |
| !채널생성 | 12개 채널 자동 생성 |
| !소재설정 | 기본 소재 프리셋 저장 |
| !소재확인 | 현재 소재 프리셋 확인 |
| !배치 | 여러 채널 일괄 실행 |
| !실행 | 단일 채널 직접 실행 |
| !다이제스트 | 수동 리포트 생성 |
| !스케줄확인 | 현재 스케줄 확인 |
| !스케줄설정 | 매일 자동 실행 등록 |

### HQ 에이전트
#headquarters에서 자연어 대화 → Haiku가 의도 파악 → 해당 명령 자동 실행

---

## 8. 모델 사용

| 용도 | 모델 | 단가 |
|------|------|------|
| 콘텐츠 생성 (ai_client.py) | Claude Sonnet 4 | $3.0/M input, $15.0/M output |
| HQ 의도 파악 (slack_bot.py) | Claude Haiku 4.5 | $0.8/M input, $4.0/M output |
| 키워드 접촉지점 판별 (keywords.py) | Gemini 2.0 Flash | 무료 |
| Claude Code 대화 (현재 세션) | Claude Opus 4.6 | Max 구독 포함 |

---

## 9. 프로젝트 디렉토리 구조

```
안티그래비티/
├── server.py                  ← 진입점 (~8줄), uvicorn 실행만
├── dashboard.html             ← 관리자 대시보드 UI
├── 사용안내서.html              ← 사용자 매뉴얼
├── slack_bot.py               ← Slack 연동 봇
├── prompt_server.py           ← 프롬프트 테스트 서버 (:8001)
├── prompt-test.html           ← 프롬프트 테스트 UI
│
├── src/
│   ├── api/                   ← FastAPI 라우터 (22개)
│   ├── services/              ← 공통 서비스 (6개)
│   ├── pipeline_v2/           ← 상태머신 기반 파이프라인 (15개)
│   ├── youtube_bot.py         ← 유튜브 댓글 봇
│   ├── cafe_comment_bot.py    ← 카페 댓글 봇
│   ├── fingerprint.py         ← 브라우저 핑거프린트
│   ├── safety_rules.py        ← 안전 규칙
│   ├── cafe_safety_rules.py   ← 카페 안전 규칙
│   ├── smm_client.py          ← SMM 패널 클라이언트
│   └── comment_tracker.py     ← 댓글 추적
│
├── .claude/
│   ├── agents/                ← AI 에이전트 정의 (50개)
│   ├── commands/              ← 슬래시 커맨드 (18개)
│   ├── channel-manuals/       ← 채널별 매뉴얼 (10개)
│   └── settings.json          ← 훅 설정 (PostToolUse, Stop, Notification)
│
├── tests/                     ← 테스트 (ci_gate, feedback_loop, unit tests)
├── docs/                      ← 문서 (아키텍처, 학습이력, API설정)
│
├── [운영 데이터 — .gitignore 제외 대상]
│   ├── job_state.json         ← 작업 상태
│   ├── weekly_schedule.json   ← 주간 스케줄
│   ├── keyword_progress.json  ← 키워드 진행상황
│   ├── cafe24_token.json      ← Cafe24 토큰
│   ├── naver_accounts.json    ← 네이버 계정
│   └── api_usage.json         ← API 토큰 사용량 추적
│
└── [출력 폴더 — 비어있을 수 있음]
    ├── outputs/               ← 파워컨텐츠/카페/사진 출력
    ├── ad_outputs/            ← 광고 크리에이티브 출력
    ├── shorts_output/         ← 숏츠 TTS 오디오 출력
    └── temp_photos/           ← 사진 임시 저장
```

---

## 10. ultraplan 재설계 주요 변경 (2026-04-07)

| 변경 전 | 변경 후 |
|---------|---------|
| server.py 모놀리스 (7744줄) | server.py 진입점 (~8줄) + src/api/ 모듈화 (22개 라우터) |
| 에이전트 46개 (플랫 구조) | 에이전트 50개 (계층 구조: 사장→부장/팀장3→채널별팀장10→직원30→시스템6) |
| 팀장 없음 | master-orchestrator + content/analytics/ops-lead 추가 |
| 파이프라인 없음 | src/pipeline_v2/ 상태머신 기반 (base_pipeline + state_machine + rule_validators + tool_boundary) |
| 검수 1단계 (AI만) | 품질 게이트 2단계 (1차 rule-validator 코드 + 2차 script-reviewer AI) |
| 상태 관리 없음 | 상태 전이 강제 (draft→under_review→approved→published, 건너뛰기/역행 불가) |
| 서비스 분리 없음 | src/services/ 공통 서비스 분리 (config, ai_client, notion, naver, selenium, common) |
| 코드 검수 수동 | PostToolUse 훅으로 py_compile 자동 검증 |
