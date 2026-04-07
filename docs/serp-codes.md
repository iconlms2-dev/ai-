# 네이버 SERP 섹션 코드 매핑

## 코드 → 영역 이름
| 코드 | 영역 |
|------|------|
| pwl_nop | 파워링크 |
| shp_gui | 쇼핑(가격비교) |
| shp_dui | 네이버가격비교 |
| shs_lis | 네이버플러스스토어 |
| urB_coR | 신뢰도통합 |
| urB_imM | 이미지 |
| urB_boR | VIEW/블로그 |
| ugB_adR | 브랜드콘텐츠 |
| ugB_pkR | 브랜드콘텐츠 |
| ugB_bsR | 인기글 |
| ugB_b1R~b3R | 신뢰도통합 |
| ugB_ipR | 인플루언서 |
| heL_htX | AI브리핑 |
| heB_ceR | 관련경험카페글 |
| nws_all | 뉴스 |
| web_gen | 웹사이트 |
| kwX_ndT | 함께많이찾는 |
| exB_soT | 함께보면좋은 |
| kwL_ssT | 연관검색어 |
| ldc_btm | 지식백과 |
| nmb_hpl | 플레이스 |
| brd_brd | 브랜드서치 |
| rrB_hdR/bdR | 리랭킹 |

## 크롤링 참고
- 뷰탭 순서: `nx_cr_area_info` 변수를 정규식으로 추출 (DOM 파싱 불필요)
- 상위글 날짜: `sds-comps-profile-info-subtext` 클래스 사용
- "~일 전", "~주 전", "~개월 전" 상대 날짜 변환 필요
