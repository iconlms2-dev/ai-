from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import quote
import time

opts = Options()
opts.add_argument('--headless=new')
opts.add_argument('--no-sandbox')
opts.add_argument('--disable-dev-shm-usage')
opts.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
svc = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=svc, options=opts)

query_zh = "饮食"
url = f"https://www.xiaohongshu.com/search_result/?keyword={quote(query_zh)}&type=54"
print(f"Fetching: {url}")
driver.get(url)
time.sleep(5)

html = driver.page_source
with open("xhs_source.html", "w", encoding="utf-8") as f:
    f.write(html)

imgs = driver.find_elements(By.CSS_SELECTOR, "img")
print(f"Total img tags: {len(imgs)}")
for img in imgs[:10]:
    print(img.get_attribute("src")[:100], img.get_attribute("class"))

driver.quit()
