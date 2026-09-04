#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""매일 대시보드 갱신 후 가족에게 알림 메일 발송 (GitHub Actions에서 실행).
필요한 GitHub Secrets: MAIL_FROM(보내는 Gmail), GMAIL_APP_PASSWORD(앱 비밀번호),
MAIL_TO(받는 주소들, 쉼표로 구분). 하나라도 없으면 발송을 건너뛴다."""
import os, re, smtplib, ssl, time
from datetime import datetime
from email.mime.text import MIMEText
from email.utils import formatdate

URL = "https://uncmac.github.io/market-brief/"

frm = os.environ.get("MAIL_FROM")
pw = os.environ.get("MAIL_PASS")
to = os.environ.get("MAIL_TO")
if not (frm and pw and to):
    print("메일 설정(Secrets) 없음 — 발송 생략")
    raise SystemExit(0)

# 방금 생성된 index.html에서 종합 판정·점수·권장 행동을 추출해 메일 본문에 요약
html = open("index.html", encoding="utf-8").read()


def find(pat):
    m = re.search(pat, html)
    return m.group(1).strip() if m else ""


verdict = find(r'class="verdict"[^>]*>([^<]+)<')
score = find(r'class="score mono"[^>]*>([^<]+)<')
action = find(r'권장 행동: ([^<]+)<')
asof = find(r'기준일 <b>([^<]+)</b>')
kind = find(r'기준일 <b>[^<]+</b> ([^<]+)<')        # "종가" 또는 "장중"
warn = find(r'class="tag warn">([^<]+)<')          # 휴장·개장 전·장중 안내 (없으면 빈 문자열)

today = datetime.now().strftime("%Y-%m-%d")
warn_line = f"\n참고: {warn}" if warn else ""
body = f"""오늘의 시장 브리핑이 갱신되었습니다.

기준일: {asof} {kind}{warn_line}
종합 판정: {verdict} ({score} / ±100)
권장 행동: {action}

전체 대시보드 보기:
{URL}

(이 메일은 매일 아침 자동 발송됩니다. 아이폰에서 위 링크를 연 뒤
공유 → "홈 화면에 추가"를 하면 앱처럼 쓸 수 있습니다.)"""

msg = MIMEText(body, "plain", "utf-8")
msg["Subject"] = f"📈 오늘의 시장 브리핑 · {today}" + (f" · {verdict}" if verdict else "")
msg["From"] = frm
msg["To"] = to
msg["Date"] = formatdate(localtime=True)

rcpt = [x.strip() for x in to.split(",") if x.strip()]

# Gmail 일시 오류(연결 끊김·일시적 거부)에 대비해 3회까지 재시도.
# 3회 모두 실패하면 예외로 종료 → 작업이 실패로 표시되고, 마커가 남지 않아
# 다음 재시도 슬롯(오전 내)이 다시 발송을 시도한다.
for attempt in range(1, 4):
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465,
                              context=ssl.create_default_context(), timeout=60) as s:
            s.login(frm, pw)
            s.sendmail(frm, rcpt, msg.as_string())
        print(f"메일 발송 완료 (시도 {attempt}회차) →", to)
        break
    except Exception as e:
        print(f"[경고] 메일 발송 실패 (시도 {attempt}/3): {type(e).__name__}: {e}")
        if attempt == 3:
            raise
        time.sleep(30 * attempt)
