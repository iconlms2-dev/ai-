from bs4 import BeautifulSoup

with open("xhs_source.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

divs = soup.find_all("div")
has_login = False
for d in divs:
    text = d.get_text()
    if "登录" in text or "验证码" in text or "滑动" in text:
        has_login = True
        break

print(f"Requires Login/Captcha: {has_login}")
print(f"Title: {soup.title.string if soup.title else 'No Title'}")

