# 안티그래비티 — 마케팅 자동화 대시보드

네이버 SEO + SNS 마케팅 콘텐츠를 AI로 자동 생성하고, 계정/스케줄/성과까지 한 곳에서 관리하는 올인원 대시보드.

## 주요 기능

- **키워드 분석** — 네이버 검색량 + 경쟁강도 + SERP 분석 + 구매여정 자동 분류
- **콘텐츠 자동 생성** — 블로그, 카페SEO, 지식인, 커뮤니티, 틱톡, 유튜브 댓글, 파워컨텐츠
- **쓰레드(Threads) 자동화** — 페르소나 기반 일상글/물길글 생성 + 공식 API 자동 게시
- **일괄 생성** — 키워드 선택 → 배정 채널별 자동 분기 → 순차 생성 + Notion 자동 저장
- **계정/IP 관리** — 네이버 블로그/카페/지식인 계정별 프록시, 안전규칙, 작업 이력 추적
- **스케줄러** — 매일 생성/검수/배포 알림 + 주간 자동 실행 (키워드 분석, 성과 수집, 리포트)
- **성과 수집** — 네이버 노출 순위 추적 + 블로그 조회수/댓글 + 주간 리포트

## 빠른 시작

### 설치

```bash
cd ~/Desktop/안티그래비티
pip3 install -r requirements.txt
playwright install chromium
```

### 환경 변수 설정

`.env` 파일에 API 키 입력:

```
NAVER_AD_API_KEY=     # 네이버 검색광고 API
NAVER_AD_SECRET=
NAVER_AD_CUSTOMER=
NOTION_TOKEN=         # 노션 통합 토큰
KEYWORD_DB_ID=        # 노션 키워드 DB ID
CONTENT_DB_ID=        # 노션 콘텐츠 DB ID
ANTHROPIC_API_KEY=    # Claude API 키
GEMINI_API_KEY=       # Gemini API 키
THREADS_APP_ID=       # Meta Threads 앱 ID
THREADS_APP_SECRET=   # Meta Threads 앱 시크릿
```

전체 환경변수 목록: [docs/api-config.md](docs/api-config.md)

### 실행

```bash
python3 server.py
```

브라우저에서 http://localhost:8000 접속.

## 프로젝트 구조

```
server.py              # FastAPI 백엔드 (port 8000, ~7100줄)
dashboard.html         # 싱글페이지 대시보드 (~6600줄)
사용안내서.html          # 사용자 매뉴얼 (/사용안내서.html 서빙)
.env                   # API 키 (절대 커밋 금지)

docs/
  api-config.md        # 환경변수 설정 가이드
  serp-codes.md        # 네이버 SERP 섹션 코드 매핑
  prompts.md           # 채널별 프롬프트 경로
  실무적용_가이드.md     # 실무 적용 단계별 가이드

src/
  youtube_bot.py       # 유튜브 댓글 자동화 (Playwright)
  fingerprint.py       # 브라우저 핑거프린트 관리
  safety_rules.py      # 계정별 안전 규칙
  smm_client.py        # SMM 패널 연동
  comment_tracker.py   # 댓글 추적

관련 파일/              # 프롬프트 원본 및 참조 자료

*.json (자동 생성)
  threads_accounts.json   # 쓰레드 계정/페르소나/토큰
  threads_queue.json      # 쓰레드 게시 큐
  naver_accounts.json     # 네이버 계정 관리
  weekly_schedule.json    # 스케줄러 설정
  cafe24_token.json       # 카페24 OAuth 토큰
```

## 대시보드 메뉴 구조

| 대분류 | 하위 메뉴 |
|--------|-----------|
| 분석 | 키워드분석, 키워드현황 |
| 콘텐츠생산 | 블로그원고, 카페SEO, 카페바이럴, 지식인, 유튜브댓글, 틱톡스크립트, 숏츠제작, 커뮤니티침투, 파워컨텐츠, 쓰레드 |
| 이미지 | 사진라이브러리 |
| 광고 | 광고소재자동화 |
| 운영 | 일괄생성, 계정관리, 스케줄러, 배포일정, 성과수집, 주간리포트, UTM관리 |
| 도움말 | 사용안내서 |

## 기술 스택

- **백엔드**: Python 3.11+, FastAPI, Uvicorn
- **프론트엔드**: Vanilla HTML / CSS / JS (프레임워크 없음)
- **AI**: Claude API (Anthropic), Gemini API (Google)
- **데이터**: Notion API (키워드/콘텐츠 DB)
- **크롤링**: Selenium, Playwright (+Stealth)
- **외부 API**: 네이버 검색광고 API, Threads Graph API, Cafe24 API, ElevenLabs TTS

## 문서

- [API 환경변수 설정](docs/api-config.md)
- [SERP 섹션 코드](docs/serp-codes.md)
- [채널별 프롬프트](docs/prompts.md)
- [실무 적용 가이드](docs/실무적용_가이드.md)

## 주의사항

- `.env` 파일은 **절대 커밋하지 마세요** (API 키 포함)
- 코드 변경 시 `사용안내서.html`도 반드시 동기화
- 네이버 계정 안전: 블로그 하루 1~2개, 카페 1~2개, 지식인 3~5개
- Threads: 일상글 70% + 물길글 30% 비율 유지
