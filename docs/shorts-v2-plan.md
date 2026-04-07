# 숏츠 파이프라인 v2 — 참고 프로젝트(autoworker-youtube) 수준으로 고도화

## 참고 프로젝트 구조

### 스킬 (오케스트레이터)
```
.claude/skills/
  youtube-pd/          ← 전체 파이프라인 오케스트레이터 (스킬)
  comment/
  grok-sso/
  new-channel/
  upload/
  whisk-cookies/
```

### 에이전트 (전문 작업자)
```
.claude/agents/
  data-researcher.md        # 레퍼런스 수집
  pattern-extractor.md      # 패턴 분석
  script-reviewer.md        # 대본 검수
  script-writer.md          # 대본 작성
  sentence-splitter.md      # 자막 타이밍용 문장 분할
  storyboard-architect.md   # 씬 설계 (스토리보드)
  storyboard-prompter.md    # 이미지 프롬프트 생성
  strategist.md             # 전략/컨셉 수립
  tts-converter.md          # TTS 변환
  video-analyst.md          # 영상 분석
  youtube-uploader.md       # 유튜브 업로드
```

### 파이프라인 6단계 (14 세부 단계)

```
1. 벤치마킹 (레퍼런스 수집 + 분석)
   ├─ YouTube URL 수집
   ├─ AI 분석 ×N (대본, 썸네일, 제목, 댓글 수집)
   ├─ 패턴 추출 (성공 요인 분석)
   └─ 팩트 체크 (허위정보 검증)

2. 전략 (컨셉 + 제목 + 훅)
   ├─ 컨셉 3세트 생성 → 자동 선택 또는 HITL
   ├─ CTR 설계 (클릭률 최적화)
   └─ 훅 & 인트로 설계

3. 대본 (기획 → 집필 → 검수)
   ├─ 기획서 작성
   ├─ AI 집필 (기획서 기반)
   └─ 검수 & 리비전 (script-reviewer)

4. 음성 (TTS + 자막)
   ├─ ElevenLabs TTS 생성
   └─ 자막 + 무음 압축 (sentence-splitter 활용)

5. 비주얼 (스토리보드 → 이미지 → 영상)
   ├─ 씬 설계 (storyboard-architect: 대본+기획서 기반 6~7초 단위)
   ├─ 이미지 생성 (storyboard-prompter → Whisk AI / DALL-E)
   └─ 비디오 생성 (훅/인트로 부분만, Grok / Runway)

6. 편집 + 업로드 (CapCut → YouTube)
   ├─ CapCut 프로젝트 JSON 생성 (이미지+음성+자막+타이밍 전부 명시)
   ├─ YouTube 메타데이터 생성 (제목, 설명, 태그)
   ├─ 썸네일 5장 생성
   └─ (수동) 렌더링 → 업로드 (또는 YouTube API 자동)
```

### 핵심 아키텍처 특징

1. **상태 머신 = 파일시스템**
   - 14단계 중 현재 위치를 파일 존재 여부로 감지
   - 중간에 멈춰도 "이어서 해줘" 한마디로 자동 재개
   - DB 없이 파일시스템이 곧 상태

2. **멀티 에이전트 분업**
   - PD(스킬)가 지휘, 전문 에이전트가 실행
   - strategist는 컨셉, writer는 대본, reviewer는 검수
   - 독립 작업은 병렬로 동시 진행

3. **auto / ask 모드**
   - 완전 자동 또는 핵심 3곳만 사용자 개입
   - workflow.json으로 모드 설정

4. **CapCut JSON 편집**
   - 모든 편집 정보를 JSON으로 명시
   - 이미지, 음성, 자막, 타이밍, 전환효과, 확대 등
   - CapCut 드래프트 폴더에 넣으면 프로젝트 자동 생성
   - 사용자는 Export만 누르면 됨

### 시스템 규모
- 14 파이프라인 단계
- 6+ 전문 에이전트
- 46 Python 스크립트
- ~$5 영상 1개 API 비용
- 1 수동 단계 (렌더링)

---

## 우리 숏츠 v1 vs 목표 v2

| 항목 | v1 (현재) | v2 (목표) |
|------|----------|----------|
| 벤치마킹 | ❌ 없음 | ✅ YouTube 레퍼런스 수집+분석+패턴+팩트 |
| 전략 | ✅ 주제 5개 생성 | ✅ 컨셉 3세트 + CTR + 훅/인트로 |
| 대본 | ✅ 대본 생성+검수 | ✅ 기획서→집필→검수 (분리) |
| TTS | ✅ ElevenLabs | ✅ + 무음 압축 + 정밀 자막 |
| 비주얼 | ❌ 없음 | ✅ 씬 설계 + 이미지 + 비디오 |
| 편집 | ❌ 없음 | ✅ CapCut JSON 자동 생성 |
| 업로드 | ❌ 없음 | ✅ YouTube 메타 + 썸네일 |
| 상태 관리 | JSON | 파일시스템 기반 상태 머신 |
| 에이전트 | 3개 | 11개 |

---

## 구현 계획

### 필요한 외부 API/서비스
- ElevenLabs TTS (이미 있음)
- 이미지 생성: Whisk AI / DALL-E / Midjourney
- 비디오 생성: Grok / Runway / Kling AI
- YouTube Data API (업로드용)
- CapCut 로컬 (드래프트 폴더 경로 필요)

### 추가해야 할 에이전트
- sentence-splitter.md (자막 타이밍 분할)
- storyboard-architect.md (씬 설계)
- storyboard-prompter.md (이미지 프롬프트)

### 추가해야 할 스킬
- .claude/commands/shorts.md 업데이트 (14단계 전체)

### 추가해야 할 Python 스크립트
- 벤치마킹 (YouTube 대본/댓글/제목 수집)
- 패턴 추출
- 팩트 체크
- 기획서 생성
- 씬 설계
- 이미지 프롬프트 생성 → 이미지 생성 API 호출
- 비디오 생성 API 호출
- CapCut JSON 생성
- YouTube 메타데이터 생성
- 썸네일 생성
- YouTube 업로드

### 상태 관리 변경
- job_state.json → 파일시스템 기반 상태 머신
- 각 프로젝트 = 폴더
- 각 단계 완료 = 해당 파일 존재
- "이어서 해줘" → 폴더 스캔 → 미완료 단계부터 재개

### 프로젝트 폴더 구조 (1개 영상)
```
shorts_projects/
  {project_id}/
    00_input/
      material.json          # 소재 정보
    01_benchmark/
      references.json        # 수집된 레퍼런스
      patterns.json          # 추출된 패턴
      facts.json             # 팩트 체크 결과
    02_strategy/
      concepts.json          # 컨셉 3세트
      selected.json          # 선택된 컨셉
      hooks.json             # 훅/인트로
    03_script/
      brief.md               # 기획서
      draft.md               # 초안
      final.md               # 최종 대본
      review.json            # 검수 결과
    04_audio/
      voice.mp3              # TTS 음성
      subtitles.srt          # 자막
      subtitles.json         # 정밀 타이밍 자막
    05_visual/
      storyboard.json        # 씬 설계
      prompts.json           # 이미지 프롬프트
      images/                # 생성된 이미지
        scene_01.png
        scene_02.png
        ...
      videos/                # 생성된 비디오 (훅/인트로)
        intro.mp4
    06_edit/
      capcut_project/        # CapCut 프로젝트 폴더
        draft_content.json   # 편집 JSON
        ...
      youtube_meta.json      # 제목, 설명, 태그
      thumbnails/            # 썸네일 5장
    status.json              # 전체 상태 추적
```

---

## 다음 세션 지시사항

1. 이 파일(docs/shorts-v2-plan.md)을 읽어라
2. 숏츠 파이프라인을 참고 프로젝트 수준으로 고도화해라
3. 기존 shorts_pipeline.py는 백업 후 교체
4. 단계별로 구현 + 테스트
5. 이미지/비디오 생성 API는 사용자에게 어떤 서비스 쓸지 확인 필요
6. CapCut 드래프트 폴더 경로 확인 필요
