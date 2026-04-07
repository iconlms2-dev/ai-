# 시스템 전체 구조 (2026-04-07 기준)

## 1. 에이전트 (.claude/agents/) — 46개

### 채널 팀장 — 워크플로우 오케스트레이터 (10개, model: opus)
| 에이전트 | 역할 |
|---------|------|
| shorts-pipeline | 숏츠 워크플로우 총괄 |
| blog-pipeline | 블로그 워크플로우 총괄 |
| cafe-seo-pipeline | 카페SEO 워크플로우 총괄 |
| cafe-viral-pipeline | 카페바이럴 워크플로우 총괄 |
| jisikin-pipeline | 지식인 워크플로우 총괄 |
| youtube-pipeline | 유튜브 워크플로우 총괄 |
| tiktok-pipeline | 틱톡 워크플로우 총괄 |
| community-pipeline | 커뮤니티 워크플로우 총괄 |
| powercontent-pipeline | 파워컨텐츠 워크플로우 총괄 |
| threads-pipeline | 쓰레드 워크플로우 총괄 |

### 채널별 전담 에이전트 (30개, model: sonnet)

각 채널마다 strategist, writer, reviewer 3명씩 전담.
프롬프트는 추후 멘토 프롬프트 적용 예정.

| 채널 | strategist (전략) | writer (작성) | reviewer (검수) |
|------|------------------|--------------|----------------|
| shorts | shorts-strategist | shorts-writer | shorts-reviewer |
| blog | blog-strategist | blog-writer | blog-reviewer |
| cafe-seo | cafe-seo-strategist | cafe-seo-writer | cafe-seo-reviewer |
| cafe-viral | cafe-viral-strategist | cafe-viral-writer | cafe-viral-reviewer |
| jisikin | jisikin-strategist | jisikin-writer | jisikin-reviewer |
| youtube | youtube-strategist | youtube-writer | youtube-reviewer |
| tiktok | tiktok-strategist | tiktok-writer | tiktok-reviewer |
| community | community-strategist | community-writer | community-reviewer |
| powercontent | powercontent-strategist | powercontent-writer | powercontent-reviewer |
| threads | threads-strategist | threads-writer | threads-reviewer |

### 시스템 에이전트 (2개, 공용)
| 에이전트 | 역할 |
|---------|------|
| code-reviewer | 코드 리뷰 (체크리스트 기반) |
| debugger | 에러 원인 분석 및 수정 |

### 유틸리티 에이전트 (4개, 공용)
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

blog-manual, cafe-seo-manual, cafe-viral-manual, community-manual, jisikin-manual, powercontent-manual, shorts-manual, threads-manual, tiktok-manual, youtube-manual

---

## 4. v2 워크플로우 (src/pipeline_v2/) — 14개 파일

### 공통 인프라
| 파일 | 역할 |
|------|------|
| base_pipeline.py | BasePipeline (모든 워크플로우 부모 클래스) |
| state_machine.py | ProjectState (파일시스템 기반 상태 전이) |
| common.py | SSE 파싱, API 호출, AI 리뷰 유틸 |
| rule_validators.py | 채널별 규칙 기반 검수기 |

### 채널별 워크플로우
| 파일 | 클래스 | 단계 |
|------|--------|------|
| shorts.py | ShortsPipeline | input→benchmark→strategy→brief→script→review→audio→save (8단계) |
| blog.py | BlogPipeline | input→benchmark→strategy→brief→write→review→save (7단계) |
| cafe_seo.py | CafeSeoPipeline | input→benchmark→strategy→brief→write→review→save (7단계) |
| cafe_viral.py | CafeViralPipeline | input→benchmark→strategy→brief→write→review→save (7단계) |
| jisikin.py | JisikinPipeline | input→benchmark→strategy→brief→write→review→save (7단계) |
| youtube.py | YoutubePipeline | input→search→fetch_info→write→review→save (6단계) |
| tiktok.py | TiktokPipeline | input→benchmark→strategy→brief→write→review→save (7단계) |
| community.py | CommunityPipeline | input→benchmark→strategy→brief→write→review→save (7단계) |
| powercontent.py | PowercontentPipeline | input→benchmark→strategy→brief→write→review→save (7단계) |
| threads.py | ThreadsPipeline | input→benchmark→strategy→brief→write→review→save (7단계) |

---

## 5. Slack 봇 (slack_bot.py) — 12개 채널 + HQ 에이전트

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

## 6. server.py API 엔드포인트 (주요 그룹)

| 그룹 | 프리픽스 | 설명 |
|------|---------|------|
| 키워드 | /api/keywords/* | 업로드, 확장, 검색량, 분석, 노션 저장 |
| 블로그 | /api/blog/* | 생성, 금칙어, 노션 저장 |
| 카페SEO | /api/cafe/* | 생성, 댓글, 노션 저장, DOCX |
| 카페바이럴 | /api/viral/* | 3단계 생성, 노션 저장 |
| 지식인 | /api/jisikin/* | 생성, 노션 저장 |
| 유튜브 | /api/youtube/* | 검색, 정보수집, 댓글생성, 자동게시 |
| 틱톡 | /api/tiktok/* | 생성, 노션 저장 |
| 숏츠 | /api/shorts/* | 주제, 대본, 훅, TTS |
| 커뮤니티 | /api/community/* | 생성, 노션 저장 |
| 파워컨텐츠 | /api/powercontent/* | 분석, 생성, 노션 저장 |
| 쓰레드 | /api/threads/* | 계정, 생성, 발행, 크롤링 |
| 사진 | /api/photo/* | 번역, 크롤링, 모자이크 |
| 광고 | /api/ad/* | 크롤링, 분석, 생성 |
| 스케줄 | /api/schedule/* | 오늘/주간 |
| 리포트 | /api/report/* | 생성, AI 액션 |
| 성과 | /api/performance/* | 수집, 대시보드 |
| Cafe24 | /api/cafe24/* | 인증, 매출, 분석 |

---

## 7. 모델 사용

| 용도 | 모델 | 비용 |
|------|------|------|
| 콘텐츠 생성 (server.py) | Claude Sonnet 4 | ~$0.05~0.15/건 |
| HQ 의도 파악 (slack_bot.py) | Claude Haiku 4.5 | ~$0.001/건 |
| 키워드 접촉지점 판별 (server.py) | Gemini 2.0 Flash | 무료 |
