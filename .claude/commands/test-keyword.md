---
description: 테스트 키워드로 분석 파이프라인 테스트
---

테스트 키워드 "전립선 영양제"로 전체 파이프라인을 테스트합니다:
1. 서버가 실행 중인지 확인 (http://localhost:8000 접속 가능한지)
2. 키워드 확장 API 호출 테스트: POST /api/keywords/expand
3. SERP 분석 API 호출 테스트: POST /api/keywords/analyze
4. 노션 저장 API 호출 테스트: POST /api/keywords/save-notion
5. 각 단계의 응답 상태와 결과를 요약해서 보고
6. 에러가 있으면 원인과 해결 방법 제시
