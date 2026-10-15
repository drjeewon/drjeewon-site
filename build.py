#!/usr/bin/env python3
"""정적 사이트 빌드: pages/*.html (맨 위 JSON 머리말 + 본문) -> dist/

머리말 예시 (파일 첫 줄부터):
<!--meta
{"path": "/acne/", "title": "...", "description": "...", "h1": "...", "faq": [["질문", "답"]]}
-->
본문 HTML ...

본문 안에서 쓸 수 있는 자리표시자: {{FAQ}} {{REVIEWER}} {{CLINIC}} {{DOMAIN}}
"""
import html
import json
import re
import shutil
from datetime import date
from email.utils import format_datetime
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
D = CFG["domain"].rstrip("/")
C = CFG["clinic"]
KST = timezone(timedelta(hours=9))
PREVIEW = CFG.get("preview", False)  # 도메인 연결 전 임시 주소: 검색 수집 막음
BASE = re.sub(r"^https?://[^/]+", "", D)  # 예: /drjeewon-site (하위 경로 배포용)


def with_base(s):
    return re.sub(r'(href|src)="/(?!/)', lambda m: f'{m.group(1)}="{BASE}/', s) if BASE else s


def esc(s):
    return html.escape(s, quote=True)


def read_page(p):
    src = p.read_text(encoding="utf-8")
    m = re.match(r"<!--meta\s*(\{.*?\})\s*-->\s*", src, re.S)
    if not m:
        raise SystemExit(f"{p.name}: 머리말 없음")
    meta = json.loads(m.group(1))
    meta["body"] = src[m.end():]
    meta.setdefault("updated", date.today().isoformat())
    meta.setdefault("published", meta["updated"])
    return meta


def inline_md(t):
    t = esc(t)
    t = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", r'<img src="\2" alt="\1" loading="lazy">', t)
    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return t


def md_to_html(src):
    """칼럼용 아주 단순한 마크다운: ## ### 문단, - 목록, 1. 목록, > 인용, **굵게**, [링크](주소), ![사진](주소)"""
    out, para, lst = [], [], None

    def flush():
        nonlocal para, lst
        if para:
            out.append("<p>" + "<br>".join(inline_md(x) for x in para) + "</p>")
            para = []
        if lst:
            tag, items = lst
            out.append(f"<{tag}>" + "".join(f"<li>{inline_md(i)}</li>" for i in items) + f"</{tag}>")
            lst = None

    for line in src.splitlines():
        t = line.strip()
        if not t:
            flush()
            continue
        m = re.match(r"(#{2,3})\s+(.*)", t)
        if m:
            flush()
            n = len(m.group(1))
            out.append(f"<h{n}>{inline_md(m.group(2))}</h{n}>")
            continue
        m = re.match(r"(?:[-*]|(\d+)\.)\s+(.*)", t)
        if m:
            if para:
                flush()
            tag = "ol" if m.group(1) else "ul"
            if not lst or lst[0] != tag:
                flush()
                lst = (tag, [])
            lst[1].append(m.group(2))
            continue
        if t.startswith(">"):
            flush()
            out.append(f'<p class="answer">{inline_md(t.lstrip("> "))}</p>')
            continue
        if lst:
            flush()
        para.append(t)
    flush()
    return "\n".join(out)


def read_column(p):
    """columns/*.md: 맨 위 --- 사이에 '키: 값' 줄 (제목, 설명, 주소, 날짜), 아래 본문.
    본문에서 'Q. 질문' 다음 줄 'A. 답'은 자주 묻는 질문으로 모아 FAQ 스키마에 들어감."""
    src = p.read_text(encoding="utf-8")
    m = re.match(r"---\s*\n(.*?)\n---\s*\n", src, re.S)
    if not m:
        raise SystemExit(f"{p.name}: 맨 위 --- 머리말 없음")
    head = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            head[k.strip()] = v.strip()
    body = src[m.end():]
    faq, rest, lines, i = [], [], body.splitlines(), 0
    while i < len(lines):
        q = re.match(r"\s*Q\d*[.:]\s*(.+)", lines[i])
        a = re.match(r"\s*A\d*[.:]\s*(.+)", lines[i + 1]) if q and i + 1 < len(lines) else None
        if q and a:
            faq.append([q.group(1).strip(), a.group(1).strip()])
            i += 2
            continue
        rest.append(lines[i])
        i += 1
    if faq:  # FAQ 섹션 제목은 {{FAQ}}가 넣으므로 본문의 같은 제목은 뺌
        rest = [x for x in rest if not re.match(r"\s*#{2,3}\s*자주\s*묻는\s*질문", x)]
    get = lambda *ks: next((head[k] for k in ks if head.get(k)), "")
    title = get("제목", "title")
    slug = get("주소", "slug") or p.stem
    when = get("날짜", "date") or date.today().isoformat()
    meta = {
        "path": f"/column/{slug}/",
        "medical": True,
        "column": True,
        "title": f"{title} | {CFG['doctor']} 한의사",
        "h1": title,
        "short": title,
        "description": get("설명", "description"),
        "published": when,
        "updated": get("수정", "updated") or when,
        "crumbs": [["칼럼", "/column/"]],
        "faq": faq,
        "body": md_to_html("\n".join(rest)) + ("\n{{FAQ}}" if faq else "") + "\n{{REVIEWER}}\n{{CLINIC}}",
    }
    return meta


def clinic_schema():
    return {
        "@type": ["MedicalClinic", "LocalBusiness"],
        "@id": f"{D}/#clinic",
        "name": C["name"],
        "url": C["url"],
        "telephone": C["tel"],
        "address": {
            "@type": "PostalAddress",
            "streetAddress": C["street"],
            "addressLocality": C["locality"],
            "addressRegion": C["region"],
            "addressCountry": "KR",
        },
        "openingHoursSpecification": [
            {"@type": "OpeningHoursSpecification", "dayOfWeek": h["days"],
             "opens": h["opens"], "closes": h["closes"]} for h in C["hours"]
        ],
        "medicalSpecialty": "Dermatology",
        "sameAs": [C["url"], C["kakao"]],
    }


def doctor_schema():
    return {
        "@type": "Physician",
        "@id": f"{D}/#doctor",
        "name": CFG["doctor"],
        "jobTitle": CFG["doctor_title"],
        "url": f"{D}/doctor/",
        "worksFor": {"@id": f"{D}/#clinic"},
    }


def page_schema(m):
    url = D + m["path"]
    graph = [
        {"@type": "WebSite", "@id": f"{D}/#website", "url": D + "/",
         "name": CFG["site_name"], "inLanguage": "ko-KR",
         "publisher": {"@id": f"{D}/#doctor"}},
        clinic_schema(),
        doctor_schema(),
        {"@type": "MedicalWebPage" if m.get("medical") else "WebPage",
         "@id": url + "#webpage", "url": url, "name": m["title"],
         "description": m["description"], "inLanguage": "ko-KR",
         "isPartOf": {"@id": f"{D}/#website"},
         "datePublished": m["published"], "dateModified": m["updated"],
         **({"reviewedBy": {"@id": f"{D}/#doctor"}, "lastReviewed": m["updated"],
             "author": {"@id": f"{D}/#doctor"}} if m.get("medical") else {})},
    ]
    crumbs = [("홈", D + "/")] + [(n, D + u) for n, u in m.get("crumbs", [])]
    if m["path"] != "/":
        crumbs.append((m.get("short", m["h1"]), url))
        graph.append({"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": u}
            for i, (n, u) in enumerate(crumbs)]})
    if m.get("faq"):
        graph.append({"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in m["faq"]]})
    return json.dumps({"@context": "https://schema.org", "@graph": graph},
                      ensure_ascii=False, indent=1)


def faq_html(m):
    items = "".join(
        f'<details class="faq"><summary>Q{i+1}. {esc(q)}</summary><p>{esc(a)}</p></details>'
        for i, (q, a) in enumerate(m.get("faq", [])))
    return f'<section id="faq"><h2>자주 묻는 질문</h2>{items}</section>'


def reviewer_html(m):
    return f'''<aside class="reviewer">
  <img src="/static/doctor.webp" alt="후한의원 인천점 {esc(CFG["doctor"])} 대표원장" width="96" height="96" loading="lazy" onerror="this.style.display='none'">
  <div>
    <p class="label">감수 한의사</p>
    <p class="name"><a href="/doctor/">{esc(CFG["doctor"])}</a> · {esc(CFG["doctor_title"])}</p>
    {f'<p class="comment">{esc(m["comment"])}</p>' if m.get("comment") else ""}
    <p class="date">최종 수정 {esc(m["updated"])}</p>
  </div>
</aside>'''


def clinic_html(m):
    return f'''<section class="clinic" id="clinic">
  <h2>{esc(m.get("clinic_heading", "진료 안내"))}</h2>
  {f'<p>{esc(m["clinic_intro"])}</p>' if m.get("clinic_intro") else ""}
  <dl>
    <dt>병원</dt><dd><a href="{C["url"]}">{esc(C["name"])}</a></dd>
    <dt>주소</dt><dd>{esc(C["region"])} {esc(C["locality"])} {esc(C["street"])} ({esc(C["subway"])})</dd>
    <dt>전화</dt><dd><a href="tel:{C["tel"]}">{C["tel"]}</a></dd>
    <dt>진료</dt><dd>{esc(C["hours_text"])}</dd>
    <dt>주차</dt><dd>{esc(C["parking"])}</dd>
  </dl>
  <div class="cta">
    <a class="btn primary" href="tel:{C["tel"]}">전화 문의</a>
    <a class="btn" href="{C["kakao"]}">카카오톡 상담</a>
    <a class="btn" href="{C["url"]}">홈페이지·예약</a>
  </div>
</section>'''


NAV = [("질환 정보", "/#diseases"), ("칼럼", "/column/"), ("원장 소개", "/doctor/"), ("오시는 길", "/clinic/")]
DISEASES_HTML = COLUMNS_HTML = LATEST_HTML = ""


def list_html(pages, limit=None):
    items = "".join(
        f'<li><a href="{m["path"]}">{esc(m["h1"])}</a> <span class="note">{esc(m["published"])}</span></li>'
        for m in pages[:limit])
    return f'<ul class="list">{items}</ul>' if items else '<p class="note">곧 첫 글이 올라옵니다.</p>'


def render(m):
    body = m["body"]
    body = body.replace("{{FAQ}}", faq_html(m)).replace("{{REVIEWER}}", reviewer_html(m))
    body = body.replace("{{CLINIC}}", clinic_html(m)).replace("{{DOMAIN}}", D)
    body = body.replace("{{DISEASES}}", DISEASES_HTML).replace("{{COLUMNS}}", COLUMNS_HTML)
    body = body.replace("{{LATEST}}", LATEST_HTML)
    url = D + m["path"]
    nav = "".join(f'<a href="{u}">{esc(n)}</a>' for n, u in NAV)
    crumbs = ""
    if m["path"] != "/":
        parts = [("홈", "/")] + m.get("crumbs", [])
        crumbs = '<nav class="crumbs" aria-label="위치">' + " › ".join(
            f'<a href="{u}">{esc(n)}</a>' for n, u in parts) + f' › <span>{esc(m.get("short", m["h1"]))}</span></nav>'
    og_img = D + m.get("image", "/static/og.jpg")
    return f'''<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(m["title"])}</title>
<meta name="description" content="{esc(m["description"])}">
<link rel="canonical" href="{url}">
<meta name="robots" content="{"noindex, nofollow" if PREVIEW else "index, follow, max-image-preview:large"}">
<meta name="author" content="{esc(CFG["doctor"])}">
<meta property="og:type" content="{"article" if m.get("medical") else "website"}">
<meta property="og:site_name" content="{esc(CFG["site_name"])}">
<meta property="og:title" content="{esc(m["title"])}">
<meta property="og:description" content="{esc(m["description"])}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{og_img}">
<meta property="og:locale" content="ko_KR">
{"".join(f'<meta name="{k}" content="{esc(v)}">' for k, v in CFG.get("verify", {}).items())}
<link rel="alternate" type="application/rss+xml" title="{esc(CFG["site_name"])}" href="{D}/rss.xml">
<link rel="stylesheet" href="/static/style.css">
<script type="application/ld+json">
{page_schema(m)}
</script>
</head>
<body>
<header class="site">
  <a class="brand" href="/">{esc(CFG["site_name"])}</a>
  <nav>{nav}</nav>
</header>
<main>
{crumbs}
<article>
<h1>{esc(m["h1"])}</h1>
{body}
</article>
</main>
<footer class="site">
  <p><strong>{esc(CFG["site_name"])}</strong> · {esc(CFG["doctor_title"])} {esc(CFG["doctor"])}</p>
  <p>{esc(C["region"])} {esc(C["locality"])} {esc(C["street"])} · <a href="tel:{C["tel"]}">{C["tel"]}</a> · <a href="{C["url"]}">{esc(C["name"])} 홈페이지</a></p>
  <p class="small">이 사이트의 글은 일반적인 건강 정보이며 진료를 대신하지 않습니다. 효과는 개인의 상태에 따라 다를 수 있습니다.</p>
</footer>
<script src="/static/site.js" defer></script>
</body>
</html>
'''


def main():
    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(ROOT / "static", DIST / "static")
    global DISEASES_HTML, COLUMNS_HTML, LATEST_HTML
    pages = [read_page(p) for p in sorted((ROOT / "pages").glob("*.html"))]
    pages += [read_column(p) for p in sorted((ROOT / "columns").glob("*.md")) if not p.name.startswith("_")]
    diseases = sorted((m for m in pages if m.get("card")), key=lambda m: m.get("order", 99))
    DISEASES_HTML = '<div class="cards">' + "".join(
        f'<div class="card"><h3><a href="{m["path"]}">{esc(m["short"])}</a></h3><p>{esc(m["card"])}</p></div>'
        for m in diseases) + "</div>"
    by_date = lambda ms: sorted(ms, key=lambda m: m["published"], reverse=True)
    COLUMNS_HTML = list_html(by_date([m for m in pages if m.get("column")]))
    LATEST_HTML = list_html(by_date([m for m in pages if m.get("medical")]), 8)
    for m in pages:
        out = DIST / m["path"].strip("/") / "index.html" if m["path"] != "/" else DIST / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(with_base(render(m)), encoding="utf-8")
    urls = "".join(
        f"<url><loc>{D}{m['path']}</loc><lastmod>{m['updated']}</lastmod></url>" for m in pages)
    (DIST / "sitemap.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n',
        encoding="utf-8")
    rules = "Disallow: /" if PREVIEW else "Allow: /"
    # AI 검색 크롤러도 명시적으로 허용 (ChatGPT·Claude·Perplexity·Gemini·네이버)
    ai_bots = ["OAI-SearchBot", "GPTBot", "ClaudeBot", "Claude-SearchBot", "PerplexityBot", "Google-Extended", "Yeti"]
    if not PREVIEW:
        rules += "\n\n" + "\n\n".join(f"User-agent: {b}\nAllow: /" for b in ai_bots)
    lines = [f"# {CFG['site_name']}", "", f"> {CFG['site_desc']}", "",
             f"- 작성·감수: {CFG['doctor']} ({CFG['doctor_title']})",
             f"- 병원: {C['name']}, {C['region']} {C['locality']} {C['street']}, {C['tel']}, {C['url']}",
             f"- 진료시간: {C['hours_text']}", "", "## 질환 정보", ""]
    lines += [f"- [{m['short']}]({D}{m['path']}): {m.get('card', m['description'])}" for m in diseases]
    cols = [m for m in pages if m.get("column")]
    if cols:
        lines += ["", "## 칼럼", ""] + [f"- [{m['h1']}]({D}{m['path']})" for m in cols]
    (DIST / "llms.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (DIST / "robots.txt").write_text(f"User-agent: *\n{rules}\n\nSitemap: {D}/sitemap.xml\n", encoding="utf-8")
    items = ""
    for m in sorted((m for m in pages if m.get("medical")), key=lambda m: m["published"], reverse=True):
        pub = format_datetime(datetime.fromisoformat(m["published"]).replace(tzinfo=KST))
        items += (f"<item><title>{esc(m['title'])}</title><link>{D}{m['path']}</link>"
                  f"<guid>{D}{m['path']}</guid><description>{esc(m['description'])}</description>"
                  f"<pubDate>{pub}</pubDate></item>")
    (DIST / "rss.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>{esc(CFG["site_name"])}</title>'
        f"<link>{D}/</link><description>{esc(CFG['site_desc'])}</description><language>ko</language>{items}</channel></rss>\n",
        encoding="utf-8")
    if not PREVIEW and not BASE:
        (DIST / "CNAME").write_text(CFG["domain"].split("//")[1].rstrip("/") + "\n", encoding="utf-8")
    print(f"{len(pages)} pages -> {DIST}")


if __name__ == "__main__":
    main()
