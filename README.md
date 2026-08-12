# 스크리너 리포트 → 대시보드 카드 자동 발송

텔레그램으로 오는 스크리너 원문을 매일 같은 폼의 대시보드로 만들어 다시 텔레그램으로 보낸다.

```
원문 텍스트 → parse_report.py → JSON → template.html → PNG → 텔레그램
```

**LLM을 쓰지 않는다.** 섹션 헤더가 고정이라 정규식으로 전부 뽑힌다. 매일 비용 0,
결과는 결정론적이고, 폼이 날마다 흔들리지 않는다. 대신 원문 구조가 바뀌면 파서가 깨지므로
`validate()`가 최소 조건을 검사하고 `--strict`에서 중단시킨다.

## 파일

| 파일 | 역할 |
|---|---|
| `parse_report.py` | 원문 → JSON. 정규식만 사용 |
| `template.html` | 폼 고정 템플릿. `__DATA__` 자리에 JSON이 주입된다 |
| `build.py` | 파싱 → 렌더 → 스크린샷 → 발송 |
| `fetch_telegram.py` | 텔레그램에서 당일 원문 수신 |
| `.github/workflows/daily.yml` | 매일 자동 실행 |

## 로컬에서 돌려보기

```bash
pip install -r requirements.txt
playwright install chromium

python build.py sample/2026-08-12.txt          # out/2026-08-12.html
python build.py sample/2026-08-12.txt --shot   # + PNG (텔레그램 카드 크기)
python build.py sample/2026-08-12.txt --shot --full   # 전체 페이지 캡처
```

파싱만 확인하려면:

```bash
python parse_report.py sample/2026-08-12.txt | jq .priority
```

## 텔레그램 설정

1. @BotFather에서 봇을 만들어 토큰을 받는다.
2. 리포트를 받을 채널(또는 그룹)을 만들고 봇을 **관리자로** 넣는다.
3. 거기에 아무 메시지나 하나 보낸 뒤 `getUpdates`로 `chat.id`를 확인한다.

```bash
curl "https://api.telegram.org/bot<TOKEN>/getUpdates" | jq '.result[].message.chat'
```

**중요:** 봇은 자기가 속한 채팅만 읽는다. 리포트가 개인 DM으로 온다면
`fetch_telegram.py`로는 못 가져온다. 그 경우 두 가지 중 하나를 택한다.

- 리포트를 전용 채널로 포워딩하고 그 채널을 봇이 읽게 한다 (권장)
- 원문을 파일로 떨궈 `python build.py report.txt --shot --send` 로 직접 넘긴다

## GitHub Actions

Secrets에 `TG_BOT_TOKEN`, `TG_CHAT_ID`, (선택) `TG_SOURCE_CHAT`을 넣는다.
`daily.yml`의 cron은 UTC 기준이니 **실제 리포트 도착 시각 이후**로 맞춰야 한다.
기본값은 한국시간 07:20이다.

먼저 Actions 탭에서 `workflow_dispatch`로 `dry_run: true`를 한 번 돌려
아티팩트의 PNG를 눈으로 확인한 다음 자동 발송을 켜는 걸 권한다.

## 이미지가 뭉개질 때

텔레그램은 세로로 긴 사진을 심하게 압축한다. 그래서 기본 캡처는 **카드 모드**로,
헤더 + RS 스펙트럼 + 우선순위 3축만 담는다 (`#card` 해시). 나머지 섹션은
`template.html`에서 `class="full"`이 붙어 있고 카드 모드에서 숨는다.

전체 대시보드를 보고 싶으면 GitHub Pages를 켜고 (`daily.yml` 마지막 스텝 주석 해제)
`DASHBOARD_URL` 변수를 넣으면 캡션 하단에 링크가 붙는다.

무압축 원본이 꼭 필요하면 `sendPhoto` 대신 `sendDocument`를 쓰면 되지만
인라인 미리보기가 사라진다.

## 원문 구조가 바뀌면

`parse_report.py` 상단의 `SECTIONS` 리스트가 헤더 목록이다. 헤더 이름이 바뀌면
여기만 고치면 된다. 개별 줄 형식이 바뀌면 해당 `parse_*` 함수의 정규식을 손본다.
`validate()`에 조건을 추가해두면 조용히 깨진 카드가 발송되는 사고를 막을 수 있다.

## 폼을 바꾸고 싶을 때

`template.html`만 고친다. 데이터는 `<script id="payload">`에 JSON으로 들어오므로
파서는 건드릴 필요가 없다. 색은 `:root`의 CSS 변수에 모여 있다 —
`--up`은 상승 적색, `--down`은 하락 청색이다.
