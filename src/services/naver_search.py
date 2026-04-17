"""네이버 검색 관련 서비스 — 자동완성, SERP 분석, 검색량, 상위글 분석"""
import re
import json
import time
import hmac
import hashlib
import base64
from datetime import datetime, timedelta
from urllib.parse import quote, quote_plus

import requests as req
from bs4 import BeautifulSoup

from src.services.config import (
    NAVER_AD_API_KEY, NAVER_AD_SECRET, NAVER_AD_CUSTOMER,
    SECTION_MAP, CONTENT_CODES,
)
from src.services.common import valid_kw


def autocomplete(keyword):
    url = f"https://ac.search.naver.com/nx/ac?q={quote(keyword)}&con=1&frm=nv&ans=2&t_koreng=1&q_enc=UTF-8&st=100&r_format=json&r_enc=UTF-8&r_unicode=0&type=1"
    try:
        r = req.get(url, timeout=5)
        data = r.json()
        items = data.get('items', [[]])
        results = []
        for group in items:
            for item in group:
                if isinstance(item, list) and len(item) > 0:
                    results.append(item[0])
                elif isinstance(item, str):
                    results.append(item)
        return results
    except Exception:
        return []


def expand_selenium(driver, keyword):
    """네이버 검색 페이지에서 연관검색어/함께많이찾는/함께보면좋은 영역만 정확히 파싱"""
    kws = {}
    try:
        url = f"https://search.naver.com/search.naver?query={quote(keyword)}&where=nexearch"
        driver.get(url)
        time.sleep(2.5)
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        for section in soup.select('.api_subject_bx'):
            title_el = section.select_one('h2, .api_title, .tit')
            if not title_el:
                continue
            title_text = title_el.get_text(strip=True)

            source = None
            if '연관검색어' in title_text:
                source = '연관검색어'
            elif '함께 많이 찾는' in title_text or '함께많이찾는' in title_text:
                source = '함께많이찾는'
            elif '함께 보면 좋은' in title_text or '함께보면좋은' in title_text:
                source = '함께보면좋은'

            if source:
                for a in section.find_all('a'):
                    span = a.select_one('span')
                    t = span.get_text(strip=True) if span else a.get_text(strip=True)
                    if valid_kw(t) and t not in kws:
                        kws[t] = source

        if not kws:
            for a in soup.find_all('a', href=True):
                href = a.get('href', '')
                source = None
                if 'sm=tab_rel' in href:
                    source = '연관검색어'
                elif 'sm=tab_clk.ndT' in href:
                    source = '함께많이찾는'
                elif 'sm=tab_clk.ssT' in href:
                    source = '함께보면좋은'

                if source:
                    span = a.select_one('span')
                    t = span.get_text(strip=True) if span else a.get_text(strip=True)
                    if valid_kw(t) and t not in kws:
                        kws[t] = source

    except Exception as e:
        print(f"Selenium error for '{keyword}': {e}")
    return kws


def ad_signature(timestamp):
    msg = f"{timestamp}.GET./keywordstool"
    sig = hmac.new(NAVER_AD_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    return base64.b64encode(sig).decode()


def search_volume(keywords_list):
    """여러 키워드를 배치로 조회. dict 반환 {keyword: {pc, mo}}"""
    result = {}
    batch_size = 5
    for i in range(0, len(keywords_list), batch_size):
        batch = keywords_list[i:i+batch_size]
        hint = ','.join(kw.replace(' ','') for kw in batch)
        ts = str(int(time.time() * 1000))
        headers = {
            'Content-Type': 'application/json',
            'X-Timestamp': ts,
            'X-API-KEY': NAVER_AD_API_KEY,
            'X-Customer': NAVER_AD_CUSTOMER,
            'X-Signature': ad_signature(ts),
        }
        try:
            r = req.get(f"https://api.searchad.naver.com/keywordstool?hintKeywords={quote_plus(hint)}&showDetail=1",
                       headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                for item in data.get('keywordList', []):
                    rk = item.get('relKeyword','').replace(' ','').upper()
                    pc = item.get('monthlyPcQcCnt', 0)
                    mo = item.get('monthlyMobileQcCnt', 0)
                    if isinstance(pc, str): pc = 10 if '<' in pc else int(pc.replace(',','') or '0')
                    if isinstance(mo, str): mo = 10 if '<' in mo else int(mo.replace(',','') or '0')
                    for kw in batch:
                        if kw.replace(' ','').upper() == rk:
                            result[kw] = {'pc': pc, 'mo': mo}
                            break
            else:
                print(f"Search Ad API error {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"Search volume error: {e}")
        time.sleep(0.3)

    for kw in keywords_list:
        if kw not in result:
            result[kw] = {'pc': 0, 'mo': 0}
    return result


def _parse_date(text, today):
    if not text: return None
    m = re.search(r'(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})', text)
    if m: return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r'(\d+)일\s*전', text)
    if m: return today - timedelta(days=int(m.group(1)))
    m = re.search(r'(\d+)주\s*전', text)
    if m: return today - timedelta(weeks=int(m.group(1)))
    m = re.search(r'(\d+)개월\s*전', text)
    if m: return today - timedelta(days=int(m.group(1))*30)
    if '어제' in text: return today - timedelta(days=1)
    return None


def analyze_serp(keyword, today):
    """SERP HTML을 requests로 가져와서 분석"""
    ua = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
    result = {'content_tab_rank': '-', 'content_format': '-', 'top6_tabs': '-', 'articles': []}
    try:
        r = req.get(f"https://search.naver.com/search.naver?query={quote(keyword)}&where=nexearch", headers={'User-Agent': ua}, timeout=10)
        html = r.text
        soup = BeautifulSoup(html, 'html.parser')

        m = re.search(r'var\s+nx_cr_area_info\s*=\s*(\[.*?\])\s*;', html, re.DOTALL)
        areas = []
        if m:
            try: areas = json.loads(m.group(1))
            except (json.JSONDecodeError, ValueError): pass

        sorted_areas = sorted(areas, key=lambda x: x.get('r', 999))

        for a in sorted_areas:
            code = a.get('n','')
            if code in CONTENT_CODES:
                result['content_tab_rank'] = a.get('r', '-')
                result['content_format'] = SECTION_MAP.get(code, code)
                break

        top6 = []
        seen = set()
        for a in sorted_areas:
            name = SECTION_MAP.get(a.get('n',''), a.get('n',''))
            if name not in seen:
                seen.add(name)
                top6.append(name)
            if len(top6) >= 6: break
        result['top6_tabs'] = ' > '.join(top6) if top6 else '-'

        articles = []
        seen_urls = set()
        for container in soup.select('.view_wrap, .total_wrap, .api_subject_bx, .sp_tit, .total_tit, [class*="content_area"], [class*="view"]'):
            links = container.find_all('a', href=re.compile(r'blog\.naver|cafe\.naver|kin\.naver|post\.naver|in\.naver'))
            for link in links:
                href = link.get('href','')
                if href in seen_urls: continue
                seen_urls.add(href)
                fmt = '기타'
                if 'blog.naver' in href: fmt = '블로그'
                elif 'cafe.naver' in href: fmt = '카페'
                elif 'kin.naver' in href: fmt = '지식인'
                elif 'post.naver' in href: fmt = '포스트'
                elif 'in.naver' in href: fmt = '인플루언서'

                date_str = ''
                parent = link
                for _ in range(8):
                    parent = parent.parent
                    if not parent: break
                    de = parent.find(class_=re.compile(r'sub_txt|date|time|profile.*sub|info_item|sds-comps-profile-info-subtext|upload_time'))
                    if de:
                        date_str = de.get_text(strip=True)
                        break

                pub = _parse_date(date_str, today)
                days_ago = (today - pub).days if pub else None
                articles.append({
                    'format': fmt,
                    'date': pub.strftime('%Y.%m.%d') if pub else '',
                    'days_ago': days_ago
                })
                if len(articles) >= 5: break
            if len(articles) >= 5: break

        if len(articles) < 3:
            for link in soup.find_all('a', href=re.compile(r'blog\.naver|cafe\.naver|kin\.naver')):
                href = link.get('href','')
                if href in seen_urls: continue
                seen_urls.add(href)
                fmt = '블로그' if 'blog' in href else '카페' if 'cafe' in href else '지식인'
                articles.append({'format': fmt, 'date': '', 'days_ago': None})
                if len(articles) >= 5: break

        result['articles'] = articles

        days_list = [a['days_ago'] for a in articles[:3] if a['days_ago'] is not None]
        if days_list:
            avg_days = sum(days_list) / len(days_list)
            if avg_days < 14: result['competition'] = '상'
            elif avg_days <= 28: result['competition'] = '중'
            else: result['competition'] = '하'
        else:
            result['competition'] = '-'

    except Exception as e:
        print(f"SERP analysis error for '{keyword}': {e}")
        result['competition'] = '-'
    return result


def analyze_blog_article(url, keyword):
    """개별 블로그 글 분석: 사진수, 키워드반복수"""
    try:
        m = re.search(r'blog\.naver\.com/([^/?]+)/(\d+)', url)
        if not m:
            return None
        blog_id, log_no = m.group(1), m.group(2)
        mobile_url = f"https://m.blog.naver.com/{blog_id}/{log_no}"
        headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1'}
        r = req.get(mobile_url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        content = soup.select_one('.se-main-container, .post_ct, #postViewArea')
        if content:
            imgs = content.find_all('img', src=re.compile(r'http'))
            photo_count = len(imgs)
            text = content.get_text()
        else:
            imgs = soup.find_all('img', src=re.compile(r'blogfiles|postfiles|pstatic'))
            photo_count = len(imgs)
            text = soup.get_text()
        keyword_repeat = text.count(keyword)
        return {'photo_count': photo_count, 'keyword_repeat': keyword_repeat}
    except Exception:
        return None


def analyze_top_for_blog(keyword):
    """상위글 분석 → 평균 사진수, 키워드반복수"""
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'}
    try:
        r = req.get(f"https://search.naver.com/search.naver?query={quote(keyword)}&where=nexearch", headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        urls = []
        for a in soup.find_all('a', href=re.compile(r'blog\.naver\.com/[^/]+/\d+')):
            href = a.get('href', '')
            if href not in urls:
                urls.append(href)
            if len(urls) >= 3:
                break
        if not urls:
            return {'photo_count': 8, 'keyword_repeat': 5}
        results = []
        for url in urls[:3]:
            a = analyze_blog_article(url, keyword)
            if a:
                results.append(a)
            time.sleep(0.5)
        if not results:
            return {'photo_count': 8, 'keyword_repeat': 5}
        return {
            'photo_count': max(round(sum(r['photo_count'] for r in results) / len(results)), 3),
            'keyword_repeat': max(round(sum(r['keyword_repeat'] for r in results) / len(results)), 3)
        }
    except Exception:
        return {'photo_count': 8, 'keyword_repeat': 5}


# 카페 분석 함수는 src/api/cafe.py의 _analyze_cafe_article, _analyze_top_for_cafe로 통합됨
# (top_titles 반환 + 광고 필터링 개선 버전)
# 카페 관련 분석이 필요하면 src.api.cafe 모듈을 import하거나 cafe_crawler를 직접 사용할 것
