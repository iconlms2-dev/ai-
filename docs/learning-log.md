# 학습 이력 (Learning Log)

에이전트 실수 발생 시 자동으로 기록됨. CLAUDE.md에는 최근 5건만 유지.

| 날짜 | 실수 | 추가 규칙 |
|------|------|----------|
| 04-01 | SSE generate()에 에러 처리 없음 | 모든 SSE는 try/except + error 이벤트 |
| 04-01 | bare except 사용 | except Exception as e 강제 |
| 04-01 | lock 없이 공유 상태 접근 | 공유 상태는 반드시 lock |
| 04-01 | 브라우저 실패 시 close() 미호출 | 예외 시 반드시 close() |
| 04-07 | server.py 모놀리스 7744줄 | src/api/ 모듈화, server.py는 진입점만 |
