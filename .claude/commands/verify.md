---
description: 코드 변경 후 검증 루프 실행
---

코드 변경 후 다음 검증을 순서대로 실행합니다:

1. **문법 검사**: `python3 -c "import py_compile; py_compile.compile('server.py', doraise=True); print('✅ server.py 문법 정상')"`
2. **서버 기동 테스트**: port 8000 kill 후 server.py 실행, 2초 대기 후 `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000` 으로 200 응답 확인
3. **핵심 API 체크**: `curl -s http://localhost:8000/api/youtube/accounts` 등 주요 엔드포인트 호출하여 500 에러 없는지 확인
4. 모든 검증 통과 시 "✅ 검증 완료" 보고, 실패 시 원인과 수정 방법 제시
5. 검증 실패한 부분이 있으면 직접 수정 후 다시 검증 (최대 3회 루프)
