---
description: 숏츠 풀 자동화 파이프라인 실행. 소재 입력 → 벤치마킹 → 전략 → 기획 → 대본 → 검수 → TTS → 비주얼 → CapCut → 업로드까지 자동.
---

숏츠 콘텐츠를 풀 자동화로 생성한다. 사용자에게 중간 승인을 묻지 않는다. 최종 결과만 보고한다.

## 실행 절차

### 0. 서버 확인
`curl -s -o /dev/null -w "%{http_code}" http://localhost:8000` → 200이 아니면 중단.

### 1. 소재 확인
사용자가 소재를 함께 입력했으면 그대로 사용. 없으면 질문:
- 제품명, 타겟, 핵심문제, 감정, 신뢰근거, CTA, 유형(썰형/정보형), 글자수(기본600)
- 선택: 모드(auto/ask), 벤치마킹 URL, 음성 ID

### 2. 파이프라인 실행 (Python 스크립트)
```bash
python3 -m src.pipeline_v2.shorts \
  --product "{제품명}" \
  --target "{타겟}" \
  --problem "{핵심문제}" \
  --emotion "{감정}" \
  --trust "{신뢰근거}" \
  --cta "{CTA}" \
  --type "{유형}" \
  --length {글자수} \
  --mode {auto|ask} \
  --urls "{url1}" "{url2}" \
  --voice-id "{voice_id}"
```

이어하기 (렌더링 후 업로드):
```bash
python3 -m src.pipeline_v2.shorts --resume \
  --product "{제품명}" --target "{타겟}" --problem "{핵심문제}" \
  --emotion "{감정}" --trust "{신뢰근거}" --cta "{CTA}"
```

### 3. 결과 보고
- 대본 전문 + 품질 점수 + 리비전 횟수
- TTS 음성 길이 + 씬 수 + 이미지 수
- CapCut 프로젝트 경로
- YouTube URL (업로드 완료 시)
- 비용 요약
