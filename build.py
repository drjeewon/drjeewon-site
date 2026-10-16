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
    """칼럼용 아주 단순한 마크다운: ## ### 문단, - 목록, 1. 목록, > 인용, | 표 |, **굵게**, [링크](주소), ![사진](주소)"""
    out, para, lst, rows = [], [], None, []

    def flush():
        nonlocal para, lst, rows
        if rows:
            cells = [[c.strip() for c in r.strip("|").split("|")] for r in rows
                     if not re.fullmatch(r"[|\s:-]+", r)]
            head, body = cells[0], cells[1:]
            out.append('<div class="table-wrap"><table><thead><tr>' + "".join(f"<th>{inline_md(c)}</th>" for c in head)
                       + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{inline_md(c)}</td>" for c in r) + "</tr>" for r in body)
                       + "</tbody></table></div>")
            rows = []
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
        if t.startswith("|"):
            if not rows:
                flush()
            rows.append(t)
            continue
        if rows:
            flush()
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
        "related": get("관련", "related"),
        "faq": faq,
        "thumb": thumb_lines(get("썸네일", "thumbnail"), title),
        "image": f"/column/{slug}/thumb.jpg",
        "body": put_thumb(md_to_html("\n".join(rest)),
                          f'<img class="thumb" src="/column/{slug}/thumb.jpg" alt="{esc(title)}" width="1200" height="1200">') + ("\n{{FAQ}}" if faq else "") + "\n{{REVIEWER}}\n{{CLINIC}}",
    }
    return meta


def put_thumb(body, img):
    """썸네일은 첫 답변 박스 바로 아래에: AI와 독자가 먼저 읽는 결론을 그림이 밀어내지 않게."""
    mm = re.search(r'<p class="answer">.*?</p>', body, re.S)
    return body[:mm.end()] + "\n" + img + body[mm.end():] if mm else img + "\n" + body


def thumb_lines(spec, title):
    """머리말 '썸네일: 강조할 말 | 질문 줄'. 없으면 제목을 첫 쉼표에서 나눠 씀."""
    if spec:
        return [x.strip() for x in spec.split("|") if x.strip()]
    t = title.rstrip()
    if "," in t:
        a, c = t.split(",", 1)
        return [a.strip(), c.strip()]
    words = t.split()
    half = max(1, len(words) // 2)
    return [" ".join(words[:half]), " ".join(words[half:])]


def make_thumb(lines, out):
    """칼럼 썸네일 1200x1200: 남색 바탕, 첫 줄(강조할 말)은 크게 노란색, 나머지(질문)는 흰색."""
    from PIL import Image, ImageDraw, ImageFont
    fonts = ROOT / "assets" / "fonts"
    W, maxw = 1200, 1020
    im = Image.new("RGB", (W, W), "#1f4289")
    d = ImageDraw.Draw(im)
    font = lambda s, w="Black": ImageFont.truetype(str(fonts / f"Pretendard-{w}.otf"), s)

    def fit(text, start, low, w="Black"):
        s = start
        while s > low and d.textlength(text, font=font(s, w)) > maxw:
            s -= 4
        return font(s, w), s

    def wrap(text, f):
        if d.textlength(text, font=f) <= maxw:
            return [text]
        words = text.split()
        best = min(range(1, len(words)), key=lambda k: abs(len(" ".join(words[:k])) - len(" ".join(words[k:])))) if len(words) > 1 else 1
        return [" ".join(words[:best]), " ".join(words[best:])]

    # 노란 핵심어: '/'로 줄을 나누거나, 한 줄로 크게 안 들어가면 2단으로 쌓는다
    keys = [x.strip() for x in lines[0].split("/") if x.strip()]
    rest = " ".join(lines[1:])
    if len(keys) == 1 and d.textlength(keys[0], font=font(260)) > maxw and " " in keys[0]:
        w = keys[0].split()
        k = min(range(1, len(w)), key=lambda k: abs(len(" ".join(w[:k])) - len(" ".join(w[k:]))))
        keys = [" ".join(w[:k]), " ".join(w[k:])]
    ks = 290 if len(keys) > 1 else 300
    while ks > 120 and max(d.textlength(x, font=font(ks)) for x in keys) > maxw:
        ks -= 6
    kf = font(ks)
    sub_f = font(104, "Bold")
    sub = wrap(rest, sub_f) if rest else []
    while sub and max(d.textlength(x, font=sub_f) for x in sub) > maxw and sub_f.size > 64:
        sub_f = font(sub_f.size - 4, "Bold")
    top_f = font(84, "Bold")
    blocks = [(CFG.get("thumb_label", "후한의원 인천"), top_f, "#fdf09a", 84 * 1.75)]
    blocks += [(x, kf, "#fbe359", ks * 1.18) for x in keys]
    blocks += [(x, sub_f, "#ffffff", sub_f.size * 1.36) for x in sub]
    total = sum(h for *_, h in blocks) + (30 if sub else 0)
    y = (W - total) / 2
    for n, (text, f, color, h) in enumerate(blocks):
        if sub and n == len(blocks) - len(sub):
            y += 30
        d.text((W / 2, y + h / 2), text, font=f, fill=color, anchor="mm")
        y += h
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, quality=88, optimize=True)


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
        "areaServed": [{"@type": "City", "name": "인천광역시"}, {"@type": "Place", "name": "인천 남동구 구월동"}],
        "knowsAbout": CLINIC_TOPICS,
        "isAcceptingNewPatients": True,
        "image": D + C.get("image", "/static/og-v4.jpg"),
        "priceRange": C.get("price_range", "₩₩"),
        **({"hasMap": C["place"]} if C.get("place") else {}),
        **({"potentialAction": {"@type": "ReserveAction", "target": C["booking"]}} if C.get("booking") else {}),
        "sameAs": [u for u in (C["url"], C.get("place"), C.get("blog"), C.get("instagram"), C["kakao"]) if u],
    }


def doctor_schema():
    return {
        "@type": "Physician",
        "@id": f"{D}/#doctor",
        "name": CFG["doctor"],
        "jobTitle": CFG["doctor_title"],
        "url": f"{D}/doctor/",
        "worksFor": {"@id": f"{D}/#clinic"},
        **({"image": D + CFG["doctor_image"]} if CFG.get("doctor_image") else {}),
        **({"memberOf": [{"@type": "Organization", "name": n} for n in CFG["doctor_memberships"]]}
           if CFG.get("doctor_memberships") else {}),
        "knowsAbout": ["여드름", "여드름 흉터", "피부질환", "한방 다이어트"],
    }


def page_schema(m):
    url = D + m["path"]
    graph = [
        {"@type": "WebSite", "@id": f"{D}/#website", "url": D + "/",
         "name": CFG["site_name"], "inLanguage": "ko-KR",
         "publisher": {"@id": f"{D}/#doctor"},
         "publishingPrinciples": f"{D}/policy/"},
        clinic_schema(),
        doctor_schema(),
        {"@type": "MedicalWebPage" if m.get("medical") else "WebPage",
         "@id": url + "#webpage", "url": url, "name": m["title"],
         "description": m["description"], "inLanguage": "ko-KR",
         "isPartOf": {"@id": f"{D}/#website"},
         "datePublished": m["published"], "dateModified": m["updated"],
         **({"primaryImageOfPage": D + m["image"]} if m.get("thumb") else {}),
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
        f'<details class="faq"><summary><span class="q">Q.</span><span class="qt">{esc(q)}</span></summary><p>{esc(a)}</p></details>'
        for q, a in m.get("faq", []))
    return f'<section id="faq"><p class="eyebrow">FAQ</p><h2>자주 묻는 질문</h2>{items}</section>'


def reviewer_html(m):
    return f'''<aside class="reviewer">
  <img src="/static/doctor.webp" alt="후한의원 인천점 {esc(CFG["doctor"])} 대표원장" width="96" height="96" loading="lazy">
  <div>
    <p class="label">감수 한의사</p>
    <p class="name"><a href="/doctor/">{esc(CFG["doctor"])}</a> · {esc(CFG["doctor_title"])}</p>
    {f'<p class="comment">{esc(m["comment"])}</p>' if m.get("comment") else ""}
    <p class="date">최종 수정 {esc(m["updated"])}</p>
  </div>
</aside>'''


def events_html(m):
    """질환 페이지·칼럼에서 해당 시술 이벤트 페이지로 바로 가는 버튼.
    config.json events: {"/acne/": [["이름 · 가격", "주소"], ...]}. 칼럼은 머리말 '관련: /acne/'로 고름."""
    evs = CFG.get("events", {}).get(m.get("related") or m["path"], [])
    if not evs:
        return ""
    items = "".join(f'<a class="event" href="{esc(u)}">{esc(n)}<span>자세히 보기 ›</span></a>' for n, u in evs)
    return f'<div class="events"><p class="label">관련 시술·이벤트 (후한의원 인천점 홈페이지)</p>{items}</div>'


def clinic_html(m):
    rows = lambda rs: "".join(f'<div class="row"><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in rs)
    return f'''<section class="clinic" id="clinic">
  <p class="eyebrow">CONTACT</p>
  <h2>{esc(m.get("clinic_heading", "진료 안내"))}</h2>
  {f'<p class="lead">{esc(m["clinic_intro"])}</p>' if m.get("clinic_intro") else ""}
  {events_html(m)}
  <div class="info3">
    <div>
      <p class="k"><b>01</b> ADDRESS</p>
      <p class="big">{esc(C.get("addr_main", C["street"]))}</p>
      <p class="sub">{esc(C.get("addr_sub", C["subway"]))}</p>
      <p class="muted">{esc(C.get("addr_note", ""))}</p>
    </div>
    <div>
      <p class="k"><b>02</b> HOURS</p>
      {rows(C.get("hours_rows", []))}
      <span class="chip">{esc(C.get("closed_text", ""))}</span>
    </div>
    <div>
      <p class="k"><b>03</b> PARKING</p>
      {rows(C.get("parking_rows", []))}
      <p class="muted">{esc(C.get("parking_note", ""))}</p>
    </div>
  </div>
  <div class="cta">
    {f'<a class="btn primary" href="{esc(C["booking"])}">네이버 예약</a>' if C.get("booking") else ""}
    <a class="btn" href="tel:{C["tel"]}">전화 {C["tel"]}</a>
    <a class="btn" href="{C["kakao"]}">카카오톡 상담</a>
    <a class="btn" href="{C["url"]}">{esc(C["name"])} 홈페이지</a>
  </div>
</section>'''


ICONS = {
    "tel": '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/></svg>',
    "naver": '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M15.6 12.8 8.1 2H2v20h6.4V11.2L15.9 22H22V2h-6.4z"/></svg>',
    "kakao": '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M12 3C6.5 3 2 6.5 2 10.8c0 2.8 1.9 5.2 4.7 6.6l-1 3.6c-.1.4.3.7.6.5l4.2-2.8c.5.1 1 .1 1.5.1 5.5 0 10-3.5 10-7.9S17.5 3 12 3z"/></svg>',
    "insta": '<svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor" stroke="none"/></svg>',
}


def dock_html(m):
    """화면 아래 떠 있는 예약 바: 왼쪽은 돌아가는 안내 문구, 오른쪽은 전화·네이버 예약·카카오톡·인스타그램."""
    msgs = CFG.get("events", {}).get(m.get("related") or m["path"]) or CFG.get("dock", [])
    msgs = [[n, u] for n, u in msgs][:8]
    book = ["네이버로 진료 예약하기", C.get("booking", C["url"])]
    if book[1] not in [u for _, u in msgs]:
        msgs.append(book)  # 이벤트가 있는 페이지도 예약 문구가 한 번은 돌게
    first = msgs[0]
    links = [("tel", f"tel:{C['tel']}", "전화 문의", "call"), ("naver", C.get("booking"), "네이버 예약", ""),
             ("kakao", C.get("kakao"), "카카오톡 상담", ""), ("insta", C.get("instagram"), "인스타그램", "")]
    btns = "".join(f'<a class="ic {cls}" href="{esc(u)}" aria-label="{lab}">{ICONS[k]}</a>' for k, u, lab, cls in links if u)
    return (f'<div class="dock" data-msgs=\'{esc(json.dumps(msgs, ensure_ascii=False))}\'>'
            f'<a class="dock-msg" href="{esc(first[1])}"><i></i><span>{esc(first[0])}</span><em>→</em></a>'
            f'<span class="dock-sep"></span><div class="dock-btns">{btns}</div></div>')


NAV = [("질환 정보", "/#diseases"), ("칼럼", "/column/"), ("원장 소개", "/doctor/"), ("오시는 길", "/clinic/")]
DISEASES_HTML = COLUMNS_HTML = LATEST_HTML = PROGRAMS_HTML = ""


def list_html(pages, limit=None):
    items = "".join(
        f'<li><a href="{m["path"]}">{esc(m["h1"])}</a> <span class="note">{esc(m["published"])}</span></li>'
        for m in pages[:limit])
    return f'<ul class="list">{items}</ul>' if items else '<p class="note">첫 칼럼을 준비하고 있습니다. 그동안 아래 질환별 글을 먼저 읽어 보세요.</p>'


def related_cols_html(m):
    """질환 페이지 ↔ 칼럼을 서로 묶는다: 질환 페이지에는 그 질환 칼럼 목록, 칼럼에는 같은 질환의 다른 칼럼."""
    key = m.get("related") if m.get("column") else m["path"]
    cols = [c for c in ALL_COLUMNS if key and c.get("related") == key and c["path"] != m["path"]][:6]
    if not cols:
        return ""
    title = "같은 주제의 다른 칼럼" if m.get("column") else f"{m.get('short', m['h1'])} 관련 칼럼"
    items = "".join(f'<li><a href="{c["path"]}">{esc(c["h1"])}</a></li>' for c in cols)
    return f'<section class="related-cols"><h2>{esc(title)}</h2><ul class="list">{items}</ul></section>\n'


def column_list_html(cols, search=False):
    if not cols:
        return list_html([])
    items = "".join(
        f'<a class="col-card" href="{m["path"]}"><img src="{m["image"]}" alt="" width="600" height="600" loading="lazy">'
        f'<strong>{esc(m["h1"])}</strong><span class="note">{esc(m["published"])}</span></a>' for m in cols)
    box = (f'<div class="col-search"><p><b>원장 칼럼 전체</b> <span>{len(cols)}편</span></p>'
           f'<input type="search" placeholder="칼럼 제목 검색" aria-label="칼럼 제목 검색"></div>') if search else ""
    return f'{box}<div class="col-grid">{items}</div>'


def static_selfcheck(body):
    """자바스크립트를 안 읽는 크롤러도 자가체크 결과 기준을 읽을 수 있게 결과 칸에 미리 적어 둔다."""
    def fill(mm):
        rules = json.loads(html.unescape(mm.group(1)))
        rest = mm.group(2)
        parts = []
        for i, (n, msg) in enumerate(rules):
            nxt = rules[i + 1][0] if i + 1 < len(rules) else None
            rng = f"{n}개 이상" if nxt is None else (f"{n}개" if nxt - 1 == n else f"{n}~{nxt - 1}개")
            parts.append(f"{rng}: {esc(msg)}")
        text = "체크한 개수별 안내<br>" + "<br>".join(parts)
        rest = rest.replace('<p class="result" aria-live="polite"></p>',
                            f'<p class="result" aria-live="polite">{text}</p>', 1)
        return mm.group(0)[:mm.start(2) - mm.start(0)] + rest
    return re.sub(r"""<div class="selfcheck" data-rules='(.*?)'>(.*?</div>)""", fill, body, flags=re.S)


def duo_h1(t):
    """'앞부분, 뒷부분' 제목을 얇은 첫 줄 + 굵은 둘째 줄로."""
    if "," in t:
        a, c = t.split(",", 1)
        return f'<span>{esc(a.strip())},</span> {esc(c.strip())}'
    return esc(t)


def render(m):
    body = m["body"]
    body = static_selfcheck(body)
    body = body.replace("{{REVIEWER}}", related_cols_html(m) + "{{REVIEWER}}", 1)
    body = body.replace("{{FAQ}}", faq_html(m)).replace("{{REVIEWER}}", reviewer_html(m))
    body = body.replace("{{CLINIC}}", clinic_html(m)).replace("{{DOMAIN}}", D)
    body = body.replace("{{PROGRAMS}}", PROGRAMS_HTML).replace("{{DISEASES}}", DISEASES_HTML).replace("{{COLUMNS}}", COLUMNS_HTML)
    body = body.replace("{{LATEST}}", LATEST_HTML)
    url = D + m["path"]
    nav = "".join(f'<a href="{u}">{esc(n)}</a>' for n, u in NAV)
    crumbs = ""
    if m["path"] != "/":
        parts = [("홈", "/")] + m.get("crumbs", [])
        crumbs = '<nav class="crumbs" aria-label="위치">' + " › ".join(
            f'<a href="{u}">{esc(n)}</a>' for n, u in parts) + f' › <span>{esc(m.get("short", m["h1"]))}</span></nav>'
    og_img = D + m.get("image", "/static/og-v4.jpg")
    home = m["path"] == "/"
    hero = ""
    if home:
        mm = re.search(r'<p class="answer">(.*?)</p>\s*', body, re.S)
        lead = mm.group(1) if mm else ""
        if mm:
            body = body[:mm.start()] + body[mm.end():]
        hero = f'''<section class="hero hero-soft">
  <div class="hs-inner">
    <p class="eyebrow">HOO CLINIC · INCHEON GUWOL</p>
    <h1 class="duo">{duo_h1(m["h1"])}</h1>
    <p class="lead">{lead}</p>
    <div class="cta">
      {f'<a class="btn primary" href="{esc(C["booking"])}">네이버 예약</a>' if C.get("booking") else ""}
      <a class="btn" href="tel:{C["tel"]}">전화 문의</a>
      <a class="btn" href="{C["kakao"]}">카카오톡 상담</a>
      <a class="btn" href="{C["url"]}">홈페이지</a>
    </div>
  </div>
</section>'''
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
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<link rel="stylesheet" href="/static/style.css">
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="/static/favicon-32.png">
<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
<meta name="theme-color" content="#f7f8fa">
<script type="application/ld+json">
{page_schema(m)}
</script>
</head>
<body>
<header class="site">
  <div class="bar">
    <a class="brand" href="/" aria-label="{esc(CFG["site_name"])} 홈"><img src="/static/icon-192.png" alt="" width="40" height="40"><span><strong>{esc(CFG["doctor"])} 한의사</strong><small class="live" data-hours='{esc(json.dumps([[h["days"], h["opens"], h["closes"]] for h in C["hours"]]))}' data-lunch='{esc(json.dumps(C.get("lunch", [])))}'>{esc(CFG["doctor_title"])}</small></span></a>
    <nav>{nav}</nav>
    <a class="nav-cta" href="{esc(C.get("booking", C["url"]))}">상담 예약</a>
  </div>
</header>
<main{' class="home"' if home else ""}>
{crumbs}
<article>
{hero if home else f'<h1>{esc(m["h1"])}</h1>'}
{body}
</article>
</main>
<footer class="site">
  <div class="wrap f-top">
    <p class="f-name">{esc(CFG["site_name"])}</p>
    <p class="f-tag"><span>이름부터 정확히 붙이고,</span> <b>다시 올라오는 이유까지 함께.</b></p>
  </div>
  <div class="wrap f-grid">
    <div class="f-brand">
      <p>{esc(CFG["doctor_title"])} {esc(CFG["doctor"])}</p>
      <img class="f-logo" src="/static/hoo-logo-white.webp" alt="{esc(C["name"])}" width="122" height="48" loading="lazy">
    </div>
    <div>
      <p class="f-title">병원 정보</p>
      <p>{esc(C["region"])} {esc(C["locality"])} {esc(C["street"])}</p>
      <p>{esc(C["hours_text"])}</p>
      <p><a href="tel:{C["tel"]}">{C["tel"]}</a> · <a href="{C["url"]}">{esc(C["name"])} 홈페이지</a></p>
    </div>
    <div>
      <p class="f-title">바로가기</p>
      <p class="f-links">{"".join(f'<a href="{u}" rel="me">{n}</a>' for n, u in (("네이버 예약", C.get("booking")), ("네이버 플레이스", C.get("place")), ("블로그", C.get("blog")), ("인스타그램", C.get("instagram")), ("카카오톡 상담", C.get("kakao"))) if u)}</p>
    </div>
  </div>
  <p class="small wrap"><a href="/policy/">콘텐츠 작성 원칙</a> · 이 사이트의 글은 일반적인 건강 정보이며 진료를 대신하지 않습니다. 효과는 개인의 상태에 따라 다를 수 있습니다.</p>
</footer>
{dock_html(m)}
<script src="/static/site.js" defer></script>
</body>
</html>
'''


ALL_COLUMNS = []
CLINIC_TOPICS = ["여드름", "청소년 여드름", "등드름·몸여드름", "여드름 흉터", "여드름 자국", "기미", "흑자·잡티", "주근깨",
                 "주사피부염·안면홍조", "지루성피부염", "모낭염", "한포진", "한관종", "편평사마귀", "쥐젖·비립종·검버섯", "모공각화증", "한방 다이어트"]


def main():
    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(ROOT / "static", DIST / "static")
    shutil.copy(ROOT / "static" / "favicon.ico", DIST / "favicon.ico")
    global DISEASES_HTML, COLUMNS_HTML, LATEST_HTML, PROGRAMS_HTML
    pages = [read_page(p) for p in sorted((ROOT / "pages").glob("*.html"))]
    pages += [read_column(p) for p in sorted((ROOT / "columns").glob("*.md")) if not p.name.startswith("_")]
    carded = {m["path"]: m for m in sorted((m for m in pages if m.get("card")), key=lambda m: m.get("order", 99))}
    treat_paths = [u for u in CFG.get("treatments", []) if u in carded]
    groups = [(gid, name, [carded[u] for u in paths if u in carded]) for gid, name, paths in CFG.get("groups", [])]
    grouped = {m["path"] for _, _, ms in groups for m in ms} | set(treat_paths)
    rest = [m for u, m in carded.items() if u not in grouped]
    if rest:
        groups.append(("etc", "기타", rest))
    diseases = [m for _, _, ms in groups for m in ms]
    treatments = [carded[u] for u in treat_paths]
    card = lambda m: f'<div class="card"><h4><a href="{m["path"]}">{esc(m["short"])}</a></h4><p>{esc(m["card"])}</p></div>'
    DISEASES_HTML = "".join(
        f'<h3 class="group" id="{gid}">{esc(name)}</h3><div class="cards">{"".join(card(m) for m in ms)}</div>'
        for gid, name, ms in groups if ms)
    info = CFG.get("group_info", {})
    PROGRAMS_HTML = '<div class="programs-grid">' + "".join(
        f'<div class="pg" id="{gid}"><p class="pg-en">{esc(info.get(gid, ["", ""])[0])}</p><h3>{esc(name)}</h3>'
        f'<p class="pg-d">{esc(info.get(gid, ["", ""])[1])}</p>'
        f'<ul>{"".join(f"<li><a href=\"{m["path"]}\">{esc(m["short"])}</a></li>" for m in ms)}</ul></div>'
        for gid, name, ms in groups if ms) + '</div>'
    if treatments:
        DISEASES_HTML += ('<h2 id="treatments">치료 방법 안내</h2><div class="cards">'
                          + "".join(card(m) for m in treatments) + "</div>")
    by_date = lambda ms: sorted(ms, key=lambda m: m["published"], reverse=True)
    ALL_COLUMNS[:] = by_date([m for m in pages if m.get("column")])
    COLUMNS_HTML = column_list_html(ALL_COLUMNS, search=True)
    # 칼럼이 생기면 홈에는 최신 칼럼을 썸네일 카드로, 아직 없으면 최근 정리한 질환 글 목록으로
    LATEST_HTML = (column_list_html(ALL_COLUMNS[:6]) if ALL_COLUMNS
                   else list_html(by_date([m for m in pages if m.get("medical")]), 8))
    for m in pages:
        if m.get("thumb"):
            make_thumb(m["thumb"], DIST / m["image"].lstrip("/"))
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
    for _, name, ms in groups:
        if ms:
            lines += ["", f"### {name}", ""] + [f"- [{m['short']}]({D}{m['path']}): {m.get('card', m['description'])}" for m in ms]
    if treatments:
        lines += ["", "## 치료 방법 안내", ""] + [f"- [{m['short']}]({D}{m['path']}): {m.get('card', m['description'])}" for m in treatments]
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
