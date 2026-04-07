---
description: "카페바이럴 3단계 파이프라인 실행"
---

카페바이럴 콘텐츠를 3단계(일상글-고민글-침투글)로 자동 생성한다. 사용자에게 중간 승인을 묻지 않는다. 최종 결과만 보고한다.

## 실행 절차

### 0. 서버 확인
`curl -s -o /dev/null -w "%{http_code}" http://localhost:8000` -> 200이 아니면 중단.

### 1. 소재 확인
사용자가 소재를 함께 입력했으면 그대로 사용. 없으면 질문:
- 타겟카테고리, 타겟, 일상주제, 고민키워드, 제품카테고리, 브랜드키워드, 제품명, USP, 성분

### 2. 파이프라인 실행 (Python 스크립트)
아래 스크립트를 Bash로 실행한다. 소재 정보를 인자로 채워 넣는다.
중간에 사용자에게 아무것도 묻지 않는다.

```bash
python3 -m src.pipeline_v2.cafe_viral \
  --category "{타겟카테고리}" \
  --target "{타겟}" \
  --topic "{일상주제}" \
  --concern "{고민키워드}" \
  --product-category "{제품카테고리}" \
  --brand-keyword "{브랜드키워드}" \
  --product-name "{제품명}" \
  --usp "{USP}" \
  --ingredients "{성분}"
```

### 이어하기
중단된 작업을 이어서 실행할 때:
```bash
python3 -m src.pipeline_v2.cafe_viral --resume {job_id}
```

### 3. 결과 보고
스크립트 출력의 "최종 보고" 섹션을 사용자에게 보여준다.
- 3단계 각각의 제목 + 본문 앞부분
- 3단계 댓글
- 각 단계 글자수
- 리비전 횟수
- 저장된 job_id
