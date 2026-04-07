# API 설정 참조

모든 키는 `.env` 파일에 저장. 절대 코드에 하드코딩하지 말 것.

## 네이버 검색광고 API
| 환경변수 | 용도 |
|----------|------|
| NAVER_AD_API_KEY | 네이버 검색광고 API 인증 키 |
| NAVER_AD_SECRET | HMAC 서명용 시크릿 키 |
| NAVER_AD_CUSTOMER | 광고주 계정 ID |

키워드 확장(연관 키워드) + 검색량 조회에 사용.

## 노션 API
| 환경변수 | 용도 |
|----------|------|
| NOTION_TOKEN | 노션 내부 통합 토큰 |
| KEYWORD_DB_ID | 키워드 맵 DB ID |
| CONTENT_DB_ID | 콘텐츠 DB ID |

키워드 저장, 콘텐츠 저장, 상태 조회 등 전체 노션 연동에 사용.

## AI API
| 환경변수 | 용도 |
|----------|------|
| ANTHROPIC_API_KEY | Claude API (블로그/카페/지식인 등 콘텐츠 생성) |
| GEMINI_API_KEY | Gemini API (구매여정 판별, 틱톡 스크립트 등) |

## SMM 패널 (좋아요 자동 구매)
| 환경변수 | 용도 | 기본값 |
|----------|------|--------|
| SMM_API_KEY | SMM 패널 API 키 | (필수) |
| SMM_API_URL | SMM 패널 API URL | https://smmwiz.com/api/v2 |
| SMM_ENABLED | SMM 기능 활성화 여부 | false |
| SMM_LIKE_SERVICE_ID | 유튜브 댓글 좋아요 서비스 ID | 4001 |
| SMM_LIKE_QUANTITY | 기본 좋아요 주문 수량 | 20 |

유튜브 댓글 자동 게시 후 좋아요 구매에 사용. smmwiz.com 대시보드에서 서비스 ID 확인 가능.

## Threads (Meta) API
| 환경변수 | 용도 |
|----------|------|
| THREADS_APP_ID | Meta Developer 앱 ID |
| THREADS_APP_SECRET | Meta Developer 앱 시크릿 |

계정별 액세스 토큰은 OAuth 연동 후 `threads_accounts.json`에 자동 저장.
장기 토큰은 60일 유효, 만료 7일 전 대시보드에서 경고 표시.

## 프록시 설정
계정별 프록시는 대시보드에서 계정 추가 시 설정.
형식: `http://user:pass@host:port` 또는 `socks5://user:pass@host:port`
