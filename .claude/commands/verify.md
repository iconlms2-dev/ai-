---
description: 코드 변경 후 검증 루프 실행
---

코드 변경 후 4단계 품질 게이트를 실행합니다:

## Stage 1: 기본 검증
1. **문법 검사**: `python3 -c "import py_compile; py_compile.compile('server.py', doraise=True); print('✅ server.py 문법 정상')"`
2. **서버 기동 테스트**: port 8000 kill 후 server.py 실행, 2초 대기 후 `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000` 으로 200 응답 확인
3. **핵심 API 체크**: `curl -s http://localhost:8000/api/youtube/accounts` 등 주요 엔드포인트 호출하여 500 에러 없는지 확인

## Stage 2: code-reviewer 실행
4. code-reviewer 에이전트로 변경된 파일 리뷰 → 점수 + 감점 내역

## Stage 3: 회귀 패턴 검증
5. CLAUDE.md 최근 학습 항목에 기록된 이슈 패턴이 재발하지 않았는지 확인:
   - SSE generate()에 에러 처리 존재하는지
   - bare except 사용하지 않는지
   - 공유 상태 접근 시 lock 사용하는지
   - 브라우저/드라이버 예외 시 close() 호출하는지

## Stage 4: 최종 판정 (점수 집계)
6. 100점 시작, 감점 집계:
   - 문법 검사 실패: -30
   - 서버 기동 실패: -40
   - API 체크 실패: 항목당 -15
   - code-reviewer 감점: 그대로 반영
   - 회귀 패턴 발견: 항목당 -10
7. 최종 판정:
   - **PASS (90+)**: "✅ 검증 완료 (점수/100)"
   - **CONCERNS (70-89)**: "⚠️ 경미한 이슈 (점수/100). 계속하시겠습니까?" → 사용자 선택
   - **FAIL (<70)**: 원인 + 수정 방법 제시 → 직접 수정 후 재검증 (최대 3회 루프)
