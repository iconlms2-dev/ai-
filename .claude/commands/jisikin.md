---
description: "지식인 Q&A 파이프라인 실행"
---

지식인 Q&A를 자동으로 생성한다. 사용자에게 중간 승인을 묻지 않는다. 최종 결과만 보고한다.

## 실행 절차

### 0. 서버 확인
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000 -> 200이 아니면 중단.

### 1. 소재 확인
사용자가 소재를 함께 입력했으면 그대로 사용. 없으면 질문:
- 키워드, 제품명, 브랜드키워드, USP, 타겟, 성분

### 2. 파이프라인 실행 (Python 스크립트)
아래 스크립트를 Bash로 실행한다. 소재 정보를 인자로 채워 넣는다.
중간에 사용자에게 아무것도 묻지 않는다.

```bash
python3 -m src.pipeline_v2.jisikin \
  --keyword "{키워드}" \
  --product-name "{제품명}" \
  --brand-keyword "{브랜드키워드}" \
  --usp "{USP}" \
  --target "{타겟}" \
  --ingredients "{성분}"
```

### 이어하기
중단된 작업을 이어서 실행할 때:
```bash
python3 -m src.pipeline_v2.jisikin --resume {job_id}
```

### 3. 결과 보고
스크립트 출력의 최종 보고 섹션을 사용자에게 보여준다.
- 질문 제목, 질문 본문, 답변 1/2, 답변 글자수, 리비전 횟수, 저장된 job_id
