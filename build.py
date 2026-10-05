#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 從 BOOTH 與 pictSPACE 抓「全部」商品，同步寫進 index.html
# pictSPACE 圖片有防盜連 -> 下載後縮圖並以 base64 內嵌，讓下載的檔案也能離線顯示
import re, html, os, subprocess, urllib.parse, hashlib, tempfile, base64, json
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, ".imgcache")
os.makedirs(CACHE, exist_ok=True)

BOOTH_URL = "https://mail930115iop.booth.pm/"
PICT_URL  = "https://pictspace.net/stores/detail/lovetraveling"
FANSKY_URL = "https://www.fansky.net/mail930115iop?tab=products"
FANSKY_API = "https://www.fansky.net/api/v1/creator/mail930115iop/shop/products"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

def fetch(url, referer=None):
    cmd = ["curl", "-sL", "--max-time", "45", "-A", UA, "-w", "\n__CT__%{content_type}", url]
    if referer:
        cmd[1:1] = ["-e", referer]
    out = subprocess.check_output(cmd)
    body, _, ct = out.rpartition(b"\n__CT__")
    return body, ct.decode("utf-8", "replace")

def curl_bin(url, referer=None):
    cmd = ["curl", "-sL", "--max-time", "40", "-A", UA]
    if referer:
        cmd += ["-e", referer]
    cmd.append(url)
    return subprocess.check_output(cmd)

def booth_items():
    out, seen, page = [], set(), 1
    while page <= 100:
        t = html.unescape(fetch(BOOTH_URL + "items?page=%d" % page)[0].decode("utf-8", "replace"))
        segs = t.split('"product_id":')
        found = 0
        for i in range(1, len(segs)):
            pid = re.match(r"(\d+)", segs[i])
            name = re.search(r'"product_name":"(.*?)"', segs[i])
            price = re.search(r'"product_price":(\d+)', segs[i])
            if not (pid and name and price):
                continue
            thumbs = re.findall(r'"thumbnail_image_urls":\["([^"]+)"', segs[i-1])
            links = re.findall(r'"shop_item_url":"([^"]+)"', segs[i-1])
            if not (thumbs and links):
                continue
            if pid.group(1) in seen:
                continue
            seen.add(pid.group(1))
            found += 1
            out.append({"name": name.group(1).strip(), "price": price.group(1),
                        "link": links[-1], "img": thumbs[-1], "r18": False})
        if found == 0:
            break
        page += 1
    return out

def pict_items():
    t = fetch(PICT_URL)[0].decode("utf-8", "replace")
    out = []
    for b in re.split(r'store-item-card', t)[1:]:
        key = re.search(r'data-item-keywords="([^"]*)"', b)
        link = re.search(r'data-action="([^"]+)"', b)
        img = re.search(r'<img src="([^"]+)"', b)
        price = re.search(r'([\d,]+)\s*円', b)
        if not (link and img and price):
            continue
        out.append({
            "name": (key.group(1) if key else "").strip(),
            "price": price.group(1).replace(",", ""),
            "link": "https://pictspace.net" + link.group(1),
            "img": img.group(1),
            "r18": "R18" in b,
        })
    return out

def fansky_items():
    out, seen, page = [], set(), 1
    while page <= 100:
        raw, _ = fetch("%s?page=%d&pageSize=10" % (FANSKY_API, page), referer="https://www.fansky.net/")
        try:
            j = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            break
        prods = j.get("data", {}).get("products", [])
        if not prods:
            break
        fresh = 0
        for p in prods:
            pid = p.get("publicId")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            fresh += 1
            cover = p.get("cover", "")
            if cover and "?" not in cover:
                cover += "?width=384"
            out.append({"name": p.get("title", "").strip(),
                        "price": p.get("effectiveSalesPrice") or p.get("salesPrice") or "",
                        "link": "https://www.fansky.net/mail930115iop/%s" % pid,
                        "img": cover, "cur": "CN\u00a5", "r18": False})
        if len(prods) < 10 or fresh == 0:
            break
        page += 1
    return out

def thumb_from_url(url, width=200, q=6, referer=None, square=False):
    key = hashlib.md5(("%s|%d|%d|%d" % (url, width, q, 1 if square else 0)).encode()).hexdigest()
    out = os.path.join(CACHE, key + ".jpg")
    if not os.path.exists(out):
        raw = curl_bin(url, referer=referer)
        tmp = os.path.join(CACHE, key + ".src")
        with open(tmp, "wb") as f:
            f.write(raw)
        if square:
            vf = "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d" % (width, width, width, width)
        else:
            vf = "scale=%d:-1" % width
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp,
                        "-vf", vf, "-q:v", str(q), out], check=True)
        try:
            os.unlink(tmp)
        except OSError:
            pass
    with open(out, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()

def pict_thumb(url, width=200, q=6):
    return thumb_from_url(url, width, q, referer="https://pictspace.net/", square=True)

PIXIV_USERS = [
    ("lovetraveling_No.1", "99882147"),
    ("lovetraveling_No.2", "118793323"),
]

def pixiv_all_ids(uid):
    raw, _ = fetch("https://www.pixiv.net/ajax/user/%s/profile/all" % uid, referer="https://www.pixiv.net/")
    try:
        j = json.loads(raw.decode("utf-8", "replace"))
        return list(j.get("body", {}).get("illusts", {}).keys())
    except Exception:
        return []

def pixiv_details(uid, ids):
    works = []
    for i in range(0, len(ids), 40):
        chunk = ids[i:i+40]
        q = "&".join("ids[]=%s" % x for x in chunk)
        url = ("https://www.pixiv.net/ajax/user/%s/profile/illusts?%s"
               "&work_category=illust&is_first_page=0" % (uid, q))
        raw, _ = fetch(url, referer="https://www.pixiv.net/")
        try:
            j = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            continue
        for k, v in j.get("body", {}).get("works", {}).items():
            works.append({"id": k, "title": v.get("title", ""), "img": v.get("url", "")})
    return works

def pixiv_section():
    allworks = []
    for label, uid in PIXIV_USERS:
        ids = pixiv_all_ids(uid)
        if not ids:
            continue
        for w in pixiv_details(uid, ids):
            w["account"] = label
            allworks.append(w)
    with ThreadPoolExecutor(max_workers=8) as ex:
        imgs = list(ex.map(lambda w: thumb_from_url(w["img"], 140, 7, referer="https://www.pixiv.net/"), allworks))
    cards = []
    for w, img in zip(allworks, imgs):
        link = "https://www.pixiv.net/artworks/%s" % w["id"]
        cards.append('<a class="shop-card" data-name="%s" href="%s" target="_blank" rel="noopener">'
                     '<img src="%s" loading="lazy" alt="">'
                     '<div class="shop-name">%s</div></a>'
                     % (html.escape(w["title"], quote=True), link, img, html.escape(w["title"])))
    return ('<div class="store-title" style="margin-top:1.3rem;">\U0001F3A8 PIXIV \u00b7 \u4f5c\u54c1\uff08%d \u4ef6\uff09</div>'
            '<input class="shop-search" type="search" placeholder="\u641c\u5c0b PIXIV \u4f5c\u54c1 / Search\u2026" data-grid="grid-pixiv" oninput="filterStore(this)">'
            '<div class="store-box"><div class="shop-grid" id="grid-pixiv">%s</div></div>'
            % (len(allworks), "".join(cards)))

def card(it, img_src):
    r18 = ' <span style="color:#e5507f;font-size:.68rem;">R18</span>' if it.get("r18") else ""
    cur = it.get("cur", "\u00a5")
    return ('<a class="shop-card" data-name="%s" href="%s" target="_blank" rel="noopener">'
            '<img src="%s" loading="lazy" alt="">'
            '<div class="shop-name">%s%s</div>'
            '<div class="shop-price">%s%s</div></a>'
            ) % (html.escape(it["name"], quote=True), it["link"], img_src,
                 html.escape(it["name"]), r18, cur, it["price"])

def main():
    booth = booth_items()
    pict = pict_items()
    fansky = fansky_items()

    # pictSPACE 縮圖（並行）
    with ThreadPoolExecutor(max_workers=6) as ex:
        pict_imgs = list(ex.map(lambda it: pict_thumb(it["img"]), pict))

    parts = ['<div class="stores">']
    parts.append('<div class="store-col">'
                 '<div class="store-title">BOOTH \u00b7 <a href="%s" target="_blank" rel="noopener">mail930115iop.booth.pm</a></div>'
                 '<input class="shop-search" type="search" placeholder="\u641c\u5c0b BOOTH \u5546\u54c1 / Search\u2026" data-grid="grid-booth" oninput="filterStore(this)">'
                 '<div class="store-box"><div class="shop-grid" id="grid-booth">' % BOOTH_URL)
    for it in booth:
        parts.append(card(it, it["img"]))
    parts.append('</div></div></div>')

    parts.append('<div class="store-col">'
                 '<div class="store-title">FANSKY\uff08\u4eba\u6c11\u5e63\u4ed8\u6b3e\uff09 \u00b7 <a href="%s" target="_blank" rel="noopener">fansky.net</a></div>'
                 '<input class="shop-search" type="search" placeholder="\u641c\u5c0b FANSKY \u5546\u54c1 / Search\u2026" data-grid="grid-fansky" oninput="filterStore(this)">'
                 '<div class="store-box"><div class="shop-grid" id="grid-fansky">' % FANSKY_URL)
    for it in fansky:
        parts.append(card(it, it["img"]))
    parts.append('</div></div></div>')

    parts.append('<div class="store-col">'
                 '<div class="store-title">pictSPACE \u00b7 <a href="%s" target="_blank" rel="noopener">pictspace.net</a></div>'
                 '<input class="shop-search" type="search" placeholder="\u641c\u5c0b pictSPACE \u5546\u54c1 / Search\u2026" data-grid="grid-pict" oninput="filterStore(this)">'
                 '<div class="store-box"><div class="shop-grid" id="grid-pict">' % PICT_URL)
    for it, img in zip(pict, pict_imgs):
        parts.append(card(it, img))
    parts.append('</div></div></div>')
    parts.append('</div>')
    products = "\n".join(parts)

    tpl = open(os.path.join(BASE, "index.template.html"), encoding="utf-8").read()
    out = tpl.replace("<!--PRODUCTS-->", products)
    if "<!--PIXIV-->" in tpl:
        out = out.replace("<!--PIXIV-->", pixiv_section())
    open(os.path.join(BASE, "index.html"), "w", encoding="utf-8").write(out)
    print("OK booth=%d pict=%d fansky=%d bytes=%d" % (len(booth), len(pict), len(fansky), len(out)))

main()
