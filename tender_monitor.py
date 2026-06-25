#!/usr/bin/env python3
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from product_word_server import search_tenders


BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "tender_monitor_seen.json"
ENV_PATH = BASE_DIR / ".env"
DEFAULT_KEYWORD = "医院 卫健委 合理用药 软件系统 招标"


def load_env_file():
    if not ENV_PATH.exists():
        return
    with ENV_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def load_seen():
    if not STATE_PATH.exists():
        return set()
    with STATE_PATH.open("r", encoding="utf-8") as f:
        return set(json.load(f))


def save_seen(seen):
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, ensure_ascii=False, indent=2)


def item_id(item):
    return "|".join([item.get("date", ""), item.get("title", ""), item.get("source", "")])


def post_json(url, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8", errors="ignore")


def send_wecom(webhook_url, items, page_url):
    lines = ["合理用药招标线索有更新：", ""]
    for item in items[:8]:
        lines.append(f"- {item.get('date', '')} {item.get('title', '')}")
        lines.append(f"  来源：{item.get('source', '')}")
    lines.extend(["", f"查看：{page_url}"])
    return post_json(webhook_url, {"msgtype": "text", "text": {"content": "\n".join(lines)}})


def send_pushplus(token, items, page_url):
    content = ["<h3>合理用药招标线索有更新</h3>", "<ul>"]
    for item in items[:8]:
        content.append(
            "<li>{date} {title}<br/>来源：{source}</li>".format(
                date=item.get("date", ""),
                title=item.get("title", ""),
                source=item.get("source", ""),
            )
        )
    content.append("</ul>")
    content.append(f'<p><a href="{page_url}">打开线索工作台</a></p>')
    return post_json(
        "https://www.pushplus.plus/send",
        {
            "token": token,
            "title": "合理用药招标线索有更新",
            "content": "\n".join(content),
            "template": "html",
        },
    )


def send_server_chan(send_key, items, page_url):
    title = "合理用药招标线索有更新"
    desp = ["## 合理用药招标线索有更新", ""]
    for item in items[:8]:
        desp.append(f"- {item.get('date', '')} {item.get('title', '')}（{item.get('source', '')}）")
    desp.extend(["", f"[打开线索工作台]({page_url})"])
    data = urllib.parse.urlencode({"title": title, "desp": "\n".join(desp)}).encode("utf-8")
    request = urllib.request.Request(f"https://sctapi.ftqq.com/{send_key}.send", data=data, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8", errors="ignore")


def notify(items):
    if not items:
        return True
    page_url = os.environ.get("TENDER_PAGE_URL", "http://127.0.0.1:8768/wechat")
    wecom = os.environ.get("WECOM_WEBHOOK_URL")
    pushplus = os.environ.get("PUSHPLUS_TOKEN")
    server_chan = os.environ.get("SERVER_CHAN_SENDKEY")
    if wecom:
        send_wecom(wecom, items, page_url)
        return True
    if pushplus:
        send_pushplus(pushplus, items, page_url)
        return True
    if server_chan:
        send_server_chan(server_chan, items, page_url)
        return True
    print("未配置微信推送通道。请设置 WECOM_WEBHOOK_URL、PUSHPLUS_TOKEN 或 SERVER_CHAN_SENDKEY。")
    return False


def main():
    load_env_file()
    items = search_tenders(DEFAULT_KEYWORD, ["aggregated"], "month", "四川", "all", "")
    seen = load_seen()
    new_items = [item for item in items if item_id(item) not in seen]
    if new_items:
        if notify(new_items):
            seen.update(item_id(item) for item in new_items)
            save_seen(seen)
    print(f"检查完成：{len(items)} 条线索，{len(new_items)} 条新增。")
    for item in new_items:
        print(f"- {item.get('date', '')} {item.get('title', '')}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"检查失败：{exc}", file=sys.stderr)
        raise
