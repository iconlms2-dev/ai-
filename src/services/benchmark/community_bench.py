"""커뮤니티 인기글 벤치마킹 — SeleniumBase UC 모드로 크롤링.

지원 커뮤니티: 뽐뿌, 클리앙, 디시인사이드, 에펨코리아, 루리웹 등
인기글(댓글 N개 이상) 수집 → 제목/본문 앞부분/댓글수 추출 → 톤 분석용
"""
import re
import time
import logging
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# 커뮤니티별 인기글 URL 패턴
COMMUNITY_URLS = {
    "뽐뿌": "https://www.ppomppu.co.kr/zboard/zboard.php?id=freeboard&page=1&divpage=1&ss=nc&category=&search_type=sub_memo&no=&sel_date=&desc=asc&keyword=",
    "클리앙": "https://www.clien.net/service/board/park?&od=T31&po=0",
    "디시인사이드": "https://gall.dcinside.com/board/lists/?id=hit&page=1",
    "에펨코리아": "https://www.fmkorea.com/index.php?mid=best&listStyle=webzine",
    "루리웹": "https://bbs.ruliweb.com/best/humor/now?page=1",
}

# 최소 댓글 수 필터 (커뮤니티별)
MIN_COMMENTS = {
    "뽐뿌": 10,
    "클리앙": 15,
    "디시인사이드": 30,
    "에펨코리아": 20,
    "루리웹": 15,
}


def _parse_ppomppu(soup) -> list[dict]:
    """뽐뿌 자유게시판 파싱."""
    posts = []
    rows = soup.select("tr.baseList-mainList, tr.list0, tr.list1")
    for row in rows:
        title_el = row.select_one("a.baseList-title, td.baseList-space a font")
        if not title_el:
            continue
        comment_el = row.select_one("span.baseList-c, span.cmt")
        comment_count = 0
        if comment_el:
            m = re.search(r'\d+', comment_el.text)
            if m:
                comment_count = int(m.group())
        link_el = row.select_one("a[href*='no=']")
        posts.append({
            "title": title_el.text.strip(),
            "comments": comment_count,
            "url": "https://www.ppomppu.co.kr/zboard/" + link_el["href"] if link_el else "",
        })
    return posts


def _parse_clien(soup) -> list[dict]:
    """클리앙 모두의공원 파싱."""
    posts = []
    items = soup.select("div.list_item")
    for item in items:
        title_el = item.select_one("span.subject_fixed")
        if not title_el:
            continue
        comment_el = item.select_one("span.rSymph05")
        comment_count = 0
        if comment_el:
            m = re.search(r'\d+', comment_el.text)
            if m:
                comment_count = int(m.group())
        link_el = item.select_one("a.list_subject")
        url = ""
        if link_el and link_el.get("href"):
            url = "https://www.clien.net" + link_el["href"]
        posts.append({
            "title": title_el.text.strip(),
            "comments": comment_count,
            "url": url,
        })
    return posts


def _parse_dcinside(soup) -> list[dict]:
    """디시인사이드 힛갤 파싱."""
    posts = []
    rows = soup.select("tr.ub-content")
    for row in rows:
        title_el = row.select_one("td.gall_tit a")
        if not title_el:
            continue
        comment_el = row.select_one("td.gall_tit a.reply_numbox span")
        comment_count = 0
        if comment_el:
            m = re.search(r'\d+', comment_el.text)
            if m:
                comment_count = int(m.group())
        url = ""
        if title_el.get("href"):
            href = title_el["href"]
            if not href.startswith("http"):
                url = "https://gall.dcinside.com" + href
            else:
                url = href
        posts.append({
            "title": title_el.text.strip(),
            "comments": comment_count,
            "url": url,
        })
    return posts


def _parse_fmkorea(soup) -> list[dict]:
    """에펨코리아 베스트 파싱."""
    posts = []
    items = soup.select("li.li")
    for item in items:
        title_el = item.select_one("h3.title a")
        if not title_el:
            continue
        comment_el = item.select_one("span.comment_count")
        comment_count = 0
        if comment_el:
            m = re.search(r'\d+', comment_el.text)
            if m:
                comment_count = int(m.group())
        url = ""
        if title_el.get("href"):
            href = title_el["href"]
            if not href.startswith("http"):
                url = "https://www.fmkorea.com" + href
            else:
                url = href
        posts.append({
            "title": title_el.text.strip(),
            "comments": comment_count,
            "url": url,
        })
    return posts


def _parse_ruliweb(soup) -> list[dict]:
    """루리웹 유머 베스트 파싱."""
    posts = []
    rows = soup.select("tr.table_body")
    for row in rows:
        title_el = row.select_one("a.deco")
        if not title_el:
            continue
        comment_el = row.select_one("a.num_reply span.num")
        comment_count = 0
        if comment_el:
            m = re.search(r'\d+', comment_el.text)
            if m:
                comment_count = int(m.group())
        url = ""
        if title_el.get("href"):
            url = title_el["href"]
        posts.append({
            "title": title_el.text.strip(),
            "comments": comment_count,
            "url": url,
        })
    return posts


PARSERS = {
    "뽐뿌": _parse_ppomppu,
    "클리앙": _parse_clien,
    "디시인사이드": _parse_dcinside,
    "에펨코리아": _parse_fmkorea,
    "루리웹": _parse_ruliweb,
}


def _crawl_post_body(driver, url: str, max_chars: int = 300) -> str:
    """개별 게시글 본문 앞부분 크롤링."""
    try:
        driver.get(url)
        time.sleep(1.5)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        # 커뮤니티별 본문 셀렉터
        for sel in [
            "div.se-main-container",  # 뽐뿌
            "div.post_article",       # 클리앙
            "div.write_div",          # 디시인사이드
            "article div.xe_content", # 에펨코리아
            "div.view_content",       # 루리웹
            "div.content_view",       # 기타
        ]:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator="\n", strip=True)
                return text[:max_chars]
        # fallback: body 전체에서 텍스트 추출
        body = soup.select_one("body")
        if body:
            return body.get_text(separator="\n", strip=True)[:max_chars]
    except Exception as e:
        logger.warning("게시글 본문 크롤링 실패 (%s): %s", url, e)
    return ""


def crawl_community_references(community: str, max_posts: int = 5,
                                keyword: Optional[str] = None) -> list[dict]:
    """커뮤니티 인기글 크롤링 → 벤치마킹 레퍼런스 반환.

    Args:
        community: 커뮤니티 이름 (뽐뿌, 클리앙, 디시인사이드, 에펨코리아, 루리웹)
        max_posts: 최대 수집 게시글 수
        keyword: 키워드 필터 (None이면 필터 없이 인기글만)

    Returns:
        [{"title": ..., "comments": int, "body_preview": str, "url": str}, ...]
    """
    url = COMMUNITY_URLS.get(community)
    parser = PARSERS.get(community)
    min_comments = MIN_COMMENTS.get(community, 10)

    if not url or not parser:
        logger.info("미지원 커뮤니티: %s — 벤치마킹 스킵", community)
        return []

    driver = None
    try:
        from src.services.selenium_pool import create_driver
        driver = create_driver()
        driver.get(url)
        time.sleep(2)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        all_posts = parser(soup)

        # 댓글 수 필터
        hot_posts = [p for p in all_posts if p["comments"] >= min_comments]
        # 키워드 필터 (있으면)
        if keyword:
            kw_filtered = [p for p in hot_posts if keyword in p["title"]]
            if kw_filtered:
                hot_posts = kw_filtered

        # 댓글 많은 순 정렬 → 상위 N개
        hot_posts.sort(key=lambda x: x["comments"], reverse=True)
        hot_posts = hot_posts[:max_posts]

        # 본문 앞부분 크롤링
        for post in hot_posts:
            if post.get("url"):
                post["body_preview"] = _crawl_post_body(driver, post["url"])
            else:
                post["body_preview"] = ""

        return hot_posts

    except Exception as e:
        logger.error("커뮤니티 벤치마킹 실패 (%s): %s", community, e)
        return []
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
