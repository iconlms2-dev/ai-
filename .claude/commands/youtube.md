---
description: "유튜브 댓글 파이프라인 실행"
---

유튜브 댓글을 자동으로 생성한다. 사용자에게 중간 승인을 묻지 않는다. 최종 결과만 보고한다.

## 실행 절차

### 0. 서버 확인
`curl -s -o /dev/null -w "%{http_code}" http://localhost:8000` -> 200이 아니면 중단.

### 1. 소재 확인
사용자가 키워드와 브랜드 키워드를 함께 입력했으면 그대로 사용. 없으면 질문:
- keyword: 검색할 키워드 (필수)
- brand-keyword: 브랜드/제품 키워드 (필수)
- count: 영상당 댓글 수 (기본 3)

### 2. 파이프라인 실행 (Python 스크립트)
아래 스크립트를 Bash로 실행한다. 소재 정보를 인자에 채워 넣는다.
중간에 사용자에게 아무것도 묻지 않는다.

```bash
python3 -m src.pipeline_v2.youtube \
  --keyword "{키워드}" \
  --brand-keyword "{브랜드키워드}" \
  --count {댓글수}
```

### 이어하기
중단된 작업을 이어서 실행할 때:
```bash
python3 -m src.pipeline_v2.youtube --resume {job_id}
```

### 3. 결과 보고
스크립트 출력의 "최종 보고" 섹션을 사용자에게 보여준다.
- 영상별 댓글 전문 (3단 시나리오: 밑밥/해결사/쐐기)
- 리비전 횟수
- 검수 결과 (PASS/FAIL)
