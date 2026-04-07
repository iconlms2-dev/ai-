# 안티그래비티

## 금지
- .env 커밋 금지
- API 키 하드코딩 금지
- 검수 미통과 콘텐츠 저장 금지
- 승인 없이 발행 금지
- bare `except:` 금지 → `except Exception as e:` 사용
- 코드 변경 시 사용안내서.html 동기화 필수

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

## 아키텍처
server.py(FastAPI :8000) + dashboard.html + .claude/agents/ + .claude/commands/
각 채널 독립 오케스트레이터. 총괄 없음.

## 참조
- docs/agent-architecture-final.md — 에이전트 전체 설계
- docs/api-config.md — API 설정
- docs/serp-codes.md — 네이버 섹션 코드
- .claude/channel-manuals/ — 채널별 매뉴얼

## 학습 루프
| 날짜 | 실수 | 추가 규칙 |
|------|------|----------|
| 04-01 | SSE generate()에 에러 처리 없음 | 모든 SSE는 try/except + error 이벤트 |
| 04-01 | bare except 사용 | except Exception as e 강제 |
| 04-01 | lock 없이 공유 상태 접근 | 공유 상태는 반드시 lock |
| 04-01 | 브라우저 실패 시 close() 미호출 | 예외 시 반드시 close() |

## 코드 자동 검수 루프 (필수)
Python 파일 수정 완료 후 반드시 아래 순서를 따른다:
1. **문법 검사**: `py_compile` 실행. 실패 시 즉시 수정.
2. **code-reviewer 실행**: Agent(subagent_type="code-reviewer")로 변경 사항 리뷰.
   - LGTM → 다음 단계.
   - 수정 필요 → 3번으로.
3. **debugger 실행**: 이슈 발견 시 Agent(subagent_type="debugger")로 자동 수정.
   - 수정 후 1번부터 재실행 (최대 2회).
4. 2회 초과 시 사용자에게 보고.

적용 대상: server.py, slack_bot.py, src/**/*.py, *_pipeline.py

## 검증
1. `python3 -c "import py_compile; py_compile.compile('server.py', doraise=True)"`
2. 서버 기동 확인
3. 해당 기능 UI 테스트
