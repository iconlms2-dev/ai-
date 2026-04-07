# 마케팅 자동화 프로젝트 설정

## 노션 API
- 토큰: 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
- 키워드 DB ID: 32d3736e-0468-8112-8323-d8b190bd8f16
- 콘텐츠 DB ID: 32d3736e-0468-81d6-a389-ee0789c3eff4

## 네이버 검색광고 API
- API_KEY: 010000000071408e816744b813c6c93b3567503c77012106fce658a3d95df50acf9208836c
- SECRET_KEY: AQAAAABxQI6BZ0S4E8bJOzVnUDx3aFeHyybkFA0iAlTJhnULsA==
- CUSTOMER_ID: 2558029

## 네이버 섹션 코드 매핑 (검증완료)
pwl_nop=파워링크, shp_gui=쇼핑(가격비교), shp_dui=네이버가격비교, shs_lis=네이버플러스스토어,
urB_coR=신뢰도통합, urB_imM=이미지, urB_boR=VIEW/블로그,
ugB_adR=브랜드콘텐츠, ugB_pkR=브랜드콘텐츠, ugB_bsR=인기글,
ugB_b1R=신뢰도통합, ugB_b2R=신뢰도통합, ugB_b3R=신뢰도통합,
ugB_ipR=인플루언서, ugB_qpR=기타,
heL_htX=AI브리핑, heB_ceR=관련경험카페글, nws_all=뉴스, web_gen=웹사이트,
kwX_ndT=함께많이찾는, exB_soT=함께보면좋은, kwL_ssT=연관검색어,
ldc_btm=지식백과, bok_lst=도서, nmb_hpl=플레이스, sit_4po=웹사이트내검색,
brd_brd=브랜드서치, abL_baX=AI브리핑, abL_rtX=AI브리핑,
rrB_hdR=리랭킹, rrB_bdR=리랭킹, nco_x58=기타, ink_mik=기타, nmb_rnk=기타, ink_kid=기타

## 뷰탭 순서 파싱 방법
nx_cr_area_info 변수를 정규식으로 추출. DOM 파싱 불필요.

## 상위글 날짜 크롤링
sds-comps-profile-info-subtext 클래스가 안정적. upload_time, date 클래스도 체크.
"~일 전", "~주 전", "~개월 전" 상대 날짜 변환 필요.

## 경쟁강도 기준
상위 3개 글 평균 경과일: ≤90일=상, 91~180일=중, 181일+=하

## 프로젝트 구조
대시보드: dashboard.html (localhost:8000)
백엔드: server.py (FastAPI)
사이드바 메뉴: 키워드분석 / 블로그원고 / 카페SEO / 카페바이럴 / 지식인 / 유튜브댓글 / 틱톡스크립트 / 커뮤니티침투 / 사진라이브러리 / 광고레퍼런스수집 / 광고기획+이미지 / 성과수집
