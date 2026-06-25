#!/usr/bin/env python3
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
import socket


BASE_DIR = Path(__file__).resolve().parent
CORPUS_PATH = BASE_DIR / "招标参数_梳理中间文本" / "corpus.json"
CONSTRUCTION_PATH = BASE_DIR / "construction_sources.json"
TENDER_SEED_PATH = BASE_DIR / "tender_seed_results.json"
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8768"))

DEFAULT_TENDER_KEYWORDS = "四川 医院 卫健委 合理用药 软件系统 招标"
DEFAULT_TENDER_DATE_RANGE = "month"
DEFAULT_TENDER_STAGE = "all"
DEFAULT_TENDER_REGION = "四川"
SEARCH_TIMEOUT = 12
MAX_SEARCH_RESULTS = 18
MAX_QUERY_VARIANTS = 7
SEED_FIRST_MIN_RESULTS = 2

STAGE_KEYWORDS = {
    "all": "",
    "notice": "招标公告 采购公告",
    "intent": "采购意向 需求公示",
    "change": "更正公告 变更公告",
    "result": "中标公告 成交公告 结果公告",
}

REGION_KEYWORDS = {
    "四川": "四川",
    "成都": "成都",
    "绵阳": "绵阳",
    "德阳": "德阳",
    "南充": "南充",
    "宜宾": "宜宾",
    "泸州": "泸州",
    "乐山": "乐山",
    "自贡": "自贡",
    "富顺": "富顺",
    "达州": "达州",
    "广元": "广元",
    "遂宁": "遂宁",
    "内江": "内江",
    "资阳": "资阳",
    "眉山": "眉山",
    "雅安": "雅安",
}

TENDER_QUERY_EXPANSIONS = [
    ("合理用药", ["合理用药监测 系统", "合理用药 软件", "合理用药 信息系统", "合理用药信息支持系统网络版"]),
    ("合理用药", ["云药房 区域审方", "区域审方中心 系统", "审方中心 系统"]),
    ("审方", ["前置审方 系统", "处方审核 系统", "药师审方", "审方系统升级"]),
    ("前置审方", ["审方系统", "处方审核 系统", "药师审方干预"]),
    ("区域审方", ["区域审方中心 系统", "审方中心 系统", "云药房 区域审方"]),
    ("云药房", ["云药房 系统", "云药房 区域审方", "县域医共体 云药房"]),
    ("临床药学", ["临床药学 管理系统", "药事管理 系统", "处方点评 系统"]),
    ("药事", ["药事管理 系统", "处方点评 系统", "合理用药监测"]),
    ("智慧医院", ["智慧医院 药房 审方", "智慧医院 合理用药", "智慧医院 药学"]),
]

SOURCE_SITES = [
    {
        "name": "综合招采搜索",
        "domain": "aggregated",
        "search_url": "https://www.so.com/s?q={query}",
    },
    {
        "name": "四川政府采购网",
        "domain": "ccgp-sichuan.gov.cn",
        "search_url": "https://www.baidu.com/s?wd=site%3Accgp-sichuan.gov.cn+{query}",
    },
    {
        "name": "四川省公共资源交易信息网",
        "domain": "ggzyjy.sc.gov.cn",
        "search_url": "https://www.baidu.com/s?wd=site%3Aggzyjy.sc.gov.cn+{query}",
    },
    {
        "name": "四川省卫生健康委员会",
        "domain": "wsjkw.sc.gov.cn",
        "search_url": "https://www.baidu.com/s?wd=site%3Awsjkw.sc.gov.cn+{query}",
    },
    {
        "name": "中国政府采购网",
        "domain": "ccgp.gov.cn",
        "search_url": "https://search.ccgp.gov.cn/bxsearch?searchtype=1&page_index=1&bidSort=0&buyerName=&projectId=&pinMu=0&bidType=0&dbselect=bidx&kw={query}&start_time=&end_time=&timeType=6&displayZone=&zoneId=&pppStatus=0&agentName=",
    },
]


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

SEARCH_TEMPLATES = [
    "site:ccgp-sichuan.gov.cn {query}",
    "site:ggzyjy.sc.gov.cn {query}",
    "site:wsjkw.sc.gov.cn {query}",
    "site:ccgp.gov.cn 四川 {query}",
]

AGGREGATED_SEARCH_TEMPLATES = [
    "{query}",
]


PRODUCTS = {
    "pass": {
        "aliases": ["pass", "passv4", "合理用药", "合理用药监测"],
        "title": "PASS合理用药监测系统 V4 参数",
        "source": "全产品参数汇总/pass pr adr mcdex 技术参数.docx",
        "start": 4,
        "end": 41,
    },
    "pr": {
        "aliases": ["pr", "前置审方", "审方", "药师审方"],
        "title": "PASS PR药师审方干预系统 V1 参数",
        "source": "全产品参数汇总/pass pr adr mcdex 技术参数.docx",
        "start": 44,
        "end": 73,
    },
    "mcdex": {
        "aliases": ["mcdex", "用药信息", "信息支持", "合理用药信息支持"],
        "title": "MCDEX NET合理用药信息支持系统 V3 参数",
        "source": "MCDEX 完整版-招标参数20241108.docx",
        "start": 4,
        "end": 67,
    },
    "pa": {
        "aliases": ["pa", "pav3", "pav", "临床药学", "处方点评"],
        "title": "PASS PA临床药学管理系统 V3 参数",
        "source": "PAV3招标参数（精简版，不含抗肿瘤增值包）20220805.docx",
        "start": 4,
        "end": 59,
    },
    "ipc": {
        "aliases": ["ipc", "住院监护", "住院药学监护", "药学监护"],
        "title": "PASS住院药学监护系统参数",
        "source": "住院监护系统功能参数.docx",
        "start": 3,
        "end": 71,
    },
    "vbp": {
        "aliases": ["vbp", "集采", "集采系统", "集采药品管控"],
        "title": "PASS集采药品智能管控系统参数",
        "source": "集采系统.docx",
        "start": 3,
        "end": 29,
    },
    "disease": {
        "aliases": ["disease", "疾病", "疾病诊疗", "诊疗支持"],
        "title": "美康疾病诊疗支持系统参数",
        "source": "vbp/兴文县医共体【PIP2.0】PASSV4标准＋疾病+抗菌、PA标准+抗网+电子、PR、MCDEX基础库、疾病诊疗-招标参数20260319.docx",
        "start": 221,
        "end": 244,
    },
    "double_center": {
        "aliases": ["双中心", "云药房", "审方中心", "中心药房", "集中审方"],
        "title": "中心云药房和集中云审方中心建设方案",
        "source": "",
        "start": 0,
        "end": 0,
    },
}


SCHEMES = {
    "pass": {
        "title": "PASS合理用药监测系统 V4 建设方案",
        "source_key": "all_products",
        "ranges": [(153, 158), (159, 162), (258, 312)],
    },
    "pr": {
        "title": "PASS PR药师审方干预系统 V1 建设方案",
        "source_key": "all_products",
        "ranges": [(153, 158), (162, 165), (312, 360)],
    },
    "mcdex": {
        "title": "MCDEX NET合理用药信息支持系统 V3 建设方案",
        "source_key": "all_products",
        "ranges": [(153, 158), (165, 167), (360, 385)],
    },
    "pa": {
        "title": "PASS PA临床药学管理系统 V3 建设方案",
        "source_key": "all_products",
        "ranges": [(153, 158), (167, 169), (190, 258)],
    },
    "disease": {
        "title": "美康疾病诊疗支持系统介绍",
        "source_key": "disease",
        "ranges": [(0, 18)],
    },
    "double_center": {
        "title": "中心云药房和集中云审方中心建设方案",
        "source_key": "double_center",
        "ranges": [(0, 364)],
    },
}


def load_corpus():
    with CORPUS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_construction_sources():
    if not CONSTRUCTION_PATH.exists():
        return {}
    with CONSTRUCTION_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


CORPUS = load_corpus()
CONSTRUCTION_SOURCES = load_construction_sources()


def find_doc(source_name):
    matches = [
        item
        for item in CORPUS
        if item.get("path", "").endswith(source_name) and "::" not in item.get("path", "")
    ]
    if not matches:
        matches = [item for item in CORPUS if item.get("path", "").endswith(source_name)]
    if not matches:
        raise FileNotFoundError(source_name)
    return matches[0]


def clean_lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def resolve_product(command):
    raw = (command or "").strip().lower()
    for key, product in PRODUCTS.items():
        if raw == key:
            return key
        if raw in [alias.lower() for alias in product["aliases"]]:
            return key
    for key, product in PRODUCTS.items():
        if any(alias.lower() in raw for alias in product["aliases"]):
            return key
    return None


def resolve_products(command):
    raw = (command or "").strip()
    if not raw:
        return []
    tokens = [item for item in re.split(r"[\s,，、+＋/／;；]+", raw) if item]
    if len(tokens) <= 1:
        product = resolve_product(raw)
        return [product] if product else []

    resolved = []
    for token in tokens:
        product = resolve_product(token)
        if product and product not in resolved:
            resolved.append(product)
    return resolved


def product_lines(product_key):
    product = PRODUCTS[product_key]
    doc = find_doc(product["source"])
    lines = clean_lines(doc.get("text", ""))
    selected = lines[product["start"] : product["end"]]
    selected = [line for line in selected if not re.fullmatch(r"\d+", line)]
    selected = [line for line in selected if line not in {"序号", "子项", "详细要求"}]
    normalized = []
    index = 0
    while index < len(selected):
        line = selected[index]
        if line == "▲妊娠哺乳" and index + 1 < len(selected) and selected[index + 1] == "用药":
            normalized.append("▲妊娠哺乳用药")
            index += 2
            continue
        normalized.append(line)
        index += 1
    selected = normalized
    return selected, doc.get("path", product["source"])


def scheme_lines(product_key):
    scheme = SCHEMES[product_key]
    source = CONSTRUCTION_SOURCES[scheme["source_key"]]
    lines = source["lines"]
    selected = []
    for start, end in scheme["ranges"]:
        selected.extend(lines[start:end])
    return selected, source["source"]


def paragraph(text="", style=None):
    escaped = html.escape(text)
    ppr = ""
    if style:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
    return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{escaped}</w:t></w:r></w:p>'


def table_cell(text, width, bold=False):
    escaped = html.escape(text)
    bold_xml = "<w:b/>" if bold else ""
    return (
        f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr>'
        f'<w:p><w:r><w:rPr>{bold_xml}</w:rPr>'
        f'<w:t xml:space="preserve">{escaped}</w:t></w:r></w:p></w:tc>'
    )


def table_row(cells, bold=False):
    widths = [900, 2600, 6800]
    return "<w:tr>" + "".join(table_cell(cell, widths[index], bold) for index, cell in enumerate(cells)) + "</w:tr>"


def table(rows):
    borders = (
        '<w:tblPr><w:tblW w:w="0" w:type="auto"/>'
        '<w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="000000"/></w:tblBorders></w:tblPr>'
    )
    header = table_row(["序号", "子项", "详细要求"], True)
    return "<w:tbl>" + borders + header + "".join(table_row(row) for row in rows) + "</w:tbl>"


def is_parameter_heading(line):
    if line.endswith(("。", "；", ";", "：", ":")):
        return False
    if line.endswith("功能要求"):
        return True
    return (
        len(line) <= 24
        and not re.match(r"^[（(]?\d|^、|^“|^应|^可|^用户|^其中|^所有|^提供|^支持", line)
    )


def parameter_rows(lines):
    rows = []
    current = None
    details = []
    for line in lines:
        if is_parameter_heading(line):
            if current is not None:
                rows.append([str(len(rows) + 1), current, "\n".join(details)])
            current = line
            details = []
        else:
            if current is None:
                current = "技术要求"
            details.append(line)
    if current is not None:
        rows.append([str(len(rows) + 1), current, "\n".join(details)])
    return rows


def package_docx(body):
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>'
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" '
        'w:right="1440" w:bottom="1440" w:left="1440" w:header="720" '
        'w:footer="720" w:gutter="0"/></w:sectPr></w:body></w:document>'
    )

    styles_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/><w:rPr><w:rFonts w:ascii="宋体" w:eastAsia="宋体"/><w:sz w:val="21"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:qFormat/><w:pPr><w:jc w:val="center"/><w:spacing w:after="240"/></w:pPr><w:rPr><w:rFonts w:ascii="宋体" w:eastAsia="宋体"/><w:b/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:before="160" w:after="80"/></w:pPr><w:rPr><w:rFonts w:ascii="宋体" w:eastAsia="宋体"/><w:b/><w:sz w:val="24"/></w:rPr></w:style>
</w:styles>"""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"""
    doc_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>"""

    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/_rels/document.xml.rels", doc_rels)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/styles.xml", styles_xml)
    return output.getvalue()


def make_docx(title, lines):
    body = [paragraph(title, "Title")]
    for line in lines:
        is_heading = (
            len(line) <= 24
            and not re.match(r"^[（(]?\d|^▲|^、|^“|^系统|^应|^可|^用户|^其中|^所有", line)
        )
        body.append(paragraph(line, "Heading2" if is_heading else None))
    return package_docx(body)


def make_parameter_docx(product_key):
    if product_key not in ["pass", "pa", "pr", "mcdex", "ipc", "vbp", "disease"]:
        raise ValueError("该产品暂无功能参数文档")
    lines, _source = product_lines(product_key)
    body = [paragraph("技术参数要求", "Title"), table(parameter_rows(lines))]
    return package_docx(body)


def make_parameter_bundle_docx(product_keys):
    valid = ["pass", "pa", "pr", "mcdex", "ipc", "vbp", "disease"]
    for product_key in product_keys:
        if product_key not in valid:
            raise ValueError("该产品暂无功能参数文档")
    body = [paragraph("技术参数要求", "Title")]
    for index, product_key in enumerate(product_keys):
        if len(product_keys) > 1:
            body.append(paragraph(PRODUCTS[product_key]["title"].replace(" 参数", ""), "Heading2"))
        lines, _source = product_lines(product_key)
        body.append(table(parameter_rows(lines)))
        if index != len(product_keys) - 1:
            body.append(paragraph(""))
    return package_docx(body)


def make_scheme_docx(product_key):
    if product_key not in SCHEMES:
        raise ValueError("该产品暂无建设方案文档")
    scheme = SCHEMES[product_key]
    lines, _source = scheme_lines(product_key)
    return make_docx(scheme["title"], lines)


def normalize_space(text):
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def strip_tags(text):
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_space(text)


def fetch_url(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(request, timeout=SEARCH_TIMEOUT) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="ignore")


def extract_result_blocks(page_html):
    blocks = re.findall(r'<li class="b_algo"[\s\S]*?</li>', page_html, flags=re.I)
    if blocks:
        return blocks
    return re.findall(r'<div class="result[\s\S]*?</div>', page_html, flags=re.I)


def extract_so_result_items(page_html):
    items = []
    blocks = re.findall(
        r'<li[^>]+class="[^"]*res-list[^"]*"[\s\S]*?</li>',
        page_html,
        flags=re.I,
    )
    for block in blocks:
        h3_match = re.search(r"<h3[^>]*>([\s\S]*?)</h3>", block, flags=re.I)
        link_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', h3_match.group(1), flags=re.I) if h3_match else None
        if not link_match:
            continue
        url = html.unescape(link_match.group(1))
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith("/"):
            url = "https://www.so.com" + url
        title = strip_tags(link_match.group(2))
        text = strip_tags(block)
        snippet = text.replace(title, "", 1).strip()
        domain_match = re.search(r"((?:[a-z0-9-]+\.)+[a-z]{2,})(?:\s|$)", snippet, flags=re.I)
        display_domain = domain_match.group(1) if domain_match else urllib.parse.urlparse(url).netloc
        if title and url.startswith("http"):
            items.append(
                {
                    "title": title,
                    "url": url,
                    "source": display_domain or "综合招采搜索",
                    "snippet": snippet,
                }
            )
    return items


def source_name_for_url(url):
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    for source in SOURCE_SITES:
        if source["domain"] in host:
            return source["name"]
    return host or "未知来源"


def source_allowed(url, source_name, selected_sources):
    if not selected_sources:
        return True
    if "aggregated" in selected_sources and (
        "so.com" in urllib.parse.urlparse(url).netloc.lower()
        or any(domain in (source_name or "") for domain in ["bidcenter", "zhaobiao", "okcis", "zhiliaobiaoxun", "qianlima"])
    ):
        return True
    host = urllib.parse.urlparse(url).netloc.lower()
    return any(domain in host or domain in (source_name or "") for domain in selected_sources if domain != "aggregated")


def load_tender_seed_results():
    if not TENDER_SEED_PATH.exists():
        return []
    with TENDER_SEED_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def compact_text(text):
    return re.sub(r"\s+", "", normalize_space(text)).lower()


def tokens_for_match(text):
    text = normalize_space(text)
    pieces = re.split(r"[\s,，、/|]+", text)
    tokens = []
    for piece in pieces:
        piece = piece.strip()
        if len(piece) >= 2 and piece not in ["四川", "医院", "系统", "软件", "招标", "采购", "公告"]:
            tokens.append(piece)
    return tokens


def seed_matches(item, keyword, region, stage, buyer):
    haystack = compact_text(" ".join([item.get("title", ""), item.get("snippet", ""), item.get("region", "")]))
    keyword_text = normalize_space(keyword) or DEFAULT_TENDER_KEYWORDS
    buyer_text = normalize_space(buyer)
    query_tokens = tokens_for_match(keyword_text)
    if buyer_text:
        query_tokens.extend(tokens_for_match(buyer_text))

    strong_tokens = [
        "合理用药",
        "美康",
        "前置审方",
        "处方审核",
        "药学监护",
        "云药房",
        "区域审方",
        "审方中心",
        "县域医共体",
        "智慧医院",
        "临床药学",
        "药事管理",
        "处方点评",
    ]
    has_domain_hit = any(compact_text(token) in haystack for token in strong_tokens)
    token_hits = sum(1 for token in query_tokens if compact_text(token) in haystack)
    compact_query = compact_text(keyword_text)
    has_title_hit = len(compact_query) >= 8 and compact_query in haystack

    if region and region != "四川" and compact_text(region) not in haystack:
        return False
    if stage != "all" and STAGE_KEYWORDS.get(stage):
        stage_words = tokens_for_match(STAGE_KEYWORDS[stage])
        if not any(compact_text(word) in haystack for word in stage_words):
            return False
    return has_title_hit or has_domain_hit or token_hits >= 2


def seed_date_allowed(item, date_range):
    start, end, _ = date_range_window(date_range)
    if not start or not end:
        return True
    item_date = item.get("date", "")
    if not item_date:
        return True
    try:
        parsed_date = date.fromisoformat(item_date)
    except ValueError:
        return True
    return start <= parsed_date <= end


def search_seed_tenders(keyword, selected_sources, date_range, region, stage, buyer, seen):
    if selected_sources and "aggregated" not in selected_sources:
        return []
    results = []
    for item in load_tender_seed_results():
        if not seed_date_allowed(item, date_range):
            continue
        if not seed_matches(item, keyword, region, stage, buyer):
            continue
        clean_url = item.get("url", "")
        dedupe_key = clean_url + item.get("title", "")
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        results.append(
            {
                "title": item.get("title", ""),
                "url": clean_url,
                "source": item.get("source", "线索库"),
                "stage": item.get("stage") or infer_stage(item.get("title", ""), item.get("snippet", "")),
                "date": item.get("date", ""),
                "query": "本地线索库",
                "snippet": item.get("snippet", ""),
            }
        )
    return results


def date_range_window(date_range):
    if date_range != "month":
        return None, None, "不限时间"
    end = date.today()
    start = end - timedelta(days=30)
    return start, end, f"最近一个月（{start.isoformat()} 至 {end.isoformat()}）"


def with_date_terms(query, date_range):
    start, end, _ = date_range_window(date_range)
    if not start or not end:
        return query
    return f"{query} after:{start.isoformat()} before:{(end + timedelta(days=1)).isoformat()}"


def build_tender_query(keyword, region=DEFAULT_TENDER_REGION, stage=DEFAULT_TENDER_STAGE, buyer=""):
    parts = []
    raw_keyword = normalize_space(keyword) or DEFAULT_TENDER_KEYWORDS
    region_text = REGION_KEYWORDS.get(region, normalize_space(region))
    known_regions = [name for name in REGION_KEYWORDS if name and name != "四川"] + ["四川", "德阳", "内江"]
    keyword_has_region = any(name in raw_keyword for name in known_regions)
    if region_text and not keyword_has_region:
        parts.append(region_text)
    parts.append(raw_keyword)
    stage_text = STAGE_KEYWORDS.get(stage, "")
    if stage_text:
        parts.append(stage_text)
    buyer_text = normalize_space(buyer)
    if buyer_text:
        parts.append(buyer_text)
    return normalize_space(" ".join(parts))


def expanded_tender_queries(keyword, region=DEFAULT_TENDER_REGION, stage=DEFAULT_TENDER_STAGE, buyer=""):
    base_keyword = normalize_space(keyword) or DEFAULT_TENDER_KEYWORDS
    variants = [base_keyword]
    compact_keyword = re.sub(r"\s+", "", base_keyword)
    if compact_keyword and compact_keyword != base_keyword:
        variants.append(compact_keyword)
    for trigger, replacements in TENDER_QUERY_EXPANSIONS:
        if trigger in base_keyword:
            variants.extend(replacements)
    if "合理用药" in base_keyword and "审方" not in base_keyword:
        variants.extend(["前置审方 系统", "处方审核 系统", "药事管理 系统"])

    queries = []
    seen = set()
    for variant in variants:
        query = build_tender_query(variant, region, stage, buyer)
        if query in seen:
            continue
        seen.add(query)
        queries.append(query)
        if len(queries) >= MAX_QUERY_VARIANTS:
            break
    return queries


def infer_stage(title, snippet):
    text = f"{title} {snippet}"
    if any(word in text for word in ["中标", "成交", "结果公告"]):
        return "结果"
    if any(word in text for word in ["采购意向", "需求公示", "征求意见"]):
        return "意向"
    if any(word in text for word in ["更正", "变更", "澄清"]):
        return "变更"
    if any(word in text for word in ["招标", "采购", "磋商", "谈判", "询价"]):
        return "公告"
    return "线索"


def search_tenders(
    keyword,
    selected_sources=None,
    date_range=DEFAULT_TENDER_DATE_RANGE,
    region=DEFAULT_TENDER_REGION,
    stage=DEFAULT_TENDER_STAGE,
    buyer="",
):
    search_queries = expanded_tender_queries(keyword, region, stage, buyer)
    selected_sources = selected_sources or [source["domain"] for source in SOURCE_SITES]
    results = []
    seen = set()
    results.extend(search_seed_tenders(keyword, selected_sources, date_range, region, stage, buyer, seen))
    if len(results) >= SEED_FIRST_MIN_RESULTS:
        return results[:MAX_SEARCH_RESULTS]
    if len(results) >= MAX_SEARCH_RESULTS:
        return results[:MAX_SEARCH_RESULTS]
    official_sources_selected = any(
        source in selected_sources
        for source in ["ccgp-sichuan.gov.cn", "ggzyjy.sc.gov.cn", "wsjkw.sc.gov.cn", "ccgp.gov.cn"]
    )

    for effective_query in search_queries:
        if "aggregated" in selected_sources:
            for template in AGGREGATED_SEARCH_TEMPLATES:
                query = template.format(query=effective_query)
                search_url = "https://www.so.com/s?q=" + urllib.parse.quote(query)
                try:
                    page = fetch_url(search_url)
                except Exception:
                    continue
                for item in extract_so_result_items(page):
                    if not source_allowed(item["url"], item["source"], selected_sources):
                        continue
                    clean_url = urllib.parse.urlunparse(urllib.parse.urlparse(item["url"])._replace(fragment=""))
                    dedupe_key = clean_url + item["title"]
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    results.append(
                        {
                            "title": item["title"],
                            "url": clean_url,
                            "source": item["source"] or "综合招采搜索",
                            "stage": infer_stage(item["title"], item["snippet"]),
                            "query": effective_query,
                            "snippet": item["snippet"],
                        }
                    )
                    if len(results) >= MAX_SEARCH_RESULTS:
                        return results
                time.sleep(0.12)

        if not official_sources_selected:
            continue

        for template in SEARCH_TEMPLATES:
            query = with_date_terms(template.format(query=effective_query), date_range)
            search_url = "https://www.bing.com/search?q=" + urllib.parse.quote(query)
            try:
                page = fetch_url(search_url)
            except Exception:
                continue

            for block in extract_result_blocks(page):
                link_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', block, flags=re.I)
                if not link_match:
                    continue
                url = html.unescape(link_match.group(1))
                title = strip_tags(link_match.group(2))
                if not url.startswith("http") or not title:
                    continue
                parsed = urllib.parse.urlparse(url)
                source_name = source_name_for_url(url)
                if not source_allowed(url, source_name, selected_sources):
                    continue
                clean_url = urllib.parse.urlunparse(parsed._replace(fragment=""))
                if clean_url in seen:
                    continue
                seen.add(clean_url)

                snippet_match = re.search(r'<p[^>]*>([\s\S]*?)</p>', block, flags=re.I)
                snippet = strip_tags(snippet_match.group(1)) if snippet_match else ""
                results.append(
                    {
                        "title": title,
                        "url": clean_url,
                        "source": source_name,
                        "stage": infer_stage(title, snippet),
                        "query": effective_query,
                        "snippet": snippet,
                    }
                )
                if len(results) >= MAX_SEARCH_RESULTS:
                    return results
            time.sleep(0.15)
    return results


def tender_search_links(
    keyword,
    date_range=DEFAULT_TENDER_DATE_RANGE,
    region=DEFAULT_TENDER_REGION,
    stage=DEFAULT_TENDER_STAGE,
    buyer="",
):
    keyword = build_tender_query(keyword, region, stage, buyer)
    start, end, _ = date_range_window(date_range)
    keyword_with_date = with_date_terms(keyword, date_range)
    encoded = urllib.parse.quote(keyword)
    encoded_with_date = urllib.parse.quote(keyword_with_date)
    ccgp_start = start.strftime("%Y:%m:%d") if start else ""
    ccgp_end = end.strftime("%Y:%m:%d") if end else ""
    baidu_date = ""
    if start and end:
        baidu_date = "&gpc=stf%3D{}%2C{}%7Cstftype%3D1".format(
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
        )
    return [
        {
            "name": "综合招采搜索",
            "url": "https://www.so.com/s?q={}".format(encoded_with_date),
        },
        {
            "name": "四川政府采购网",
            "url": "https://www.baidu.com/s?wd=site%3Accgp-sichuan.gov.cn+{}{}".format(
                encoded_with_date,
                baidu_date,
            ),
        },
        {
            "name": "四川省公共资源交易信息网",
            "url": "https://www.baidu.com/s?wd=site%3Aggzyjy.sc.gov.cn+{}{}".format(
                encoded_with_date,
                baidu_date,
            ),
        },
        {
            "name": "四川省卫生健康委员会",
            "url": "https://www.baidu.com/s?wd=site%3Awsjkw.sc.gov.cn+{}{}".format(
                encoded_with_date,
                baidu_date,
            ),
        },
        {
            "name": "中国政府采购网",
            "url": (
                "https://search.ccgp.gov.cn/bxsearch?searchtype=1&page_index=1&bidSort=0"
                "&buyerName=&projectId=&pinMu=0&bidType=0&dbselect=bidx&kw={}"
                "&start_time={}&end_time={}&timeType=6&displayZone=&zoneId=&pppStatus=0&agentName="
            ).format(encoded, ccgp_start, ccgp_end),
        },
    ]


def json_response(data):
    return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")


def write_env_config(values):
    lines = []
    env_path = BASE_DIR / ".env"
    existing = {}
    if env_path.exists():
        with env_path.open("r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    key, value = line.rstrip("\n").split("=", 1)
                    existing[key] = value
    existing.update({key: value for key, value in values.items() if value})
    for key in ["PUSHPLUS_TOKEN", "TENDER_PAGE_URL", "WECOM_WEBHOOK_URL", "SERVER_CHAN_SENDKEY"]:
        if key in existing:
            lines.append(f"{key}={existing[key]}")
    with env_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def local_network_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>合理用药资料工具</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f6f7f9; color: #1f2933; }
    main { max-width: 920px; margin: 0 auto; padding: 28px 18px; }
    h1 { font-size: 24px; margin: 0 0 10px; }
    h2 { font-size: 18px; margin: 0 0 8px; }
    p { line-height: 1.65; margin: 8px 0; }
    .panel { background: #fff; border: 1px solid #dde2e8; border-radius: 8px; padding: 18px; margin-top: 18px; }
    label { display: block; font-size: 14px; margin-bottom: 8px; color: #52616f; }
    input { width: 100%; height: 46px; border: 1px solid #b9c2cc; border-radius: 6px; padding: 0 12px; font-size: 17px; }
    button { width: 100%; height: 46px; margin-top: 12px; border: 0; border-radius: 6px; background: #1769aa; color: #fff; font-size: 16px; font-weight: 600; }
    .chips { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 12px; }
    .chips button { margin: 0; background: #e8eef5; color: #1f2933; font-weight: 500; }
    .hint { font-size: 14px; color: #66788a; }
    .nav { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
    .nav a { display: inline-flex; align-items: center; min-height: 38px; padding: 0 14px; border-radius: 6px; color: #174a72; background: #e8eef5; text-decoration: none; font-weight: 600; }
    .nav a.active { background: #1769aa; color: #fff; }
    .type-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 0 0 12px; }
    .type-row label { display: flex; align-items: center; justify-content: center; min-height: 42px; border: 1px solid #ccd5df; border-radius: 6px; margin: 0; color: #1f2933; }
    .type-row input { width: auto; height: auto; margin-right: 6px; }
    .product-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 12px; }
    .product-grid label { display: flex; align-items: center; min-height: 40px; border: 1px solid #ccd5df; border-radius: 6px; padding: 0 10px; margin: 0; color: #1f2933; background: #fbfcfd; }
    .product-grid input { width: auto; height: auto; margin-right: 8px; }
  </style>
</head>
<body>
  <main>
    <h1>合理用药资料工具</h1>
    <p class="hint">生成标准产品参数和建设方案，也可以搜四川医院、卫健委、政府采购等公开招标原文。</p>
    <nav class="nav">
      <a class="active" href="/">产品资料</a>
      <a href="/tenders">招标信息搜索</a>
    </nav>
    <section class="panel">
      <h2>产品资料 Word 生成器</h2>
      <form action="/generate" method="get" onsubmit="return prepareProducts()">
        <div class="type-row">
          <label><input type="radio" name="doc_type" value="parameter" checked />功能参数</label>
          <label><input type="radio" name="doc_type" value="scheme" />建设方案</label>
        </div>
        <label for="product">产品指令</label>
        <input id="product" name="product" placeholder="例如：pass pa pr，或 ipc vbp 疾病诊疗" autocomplete="off" />
        <div class="product-grid">
          <label><input type="checkbox" value="pass" />PASS</label>
          <label><input type="checkbox" value="pa" />PA</label>
          <label><input type="checkbox" value="pr" />PR</label>
          <label><input type="checkbox" value="mcdex" />MCDEX</label>
          <label><input type="checkbox" value="ipc" />IPC</label>
          <label><input type="checkbox" value="vbp" />VBP</label>
          <label><input type="checkbox" value="疾病诊疗" />疾病诊疗</label>
        </div>
        <button type="submit">生成 Word 文档</button>
      </form>
      <div class="chips">
        <button type="button" onclick="go('pass')">PASS</button>
        <button type="button" onclick="go('pa')">PA</button>
        <button type="button" onclick="go('pr')">PR</button>
        <button type="button" onclick="go('mcdex')">MCDEX</button>
        <button type="button" onclick="go('ipc')">IPC</button>
        <button type="button" onclick="go('vbp')">VBP</button>
        <button type="button" onclick="go('疾病诊疗')">疾病诊疗</button>
        <button type="button" onclick="goScheme('双中心')">双中心</button>
      </div>
    </section>
  </main>
  <script>
    function go(product) {
      location.href = "/generate?product=" + encodeURIComponent(product);
    }
    function goScheme(product) {
      location.href = "/generate?doc_type=scheme&product=" + encodeURIComponent(product);
    }
    function prepareProducts() {
      var input = document.getElementById("product");
      var checked = Array.from(document.querySelectorAll(".product-grid input:checked")).map(function(item) {
        return item.value;
      });
      if (checked.length > 0) {
        input.value = checked.join(" ");
      }
      return true;
    }
  </script>
</body>
</html>
"""


TENDERS_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>招标线索工作台</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #eef2f6; color: #17202a; }
    a { color: #145f8f; text-decoration: none; }
    button, input, select { font: inherit; }
    .shell { min-height: 100vh; display: grid; grid-template-columns: 236px minmax(0, 1fr); }
    .sidebar { background: #14212d; color: #dce7ef; padding: 22px 16px; }
    .brand { font-size: 19px; font-weight: 750; margin-bottom: 22px; color: #fff; }
    .nav a { display: flex; min-height: 40px; align-items: center; padding: 0 12px; border-radius: 6px; color: #c8d5df; margin-bottom: 6px; }
    .nav a.active { background: #1f6f9e; color: #fff; }
    .watch { margin-top: 24px; padding-top: 18px; border-top: 1px solid #2b3b48; }
    .watch h2 { font-size: 13px; color: #91a6b6; margin: 0 0 10px; font-weight: 600; }
    .watch button { width: 100%; min-height: 34px; border: 1px solid #355368; border-radius: 6px; background: #1c2c3a; color: #e6f0f7; margin: 0 0 8px; cursor: pointer; }
    .content { padding: 22px; }
    .topbar { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 16px; }
    h1 { font-size: 24px; margin: 0 0 6px; }
    .hint { color: #667887; font-size: 14px; line-height: 1.6; margin: 0; }
    .layout { display: grid; grid-template-columns: 280px minmax(0, 1fr) 260px; gap: 14px; align-items: start; }
    .panel { background: #fff; border: 1px solid #d8e0e7; border-radius: 8px; padding: 16px; box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04); }
    .panel h2 { font-size: 15px; margin: 0 0 12px; }
    label { display: block; font-size: 13px; color: #536675; margin: 12px 0 6px; }
    input[type="text"], select { width: 100%; min-height: 42px; border: 1px solid #bdc8d2; border-radius: 6px; padding: 0 10px; background: #fff; color: #17202a; }
    .source-list label { display: flex; align-items: center; gap: 8px; min-height: 34px; margin: 4px 0; color: #243442; }
    .primary { width: 100%; min-height: 44px; margin-top: 14px; border: 0; border-radius: 6px; background: #1769aa; color: #fff; font-weight: 700; cursor: pointer; }
    .ghost { border: 1px solid #cbd5df; border-radius: 6px; min-height: 34px; padding: 0 10px; background: #fff; color: #234052; cursor: pointer; }
    .search-card { margin-bottom: 14px; }
    .search-row { display: grid; grid-template-columns: minmax(0, 1fr) 120px; gap: 10px; }
    .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 12px; }
    .stat { border: 1px solid #e0e7ee; border-radius: 8px; padding: 10px; background: #f8fafc; }
    .stat strong { display: block; font-size: 20px; margin-bottom: 2px; }
    .stat span { color: #667887; font-size: 12px; }
    .toolbar { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; justify-content: space-between; margin-bottom: 10px; }
    .tag { display: inline-flex; align-items: center; min-height: 26px; padding: 0 8px; border-radius: 999px; background: #e9f2f8; color: #145f8f; font-size: 12px; font-weight: 700; }
    .result { border: 1px solid #dce4eb; border-radius: 8px; background: #fff; padding: 14px; margin-bottom: 10px; }
    .result h3 { margin: 0 0 8px; font-size: 17px; line-height: 1.45; }
    .meta { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; color: #607382; font-size: 13px; }
    .snippet { color: #34495a; font-size: 14px; line-height: 1.6; margin: 0; }
    .result-actions { display: flex; gap: 8px; margin-top: 12px; }
    .open { display: inline-flex; align-items: center; min-height: 34px; padding: 0 12px; border-radius: 6px; background: #1769aa; color: #fff; font-weight: 700; }
    .copy { display: inline-flex; align-items: center; min-height: 34px; padding: 0 12px; border: 1px solid #cbd5df; border-radius: 6px; color: #234052; background: #fff; }
    .quick-links { display: grid; gap: 8px; }
    .quick-links a { min-height: 36px; display: flex; align-items: center; padding: 0 10px; border: 1px solid #d8e0e7; border-radius: 6px; background: #f9fbfd; color: #234052; font-weight: 600; }
    .empty { border: 1px dashed #c7d2dd; border-radius: 8px; background: #f9fbfd; color: #667887; padding: 28px; text-align: center; }
    .summary-line { font-size: 13px; color: #667887; margin-top: 8px; }
    .query-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .query-pill { display: inline-flex; align-items: center; min-height: 24px; padding: 0 8px; border-radius: 999px; background: #eef4f8; color: #3f596b; font-size: 12px; }
    @media (max-width: 1080px) {
      .shell { grid-template-columns: 1fr; }
      .sidebar { display: none; }
      .layout { grid-template-columns: 1fr; }
    }
    @media (max-width: 720px) {
      .content { padding: 14px; }
      .topbar, .search-row { display: block; }
      .stats { grid-template-columns: 1fr; }
      .search-row button { width: 100%; margin-top: 10px; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">招标线索工作台</div>
      <nav class="nav">
        <a href="/">产品资料</a>
        <a class="active" href="/tenders">招标搜索</a>
      </nav>
      <div class="watch">
        <h2>常用订阅</h2>
        <button type="button" data-query="合理用药 软件系统">合理用药软件系统</button>
        <button type="button" data-query="前置审方 系统">前置审方系统</button>
        <button type="button" data-query="临床药学 管理系统">临床药学管理系统</button>
        <button type="button" data-query="药品不良反应 监测系统">不良反应监测</button>
      </div>
    </aside>
    <main class="content">
      <div class="topbar">
        <div>
          <h1>四川医疗招标线索</h1>
          <p class="hint">按近 30 天、项目阶段、地区和采购单位筛选，结果保留公开原文入口。</p>
        </div>
        <a class="ghost" href="/">返回产品资料</a>
      </div>

      <div class="layout">
        <aside class="panel">
          <h2>筛选条件</h2>
          <form id="searchForm">
            <label for="dateRange">时间范围</label>
            <select id="dateRange" name="date_range">
              <option value="month" selected>最近一个月</option>
              <option value="all">不限时间</option>
            </select>

            <label for="region">地区</label>
            <select id="region" name="region">
              <option selected>四川</option>
              <option>成都</option><option>绵阳</option><option>德阳</option><option>南充</option>
              <option>宜宾</option><option>泸州</option><option>乐山</option><option>自贡</option>
              <option>富顺</option><option>达州</option><option>广元</option><option>遂宁</option><option>内江</option>
              <option>资阳</option><option>眉山</option><option>雅安</option>
            </select>

            <label for="stage">项目阶段</label>
            <select id="stage" name="stage">
              <option value="all" selected>全部阶段</option>
              <option value="notice">招标/采购公告</option>
              <option value="intent">采购意向/需求公示</option>
              <option value="change">更正/变更公告</option>
              <option value="result">中标/成交结果</option>
            </select>

            <label for="buyer">采购单位关键词</label>
            <input id="buyer" name="buyer" type="text" placeholder="例如：人民医院 / 卫健委" />

              <label>信息来源</label>
            <div class="source-list">
              <label><input type="checkbox" name="source" value="aggregated" checked />综合招采搜索</label>
              <label><input type="checkbox" name="source" value="ccgp-sichuan.gov.cn" checked />四川政府采购网</label>
              <label><input type="checkbox" name="source" value="ggzyjy.sc.gov.cn" checked />公共资源交易</label>
              <label><input type="checkbox" name="source" value="wsjkw.sc.gov.cn" checked />四川卫健委</label>
              <label><input type="checkbox" name="source" value="ccgp.gov.cn" checked />中国政府采购网</label>
            </div>
            <button class="primary" type="submit">搜索线索</button>
          </form>
        </aside>

        <section>
          <div class="panel search-card">
            <label for="keyword">关键词</label>
            <div class="search-row">
              <input id="keyword" form="searchForm" name="keyword" type="text" value="医院 卫健委 合理用药 软件系统 招标" />
              <button class="primary" form="searchForm" type="submit">搜索</button>
            </div>
            <div class="stats">
              <div class="stat"><strong id="resultCount">0</strong><span>自动结果</span></div>
              <div class="stat"><strong id="sourceCount">5</strong><span>已选来源</span></div>
              <div class="stat"><strong id="dateLabel">近 30 天</strong><span>当前周期</span></div>
            </div>
            <div id="querySummary" class="summary-line">默认搜索四川地区近 30 天合理用药软件系统招标线索。</div>
            <div id="queryVariants" class="query-list"></div>
          </div>

          <div class="toolbar">
            <span class="tag">原文优先</span>
            <span id="status" class="hint"></span>
          </div>
          <div id="results" class="empty">点击搜索后展示线索卡片。</div>
        </section>

        <aside class="panel">
          <h2>官方站点直达</h2>
          <p class="hint">自动结果为空时，用这些入口继续查原文。</p>
          <div id="quickLinks" class="quick-links"></div>
        </aside>
      </div>
    </main>
  </div>
  <script>
    const form = document.getElementById("searchForm");
    const statusBox = document.getElementById("status");
    const resultsBox = document.getElementById("results");
    const quickLinks = document.getElementById("quickLinks");
    const resultCount = document.getElementById("resultCount");
    const sourceCount = document.getElementById("sourceCount");
    const dateLabel = document.getElementById("dateLabel");
    const querySummary = document.getElementById("querySummary");
    const queryVariants = document.getElementById("queryVariants");
    const keywordInput = document.getElementById("keyword");

    function escapeHtml(value) {
      return String(value || "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[char]));
    }

    function selectedSourceCount() {
      return form.querySelectorAll('input[name="source"]:checked').length;
    }

    function renderQuickLinks(links) {
      quickLinks.innerHTML = links.map((item) =>
        `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">${escapeHtml(item.name)}</a>`
      ).join("");
    }

    function renderResults(items) {
      if (!items.length) {
        resultsBox.className = "empty";
        resultsBox.innerHTML = "暂时没有自动抓到结果。右侧官方入口已按同一条件生成，可继续打开原文站点查询。";
        return;
      }
      resultsBox.className = "";
      resultsBox.innerHTML = items.map((item) => `
        <article class="result">
          <h3>${escapeHtml(item.title)}</h3>
          <div class="meta">
            <span>${escapeHtml(item.source)}</span>
            <span class="tag">${escapeHtml(item.stage || "线索")}</span>
            <span>${escapeHtml(item.date || "")}</span>
            <span>${escapeHtml(item.query || "")}</span>
          </div>
          <p class="snippet">${escapeHtml(item.snippet || "打开原文查看公告正文、采购人、预算金额和附件。")}</p>
          <div class="result-actions">
            <a class="open" href="${escapeHtml(item.url)}" target="_blank" rel="noopener">${escapeHtml((item.url || "").includes("so.com/s?q=") ? "查找原文" : "打开原文")}</a>
            <a class="copy" href="${escapeHtml(item.url)}" target="_blank" rel="noopener">查看链接</a>
          </div>
        </article>
      `).join("");
    }

    async function runSearch(event) {
      event && event.preventDefault();
      const params = new URLSearchParams(new FormData(form));
      statusBox.textContent = "正在搜索公开招标线索...";
      resultsBox.className = "empty";
      resultsBox.textContent = "正在获取公开网页结果。";
      sourceCount.textContent = selectedSourceCount();
      try {
        const response = await fetch("/api/tenders?" + params.toString());
        const data = await response.json();
        renderQuickLinks(data.quick_links || []);
        renderResults(data.results || []);
        resultCount.textContent = data.results.length;
        dateLabel.textContent = data.date_range === "month" ? "近 30 天" : "不限";
        querySummary.textContent = `搜索词：${data.effective_keyword}；${data.date_range_label}`;
        queryVariants.innerHTML = (data.query_variants || []).map((item) =>
          `<span class="query-pill">${escapeHtml(item)}</span>`
        ).join("");
        statusBox.textContent = `完成，找到 ${data.results.length} 条自动结果`;
      } catch (error) {
        statusBox.textContent = "搜索失败";
        resultsBox.textContent = "网络或目标站点暂时不可用。可以用右侧官方入口继续查。";
      }
    }

    document.querySelectorAll("[data-query]").forEach((button) => {
      button.addEventListener("click", () => {
        keywordInput.value = button.dataset.query;
        runSearch();
      });
    });

    form.addEventListener("submit", runSearch);
    sourceCount.textContent = selectedSourceCount();
    runSearch();
  </script>
</body>
</html>
"""


PUSHPLUS_SETUP_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PushPlus 配置</title>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #eef2f6; color: #17202a; }
    main { max-width: 560px; margin: 0 auto; padding: 22px 16px; }
    .panel { background: #fff; border: 1px solid #d8e0e7; border-radius: 8px; padding: 18px; }
    h1 { font-size: 22px; margin: 0 0 10px; }
    p { color: #536675; line-height: 1.7; }
    label { display: block; font-size: 14px; color: #536675; margin: 14px 0 6px; }
    input { width: 100%; min-height: 44px; border: 1px solid #bdc8d2; border-radius: 6px; padding: 0 10px; font-size: 16px; }
    button { width: 100%; min-height: 44px; margin-top: 16px; border: 0; border-radius: 6px; background: #1769aa; color: #fff; font-size: 16px; font-weight: 700; }
    .hint { font-size: 13px; color: #667887; }
    .ok { background: #e8f6ed; border: 1px solid #addfc0; color: #166534; border-radius: 8px; padding: 12px; margin-bottom: 14px; }
  </style>
</head>
<body>
  <main>
    <div class="panel">
      {message}
      <h1>PushPlus 个人微信提醒</h1>
      <p>把 PushPlus Token 粘贴到下面，保存后运行监控脚本，有新增招标线索时会推送到你的微信。</p>
      <form method="post" action="/pushplus-setup">
        <label for="token">PushPlus Token</label>
        <input id="token" name="pushplus_token" placeholder="粘贴你的 PushPlus Token" autocomplete="off" />
        <label for="page">查看页面地址</label>
        <input id="page" name="tender_page_url" value="{page_url}" />
        <button type="submit">保存配置</button>
      </form>
      <p class="hint">这个配置页只适合在你自己的本地网络或可信云端使用，不要把地址发到公开群。</p>
    </div>
  </main>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, status, content_type, data, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if filename:
            quoted = urllib.parse.quote(filename)
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quoted}")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ["/", "/index.html"]:
            self.send_bytes(200, "text/html; charset=utf-8", INDEX_HTML.encode("utf-8"))
            return
        if parsed.path in ["/tenders", "/wechat"]:
            self.send_bytes(200, "text/html; charset=utf-8", TENDERS_HTML.encode("utf-8"))
            return
        if parsed.path == "/pushplus-setup":
            host = self.headers.get("Host", f"127.0.0.1:{PORT}")
            page_url = f"http://{host}/wechat"
            html_text = PUSHPLUS_SETUP_HTML.replace("{message}", "").replace("{page_url}", html.escape(page_url))
            self.send_bytes(200, "text/html; charset=utf-8", html_text.encode("utf-8"))
            return
        if parsed.path == "/api/tenders":
            query = urllib.parse.parse_qs(parsed.query)
            keyword = query.get("keyword", [DEFAULT_TENDER_KEYWORDS])[0]
            sources = query.get("source", [])
            date_range = query.get("date_range", [DEFAULT_TENDER_DATE_RANGE])[0]
            region = query.get("region", [DEFAULT_TENDER_REGION])[0]
            stage = query.get("stage", [DEFAULT_TENDER_STAGE])[0]
            buyer = query.get("buyer", [""])[0]
            effective_keyword = build_tender_query(keyword, region, stage, buyer)
            query_variants = expanded_tender_queries(keyword, region, stage, buyer)
            results = search_tenders(keyword, sources, date_range, region, stage, buyer)
            _, _, date_range_label = date_range_window(date_range)
            payload = {
                "keyword": normalize_space(keyword) or DEFAULT_TENDER_KEYWORDS,
                "effective_keyword": effective_keyword,
                "query_variants": query_variants,
                "date_range": date_range,
                "date_range_label": date_range_label,
                "results": results,
                "quick_links": tender_search_links(keyword, date_range, region, stage, buyer),
            }
            self.send_bytes(200, "application/json; charset=utf-8", json_response(payload))
            return
        if parsed.path == "/generate":
            query = urllib.parse.parse_qs(parsed.query)
            product_input = query.get("product", [""])[0]
            product_key = resolve_product(product_input)
            product_keys = resolve_products(product_input)
            doc_type = query.get("doc_type", ["parameter"])[0]
            if not product_keys:
                message = "未识别产品指令。请输入 pass、pa、pr、mcdex、疾病诊疗或双中心。"
                self.send_bytes(400, "text/plain; charset=utf-8", message.encode("utf-8"))
                return
            try:
                if doc_type == "scheme":
                    product_key = product_keys[0]
                    data = make_scheme_docx(product_key)
                    title = SCHEMES[product_key]["title"]
                else:
                    data = make_parameter_bundle_docx(product_keys)
                    title = "技术参数要求" if len(product_keys) > 1 else PRODUCTS[product_keys[0]]["title"]
            except ValueError as exc:
                self.send_bytes(400, "text/plain; charset=utf-8", str(exc).encode("utf-8"))
                return
            filename = title.replace(" ", "") + ".docx"
            self.send_bytes(
                200,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                data,
                filename,
            )
            return
        self.send_bytes(404, "text/plain; charset=utf-8", "Not found".encode("utf-8"))

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/pushplus-setup":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8", errors="ignore")
            data = urllib.parse.parse_qs(body)
            token = data.get("pushplus_token", [""])[0].strip()
            page_url = data.get("tender_page_url", [""])[0].strip()
            if not token:
                message = '<div class="ok">请先填写 PushPlus Token。</div>'
            else:
                write_env_config({"PUSHPLUS_TOKEN": token, "TENDER_PAGE_URL": page_url})
                message = '<div class="ok">已保存 PushPlus 配置。现在可以运行 python3 tender_monitor.py 测试提醒。</div>'
            html_text = PUSHPLUS_SETUP_HTML.replace("{message}", message).replace("{page_url}", html.escape(page_url))
            self.send_bytes(200, "text/html; charset=utf-8", html_text.encode("utf-8"))
            return
        self.send_bytes(404, "text/plain; charset=utf-8", "Not found".encode("utf-8"))

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    server = ReusableThreadingHTTPServer((HOST, PORT), Handler)
    print(f"产品资料生成器已启动：http://127.0.0.1:{PORT}")
    server.serve_forever()
