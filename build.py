#!/usr/bin/env python3
"""
원문 텍스트 -> HTML -> PNG -> 텔레그램 발송.

    python build.py sample/2026-08-12.txt              # HTML만
    python build.py report.txt --shot                  # PNG까지
    python build.py report.txt --shot --send           # 발송까지
    cat report.txt | python build.py - --shot --send   # 파이프 입력

환경변수:
    TG_BOT_TOKEN   봇 토큰
    TG_CHAT_ID     받을 채팅/채널 ID
    DASHBOARD_URL  전체 대시보드가 올라가는 베이스 URL (선택, 캡션 링크용)
"""
import argparse
import json
import os
import sys
from pathlib import Path

from parse_report import parse, validate

ROOT = Path(__file__).parent
OUT = ROOT / "out"


def render(data: dict) -> str:
    tpl = (ROOT / "template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False)
    # </script> 가 payload 안에 들어가면 문서가 깨진다
    payload = payload.replace("</", "<\\/")
    return tpl.replace("__DATA__", payload).replace("__DATE__", data["date"])


def shoot(html_path: Path, png_path: Path, card: bool = True, width: int = 760):
    """Playwright로 스크린샷. 카드 모드는 .full 섹션이 숨겨진 압축 뷰."""
    from playwright.sync_api import sync_playwright

    url = html_path.resolve().as_uri() + ("#card" if card else "")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": width, "height": 1200},
                        device_scale_factor=2)
        pg.goto(url)
        pg.wait_for_timeout(400)
        pg.screenshot(path=str(png_path), full_page=True)
        b.close()
    return png_path


def caption(data: dict) -> str:
    """텔레그램 캡션. 1024자 제한이 있으니 3줄 + 우선순위만."""
    lines = [f"*{data['date']}* · {data['verdict']}", "", data["headline"]]
    t = data.get("today") or {}
    if t:
        lines.append(f"breadth {t.get('breadth')}/{t.get('overlap')}"
                     + (f" · 신고가 {data['highs']['total']}" if data.get("highs", {}).get("total") else ""))
    lines.append("")
    for r in data["priority"]["ranked"][:3]:
        lines.append(f"{r['rank']}. " + " · ".join(r["tickers"][:5]))
    if data.get("froth"):
        lines.append("추격 금지: " + " · ".join(f["ticker"] for f in data["froth"]))
    url = os.environ.get("DASHBOARD_URL")
    if url:
        lines += ["", f"{url.rstrip('/')}/{data['date']}.html"]
    text = "\n".join(lines)
    return text[:1020]


def send(png: Path, text: str):
    import requests

    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_CHAT_ID")
    if not token or not chat:
        sys.exit("TG_BOT_TOKEN / TG_CHAT_ID 가 없다")
    with open(png, "rb") as f:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data={"chat_id": chat, "caption": text, "parse_mode": "Markdown"},
            files={"photo": f}, timeout=60)
    if not r.ok or not r.json().get("ok"):
        sys.exit(f"발송 실패: {r.text[:300]}")
    print("발송 완료")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="원문 텍스트 파일 경로, 또는 - 로 stdin")
    ap.add_argument("--shot", action="store_true", help="PNG까지 생성")
    ap.add_argument("--send", action="store_true", help="텔레그램 발송")
    ap.add_argument("--full", action="store_true", help="카드 대신 전체 페이지를 캡처")
    ap.add_argument("--strict", action="store_true", help="파싱 경고가 있으면 중단")
    a = ap.parse_args()

    raw = sys.stdin.read() if a.src == "-" else Path(a.src).read_text(encoding="utf-8")
    data = parse(raw)

    problems = validate(data)
    for p in problems:
        print(f"[파싱 경고] {p}", file=sys.stderr)
    if problems and a.strict:
        sys.exit("strict 모드: 파싱이 불완전해 중단한다")

    OUT.mkdir(exist_ok=True)
    html = OUT / f"{data['date']}.html"
    html.write_text(render(data), encoding="utf-8")
    (OUT / f"{data['date']}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"HTML: {html}")

    if a.shot or a.send:
        png = OUT / f"{data['date']}.png"
        shoot(html, png, card=not a.full)
        print(f"PNG: {png}")
        if a.send:
            send(png, caption(data))


if __name__ == "__main__":
    main()
