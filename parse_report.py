#!/usr/bin/env python3
"""
스크리너 텔레그램 원문 -> 구조화 JSON.

LLM을 쓰지 않는다. 섹션 헤더가 고정이라는 전제 하에 정규식으로만 뽑는다.
매일 비용 0, 결과 100% 결정론적.

사용:
    python parse_report.py sample/2026-08-12.txt > data.json
"""
import json
import re
import sys
import unicodedata
from datetime import date

# 원문에 등장하는 섹션 헤더. 순서는 상관없다.
SECTIONS = [
    "Situational Awareness", "한줄 요약", "장세 판단", "추세추종 적합도",
    "시장 센티먼트", "과열 / 공포 체크", "브레드스/확산도", "오늘 흐름",
    "전일 대비 변화", "최근 며칠 누적 흐름", "계속 강한 섹터와 그룹",
    "새로 강해진 섹터와 그룹", "약해진 섹터와 그룹", "ETF 흐름",
    "섹터 ↔ 종목 매칭", "Tech/Growth 환경", "강세 종목", "반복 출현 리더",
    "왜 강한가", "눌림 종목", "횡보 종목", "약해지는 종목",
    "가장 먼저 볼 종목", "내 해석", "다음 액션", "RS 저평가 후보",
]

# 티커로 오인하기 쉬운 대문자 토큰
NOT_TICKER = {
    "RS", "RV", "AI", "ETF", "UWL", "1D", "1W", "1M", "E", "P&L",
    "US", "VIX", "A", "D", "EP", "AD",
}


def strip_emoji(s: str) -> str:
    out = []
    for ch in s:
        cat = unicodedata.category(ch)
        if cat == "So" or ch in "\ufe0f\u200d":
            continue
        out.append(ch)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def split_sections(text: str) -> dict:
    """헤더 라인을 기준으로 본문을 섹션별로 자른다."""
    lines = text.splitlines()
    idx, current, buf = {}, None, []
    for line in lines:
        bare = strip_emoji(line).strip()
        hit = next((h for h in SECTIONS if bare == h or bare.startswith(h + " ")), None)
        if hit and not line.strip().startswith("-"):
            if current:
                idx[current] = "\n".join(buf).strip()
            current, buf = hit, []
            continue
        buf.append(line)
    if current:
        idx[current] = "\n".join(buf).strip()
    return idx


def bullets(block: str) -> list:
    """'- ' 로 시작하는 줄만 뽑아 앞의 대시를 뗀다."""
    return [
        re.sub(r"^-\s*", "", ln).strip()
        for ln in (block or "").splitlines()
        if ln.strip().startswith("-")
    ]


def num(m, default=None):
    return float(m.group(1)) if m else default


def tickers_in(s: str) -> list:
    """문장에서 티커만 순서대로, 중복 없이."""
    found, seen = [], set()
    for t in re.findall(r"\b([A-Z]{1,6})\b", s):
        if t in NOT_TICKER or t in seen or t.isdigit():
            continue
        seen.add(t)
        found.append(t)
    return found


# --------------------------------------------------------------------------
# 개별 섹션 파서
# --------------------------------------------------------------------------

def parse_etf(sec: dict) -> list:
    """ETF 흐름 섹션 -> [{ticker, rs, d, w, m, note}]"""
    rows = []
    for b in bullets(sec.get("ETF 흐름", "")):
        head = re.match(r"^([A-Z]{2,6}):\s*RS\s*(\d+)\s*(.*)$", b)
        if head:
            ticker, rs, rest = head.group(1), int(head.group(2)), head.group(3)
            note = rest
            # 마지막 퍼센트 뒤부터가 코멘트
            last = None
            for m in re.finditer(r"1[DWM]\s*[+-][\d.]+%", rest):
                last = m
            if last:
                note = rest[last.end():]
            note = strip_emoji(note).lstrip("/ ").strip()
            note = note.split("→")[0].strip() or note
            rows.append({
                "ticker": ticker,
                "rs": rs,
                "d": num(re.search(r"1D\s*([+-][\d.]+)%", rest)),
                "w": num(re.search(r"1W\s*([+-][\d.]+)%", rest)),
                "m": num(re.search(r"1M\s*([+-][\d.]+)%", rest)),
                "note": note,
            })
            continue
        # "약한 쪽: IBIT(RS18)·URA(33)·FINX(37)..." 형태
        if b.startswith("약한 쪽"):
            tail = b.split("—")[-1] if "—" in b else "우선순위 최하"
            for t, rs in re.findall(r"([A-Z]{2,6})\((?:RS)?(\d+)\)", b):
                rows.append({
                    "ticker": t, "rs": int(rs), "d": None, "w": None, "m": None,
                    "note": strip_emoji(tail).strip(),
                })
    rows.sort(key=lambda r: -r["rs"])
    return rows


def parse_breadth(sec: dict) -> list:
    """'8/7 164/29 → 8/8 157/36 → ...'"""
    block = sec.get("브레드스/확산도", "")
    out = []
    for d, b, o in re.findall(r"(\d{1,2}/\d{1,2})\s+(\d{2,4})/(\d{1,3})", block):
        out.append({"date": d, "breadth": int(b), "overlap": int(o)})
    return out


def parse_axes(sec: dict) -> list:
    """'- 축1 소프트·서비스(1위·33개): TEAM +1.46%, ...'"""
    axes = []
    for b in bullets(sec.get("오늘 흐름", "")):
        m = re.match(r"^축(\d+)\s+([^(:]+)(?:\(([^)]*)\))?\s*:\s*(.*)$", b)
        if not m:
            continue
        body = strip_emoji(m.group(4))
        axes.append({
            "no": int(m.group(1)),
            "name": m.group(2).strip(),
            "tag": (m.group(3) or "").strip(),
            "tickers": tickers_in(body),
            "raw": body,
        })
    return axes


def parse_priority(sec: dict) -> dict:
    """'가장 먼저 볼 종목' -> 순위별 종목 + 확인 포인트."""
    ranked, watch = [], ""
    for b in bullets(sec.get("가장 먼저 볼 종목", "")):
        m = re.match(r"^(\d)순위:\s*(.+)$", b)
        if m:
            body = strip_emoji(m.group(2))
            names, why = (body.split("—", 1) + [""])[:2]
            ranked.append({
                "rank": int(m.group(1)),
                "tickers": tickers_in(names),
                "why": why.strip(" —"),
            })
        elif b.startswith("관찰만"):
            watch = strip_emoji(b.split(":", 1)[-1]).strip()
    ranked.sort(key=lambda r: r["rank"])
    return {"ranked": ranked, "watch": watch, "watch_tickers": tickers_in(watch)}


def parse_leaders(sec: dict) -> list:
    """'- P: 4중복 +11.64%, $36.36B — 설명'"""
    out = []
    for b in bullets(sec.get("반복 출현 리더", "")):
        m = re.match(
            r"^([A-Z]{1,6}):\s*(\d+)중복\s*([+-][\d.]+)%,\s*\$([\d.]+)B"
            r"(?:,\s*1M\s*([+-][\d.]+)%)?\s*—\s*(.*)$", b)
        if not m:
            continue
        out.append({
            "ticker": m.group(1),
            "overlap": int(m.group(2)),
            "d": float(m.group(3)),
            "cap": float(m.group(4)),
            "m1": float(m.group(5)) if m.group(5) else None,
            "note": strip_emoji(m.group(6)).strip(),
        })
    out.sort(key=lambda r: (-r["overlap"], -r["cap"]))
    return out


def parse_underrated(sec: dict) -> list:
    """'- SLV: RS63, 1W +5.3%, 1M +11.5%' -> [{ticker, rs, w, m}] (screener_bridge.py가 계산해서 붙인, 결정론적 포맷)"""
    out = []
    for b in bullets(sec.get("RS 저평가 후보", "")):
        m = re.match(r"^([A-Z]{1,6}):\s*RS(\d+)(?:,\s*1W\s*([+-][\d.]+)%)?,\s*1M\s*([+-][\d.]+)%$", b)
        if not m:
            continue
        out.append({
            "ticker": m.group(1),
            "rs": int(m.group(2)),
            "w": float(m.group(3)) if m.group(3) else None,
            "m": float(m.group(4)),
        })
    out.sort(key=lambda r: -r["m"])
    return out


def parse_group_list(block: str) -> list:
    """'- 이름: 설명' 형태의 섹터 목록."""
    out = []
    for b in bullets(block):
        name, _, desc = b.partition(":")
        out.append({
            "name": strip_emoji(name).strip(),
            "desc": strip_emoji(desc).strip() or strip_emoji(b),
        })
    return out


def parse_highs(text: str) -> dict:
    """52주 신고가 총계와 섹터 구성."""
    comp, total = [], None
    # '신고가 43개가 에너지9·헬스8...' 처럼 구성이 딸린 문장이 진짜 총계다.
    seg = re.search(r"신고가\s*(\d+)개가\s*([^—\n]+)", text)
    if seg:
        total = int(seg.group(1))
        for name, cnt in re.findall(r"([가-힣]{2,4})(\d{1,2})", seg.group(2)):
            comp.append({"name": name, "count": int(cnt)})
    else:
        hits = [int(n) for n in re.findall(r"52주 신고가\s*(\d+)개", text)]
        total = max(hits) if hits else None
    return {"total": total, "composition": comp}


def parse_froth(sec: dict) -> list:
    """froth·소형 라인에서 종목과 등락."""
    out = []
    for b in bullets(sec.get("오늘 흐름", "")):
        if not b.startswith("froth"):
            continue
        for t, v in re.findall(r"([A-Z]{2,6})\s*([+-][\d.]+)%", b):
            out.append({"ticker": t, "d": float(v)})
    return out


# --------------------------------------------------------------------------

def parse(text: str) -> dict:
    sec = split_sections(text)

    # 날짜
    dm = re.search(r"(\d{4})-(\d{2})-(\d{2})", text[:200])
    rdate = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}" if dm else date.today().isoformat()

    # 헤드라인: 한줄 요약의 첫 '—' 앞
    oneline = strip_emoji(sec.get("한줄 요약", "")).strip()
    headline = oneline.split("—")[0].strip() if oneline else ""

    fit = bullets(sec.get("추세추종 적합도", ""))
    heat = bullets(sec.get("과열 / 공포 체크", ""))
    breadth = parse_breadth(sec)

    uwl = re.search(r"UWL\s*(\d+)개 중\s*(\d+)개", text)
    ref = re.search(r"ETF Excel 기준일\s*([\d/]+)", text)

    return {
        "date": rdate,
        "headline": headline,
        "oneline": oneline,
        "verdict": strip_emoji(fit[0]) if fit else "",
        "priority_line": strip_emoji(fit[1]) if len(fit) > 1 else "",
        "regime": [strip_emoji(b) for b in bullets(sec.get("장세 판단", ""))],
        "heat_label": strip_emoji(heat[0]) if heat else "",
        "heat_reasons": [strip_emoji(b) for b in heat[1:]],
        "breadth": breadth,
        "today": breadth[-1] if breadth else None,
        "highs": parse_highs(text),
        "uwl": {"hits": int(uwl.group(2)), "total": int(uwl.group(1))} if uwl else None,
        "etf": parse_etf(sec),
        "etf_asof": ref.group(1) if ref else None,
        "axes": parse_axes(sec),
        "priority": parse_priority(sec),
        "leaders": parse_leaders(sec),
        "froth": parse_froth(sec),
        "getting_strong": parse_group_list(sec.get("새로 강해진 섹터와 그룹", "")),
        "getting_weak": parse_group_list(sec.get("약해진 섹터와 그룹", "")),
        "still_strong": parse_group_list(sec.get("계속 강한 섹터와 그룹", "")),
        "underrated": parse_underrated(sec),
        "actions": [strip_emoji(b) for b in bullets(sec.get("다음 액션", ""))],
        "read": [strip_emoji(b) for b in bullets(sec.get("내 해석", ""))],
    }


def validate(d: dict) -> list:
    """조용히 깨진 채로 발송되는 게 최악이라, 최소 조건만 강하게 본다."""
    errs = []
    if len(d["etf"]) < 8:
        errs.append(f"ETF 행이 {len(d['etf'])}개뿐 (8개 미만)")
    if len(d["breadth"]) < 2:
        errs.append("breadth 추이를 못 읽음")
    if not d["axes"]:
        errs.append("오늘의 축을 못 읽음")
    if not d["priority"]["ranked"]:
        errs.append("우선순위를 못 읽음")
    if not d["headline"]:
        errs.append("헤드라인이 빔")
    return errs


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else None
    raw = open(src, encoding="utf-8").read() if src else sys.stdin.read()
    data = parse(raw)
    problems = validate(data)
    if problems:
        for p in problems:
            print(f"[파싱 경고] {p}", file=sys.stderr)
    print(json.dumps(data, ensure_ascii=False, indent=2))
