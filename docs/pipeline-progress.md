# 파이프라인 구축 진행 상황

> 다음 세션에서 이 파일을 읽고 이어서 작업할 것.
> 설계서: docs/agent-architecture-final.md
> 원칙: CLAUDE.md 참조

## 코드 권한
- 코드 관련은 전권 위임. 승인 묻지 마라.
- 기획/구조/문제 발생 시에만 사용자에게 질문.
- settings.local.json에 Bash(*), Edit(*) 등 전부 자동 허용 설정됨.

## 채널별 진행 상황

| 채널 | v1 pipeline.py | v2 pipeline | command.md | manual.md | agent.md | 상태 |
|------|----------------|-------------|------------|-----------|----------|------|
| 숏츠 | ✅ | ✅ | ✅ | ✅ | ✅ | **v2 완료** |
| 블로그 | ✅ | ✅ | ✅ | ✅ | ✅ | **v2 완료** |
| 카페SEO | ✅ | ✅ | ✅ | ✅ | ✅ | **v2 완료** |
| 카페바이럴 | ✅ | ✅ | ✅ | ✅ | ✅ | **v2 완료** |
| 지식인 | ✅ | ✅ | ✅ | ✅ | ✅ | **v2 완료** |
| 유튜브 | ✅ | ✅ | ✅ | ✅ | ✅ | **v2 완료** |
| 틱톡 | ✅ | ✅ | ✅ | ✅ | ✅ | **v2 완료** |
| 커뮤니티 | ✅ | ✅ | ✅ | ✅ | ✅ | **v2 완료** |
| 파워컨텐츠 | ✅ | ✅ | ✅ | ✅ | ✅ | **v2 완료** |
| 쓰레드 | ✅ | ✅ | ✅ | ✅ | ✅ | **v2 완료** |

## 현재 상태: 10개 채널 v2 완성

### v2 구조
```
src/pipeline_v2/
  __init__.py
  state_machine.py     # 파일시스템 기반 상태 머신 (ProjectState)
  common.py            # SSE 파싱, 서버 체크, AI 리뷰 호출
  rule_validators.py   # 채널별 규칙 검수기 (코드 강제)
  base_pipeline.py     # 공통 베이스 (run/resume/revision_loop)
  shorts.py            # 숏츠 파이프라인
  blog.py              # 블로그
  cafe_seo.py          # 카페SEO
  cafe_viral.py        # 카페바이럴
  jisikin.py           # 지식인
  youtube.py           # 유튜브 댓글
  tiktok.py            # 틱톡
  community.py         # 커뮤니티
  powercontent.py      # 파워컨텐츠
  threads.py           # 쓰레드
```

### v2 vs v1 변경점
| 항목 | v1 | v2 |
|------|----|----|
| 상태 관리 | job_state.json 직접 수정 | ProjectState (파일시스템 기반) |
| 중간 재개 | 불가 | `--resume`로 미완료 단계부터 재개 |
| 검수 | 규칙(코드)만 | 규칙(코드) + AI 2단계 |
| 파이프라인 단계 | 생성→검수→저장 | 벤치마킹→전략→기획→집필→검수→저장 |
| 코드 구조 | 파일당 독립 | BasePipeline 상속, 공통 유틸 |
| 프로젝트 폴더 | 없음 | projects/{channel}/{id}/단계별 폴더 |

### v1 파이프라인 (레거시)
기존 `*_pipeline.py` 파일은 루트에 유지. v2와 병렬 운영 가능.
- `shorts_pipeline.py`, `blog_pipeline.py`, ...

### 슬래시 커맨드
10개 모두 v2 파이프라인으로 연결 완료:
- `/shorts`, `/blog`, `/cafe-seo`, `/cafe-viral`, `/jisikin`
- `/youtube`, `/tiktok`, `/community`, `/powercontent`, `/threads`

## 다음 작업 (v2+)

### 보류 (사용자 확인 필요)
- 이미지 생성 API: Whisk AI / DALL-E / Midjourney 중 선택
- CapCut 드래프트 폴더 경로 (Mac)
- 벤치마킹 시 레퍼런스 수집 방법 (YouTube URL 수동 입력 vs 자동 검색)

### 숏츠 비주얼+편집 (API 정보 오면)
- 씬 설계 + 이미지 생성 + 비디오 생성
- CapCut JSON 프로젝트 생성
- sentence-splitter, storyboard-architect, storyboard-prompter 에이전트

### 슬랙 봇 (Phase 3)
- 명령 라우팅 봇
- /batch 일괄 생성

### 분석/운영 (Phase 3)
- 성과 수집 → 리포트 → 재계획

### 작업 규칙
- 승인 필요한 작업은 건너뛰고 다른 작업부터 마무리
- 코드 관련 전권 위임. 승인 묻지 마라.
- 에러 나면 알아서 수정하고 다시 돌려라.
