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
.claude/agents/ — 계층: master-orchestrator → 팀장(content/analytics/ops-lead) → 채널별 직원

## 상태 전이 (코드 강제)
draft → under_review → revision → under_review → approved → publish_ready → published
건너뛰기 불가. 역행 불가 (revision→under_review 제외). 승인 없이 발행 불가.

## 품질 게이트
1차: rule-validator (코드) → 실패 항목만 부분 수정
2차: script-reviewer (AI) → 항목별 하한선
부분 수정 최대 3회. 전략 되돌림 최대 1회. 초과 시 HITL.

## 컨텍스트 전략
- 해당 채널 매뉴얼만 로드 (다른 채널 안 읽음)
- 안 바뀌는 정보(제품, 브랜드) 앞에 고정
- 바뀌는 정보(키워드, 분석결과) 뒤에 배치

## 코드 자동 검수 (필수)
Python 파일 수정 후:
1. `py_compile` 실행 → 실패 시 즉시 수정
2. code-reviewer 실행 → LGTM이면 완료
3. 이슈 발견 시 debugger로 자동 수정 → 1번부터 재실행 (최대 2회)
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

## 최근 학습 (전체: docs/learning-log.md)
| 날짜 | 실수 | 규칙 |
|------|------|------|
| 04-01 | SSE generate()에 에러 처리 없음 | 모든 SSE는 try/except + error 이벤트 |
| 04-01 | bare except 사용 | except Exception as e 강제 |
| 04-01 | lock 없이 공유 상태 접근 | 공유 상태는 반드시 lock |
| 04-01 | 브라우저 실패 시 close() 미호출 | 예외 시 반드시 close() |
| 04-07 | server.py 모놀리스 7744줄 | src/api/ 모듈화, server.py는 진입점만 |
