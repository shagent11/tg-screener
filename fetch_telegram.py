#!/usr/bin/env python3
"""
텔레그램에서 오늘자 스크리너 원문을 가져와 stdout으로 뱉는다.

    python fetch_telegram.py | python build.py - --shot --send

주의: 봇은 자기가 속한 채팅의 메시지만 읽는다. 리포트가 개인 DM으로
다른 봇/사람에게서 온다면 이 방법으로는 못 읽으니, 그 경우 리포트를
전용 채널로 포워딩하고 이 봇을 그 채널 관리자로 넣어라.

환경변수:
    TG_BOT_TOKEN      봇 토큰
    TG_SOURCE_CHAT    (선택) 특정 채팅 ID만 필터
    REPORT_MARKER     (선택) 리포트 식별 문자열, 기본 "Screener Report"
"""
import os
import sys
from datetime import datetime, timezone

import requests

TOKEN = os.environ["TG_BOT_TOKEN"]
SOURCE = os.environ.get("TG_SOURCE_CHAT")
MARKER = os.environ.get("REPORT_MARKER", "Screener Report")
STATE = ".tg_offset"


def updates(offset=None):
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates",
                     params={"offset": offset, "limit": 100, "timeout": 0,
                             "allowed_updates": '["message","channel_post"]'},
                     timeout=30)
    r.raise_for_status()
    return r.json().get("result", [])


def download_document(file_id):
    """4096자 제한을 피하려고 문서(파일)로 올라온 리포트는 getFile + 다운로드로 원문을 가져온다."""
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getFile",
                     params={"file_id": file_id}, timeout=30)
    r.raise_for_status()
    file_path = r.json()["result"]["file_path"]
    r = requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{file_path}", timeout=30)
    r.raise_for_status()
    return r.content.decode("utf-8")


def main():
    offset = None
    if os.path.exists(STATE):
        offset = int(open(STATE).read().strip() or 0)

    ups = updates(offset)
    if ups:
        with open(STATE, "w") as f:
            f.write(str(ups[-1]["update_id"] + 1))

    best = None
    for u in ups:
        msg = u.get("message") or u.get("channel_post") or {}
        text = msg.get("text") or msg.get("caption") or ""
        if MARKER not in text:
            continue
        if SOURCE and str(msg.get("chat", {}).get("id")) != str(SOURCE):
            continue
        if best is None or msg.get("date", 0) >= best.get("date", 0):
            best = msg

    if not best:
        sys.exit("오늘자 리포트를 못 찾았다 (마커: %s)" % MARKER)

    when = datetime.fromtimestamp(best["date"], timezone.utc)
    print(f"[수신 {when:%Y-%m-%d %H:%M UTC}] chat={best['chat']['id']}", file=sys.stderr)

    doc = best.get("document")
    if doc:
        sys.stdout.write(download_document(doc["file_id"]))
    else:
        sys.stdout.write(best.get("text") or best.get("caption"))


if __name__ == "__main__":
    main()
