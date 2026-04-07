from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time

opts = Options()
# Removed headless for testing visibility, although server runs headless
opts.add_argument('--headless=new')
opts.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
opts.add_argument('--disable-blink-features=AutomationControlled')
opts.add_experimental_option("excludeSwitches", ["enable-automation"])
opts.add_experimental_option('useAutomationExtension', False)

svc = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=svc, options=opts)
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
    "source": """
    Object.defineProperty(navigator, 'webdriver', {
      get: () => undefined
    })
    """
})

url = "https://www.xiaohongshu.com/search_result/?keyword=饮食&type=54"
print("Navigating...")
driver.get(url)
time.sleep(6)

html = driver.page_source
with open("xhs_source3.html", "w", encoding="utf-8") as f:
    f.write(html)

driver.quit()

from bs4 import BeautifulSoup
with open("xhs_source3.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

divs = soup.find_all("div")
has_login = False
for d in divs:
    text = d.get_text()
    if "登录" in text or "验证码" in text or "滑动" in text:
        has_login = True
        break

print(f"Still blocked: {has_login}")

