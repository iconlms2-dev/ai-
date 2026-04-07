---
description: 마케팅 자동화 서버 재시작
---

다음 순서대로 실행해주세요:
1. 포트 8000을 사용 중인 프로세스를 종료합니다 (`lsof -ti:8000 | xargs kill -9`)
2. 1초 대기
3. server.py를 백그라운드로 실행합니다 (`cd /Users/iconlms/Desktop/안티그래비티 && python3 server.py &`)
4. 2초 대기 후 브라우저에서 http://localhost:8000 을 엽니다 (`open http://localhost:8000`)
5. "서버가 재시작되었습니다" 라고 알려주세요
