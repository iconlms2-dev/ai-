# 채널별 프롬프트 파일 경로

각 콘텐츠 생성 모듈이 사용하는 프롬프트 파일 위치.

| 채널 | 프롬프트 파일 |
|------|-------------|
| 블로그원고 | 관련 파일/블로그원고_프롬프트.md |
| 카페SEO | 관련 파일/카페SEO_프롬프트.md |
| 카페바이럴 | 관련 파일/카페바이럴_프롬프트.md |
| 유튜브댓글 | 관련 파일/유튜브댓글_프롬프트.md |
| 사진라이브러리 | 관련 파일/사진라이브러리_프롬프트.md |

| 쓰레드 일상글 | server.py 내 _build_threads_daily_prompt() |
| 쓰레드 물길글 | server.py 내 _build_threads_traffic_prompt() |
| 쓰레드 댓글 | server.py 내 _build_threads_comment_prompt() |

프롬프트 수정 시 해당 파일을 직접 편집하면 됨.
