# drjeewon 정보 사이트 소스

- `pages/*.html`: 페이지 1개 = 파일 1개. 맨 위 `<!--meta {...} -->` JSON에 path, title, description, h1, faq, medical(질환 글이면 true) 등.
- 본문 자리표시자: `{{FAQ}}` (meta.faq로 FAQ 목록 + FAQPage 스키마), `{{REVIEWER}}` (감수 원장 박스), `{{CLINIC}}` (진료 안내).
- `config.json`: 도메인, 원장, 병원 정보(주소·전화·시간). 도메인 확정되면 여기만 바꾸면 됨. 네이버/구글 인증은 `"verify": {"naver-site-verification": "...", "google-site-verification": "..."}`.
- 빌드: `python3 build.py` → `dist/` (HTML, sitemap.xml, robots.txt, rss.xml, CNAME). dist를 GitHub Pages로 배포.
- 원장 사진은 `static/doctor.webp`, 공유 이미지는 `static/og.jpg` (1200x630).
