# 안티그래비티

## 절대 금지
- .env 커밋 금지 / API 키 하드코딩 금지 / 프로덕션 키·토큰 로그 출력 금지
- server.py에 직접 엔드포인트 추가 금지 → src/api/{domain}.py에 추가
- 검수 미통과 콘텐츠 Notion 저장 금지 / 승인 없이 발행 금지
- bare `except:` 금지 → `except Exception as e:` 사용
- Notion DB 삭제 API 호출 금지
- 코드 변경 시 사용안내서.html 동기화 필수

## 아키텍처
server.py(진입점 ~8줄) → src/api/create_app() → 20개 라우터
src/services/ — config, common, ai_client, notion_client, naver_search, selenium_pool
src/pipeline_v2/ — 채널별 파이프라인 (state_machine, rule_validators, tool_boundary)
.claude/agents/ — 계층: 사장(master-orchestrator) → 콘텐츠부장(content-lead)/분석팀장/운영팀장 → 채널별 팀장(pipeline) → 직원(strategist/writer/reviewer)

## 상태 전이 (코드 강제)
draft → under_review → revision → under_review → approved → publish_ready → published
건너뛰기 불가. 역행 불가 (revision→under_review 제외). 승인 없이 발행 불가.

## 4단계 품질 게이트

### 판정 체계
| 판정 | 점수 | 의미 | 액션 |
|------|------|------|------|
| PASS | 90-100 | 모든 기준 충족 | 즉시 다음 단계 |
| CONCERNS | 70-89 | 경미한 이슈, 발행 가능 | 사용자에게 경고 표시 후 선택 |
| FAIL | 0-69 | 차단 이슈 존재 | 수정 루프 진입 |
| WAIVED | - | 사용자 승인 예외 | 사유 기록 후 진행 |

### 검수 스테이지
- Stage 1: rule-validator (코드) → 실패 항목만 부분 수정
- Stage 2: AI 심층 리뷰 → 차원별 점수
- Stage 3: 회귀 패턴 검증 → 최근 학습 항목 재발 체크
- Stage 4: 최종 판정 → 점수 집계 후 4단계 판정

### 콘텐츠 품질 점수 = 100 - 감점
- 규칙 검증 실패: 항목당 -10 ~ -15
- AI 리뷰 차원별 감점: 차원당 -5 ~ -20 (10점 만점 중 하한선 미달 시)
- 회귀 패턴 발견: 항목당 -10

### 코드 품질 점수 = 100 - 감점
- 에러 처리 누락: -15 (상), -10 (중)
- 보안 이슈: -25
- 동시성/리소스 이슈: -15
- bare except: -10
- 스타일/컨벤션: -5

### 판정 분기
- PASS (90+) → 즉시 다음 단계
- CONCERNS (70-89) → 사용자 선택: 발행 진행 / 수정 요청 / 예외 승인(WAIVED)
- FAIL (<70) → 수정 루프 진입 (부분 수정 최대 3회, 전략 되돌림 최대 1회, 초과 시 HITL)
- WAIVED → 사유 기록 후 진행 (부분수정 3회 초과 시 최고점 버전 + WAIVED 옵션 제시)

## 컨텍스트 전략
- 해당 채널 매뉴얼만 로드 (다른 채널 안 읽음)
- 안 바뀌는 정보(제품, 브랜드) 앞에 고정
- 바뀌는 정보(키워드, 분석결과) 뒤에 배치

## 코드 자동 검수 (필수)
Python 파일 수정 후:
1. `py_compile` 실행 → 실패 시 즉시 수정
2. code-reviewer 실행 → PASS(90+)이면 완료, CONCERNS(70-89)이면 경고 표시
3. FAIL(<70) 시 debugger로 자동 수정 → 1번부터 재실행 (최대 2회)
4. 2회 초과 시 사용자에게 보고
적용 대상: server.py, src/**/*.py

## 검증
1. `python3 -c "import py_compile; py_compile.compile('server.py', doraise=True)"`
2. `python3 -c "from src.api import create_app; app = create_app(); print(len(app.routes))"`
3. `python3 -m pytest tests/ -v` (있으면)

## 참조
- docs/agent-architecture-final.md — 에이전트 설계
- docs/learning-log.md — 학습 이력 (실수 → 규칙 추가)
- docs/api-config.md — API 설정
- .claude/channel-manuals/ — 채널별 매뉴얼
- .claude/skills/ — 메타 스킬 (blueprint→deep-dive→구현→autoresearch→reflect)

## Context Utilization Display
- 모든 응답 끝에 예상 컨텍스트 사용률 표시: `[Context: ~X%]`
- `/context` 명령어의 실제 토큰 수치를 기준으로 추정. 감으로 부풀리지 않는다.
- 장시간 작업(멀티스텝 도구 체인, 백그라운드 처리) 중 5% 임계값을 넘을 때마다 인라인 마일스톤 표시: `─── Context milestone: ~X% ───`

## 최근 학습 (전체: docs/learning-log.md)
| 날짜 | 실수 | 규칙 |
|------|------|------|
| 04-01 | SSE generate()에 에러 처리 없음 | 모든 SSE는 try/except + error 이벤트 |
| 04-01 | bare except 사용 | except Exception as e 강제 |
| 04-01 | lock 없이 공유 상태 접근 | 공유 상태는 반드시 lock |
| 04-01 | 브라우저 실패 시 close() 미호출 | 예외 시 반드시 close() |
| 04-07 | server.py 모놀리스 7744줄 | src/api/ 모듈화, server.py는 진입점만 |
