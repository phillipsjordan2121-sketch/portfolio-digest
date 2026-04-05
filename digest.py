#!/usr/bin/env python3
import os, json, anthropic, smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

HOLDINGS = [
    {"ticker": "NVDA", "company": "NVIDIA Corp", "shares": 8.0009, "cost": 192.89},
    {"ticker": "CEG", "company": "Constellation Energy", "shares": 4.0099, "cost": 385.57},
    {"ticker": "FNDE", "company": "Schwab Fundamental Emerging Markets ETF", "shares": 111, "cost": 35.95},
    {"ticker": "QQQ", "company": "Invesco QQQ TR", "shares": 3.0078, "cost": 605.45},
    {"ticker": "CGGR", "company": "Capital Group Growth ETF", "shares": 89, "cost": 44.89},
    {"ticker": "QTUM", "company": "Defiance Quantum ETF", "shares": 2, "cost": 114.56},
    {"ticker": "SWEGX", "company": "Schwab MarketTrack All Equity", "shares": 88.797, "cost": 24.07}
]

RECIPIENT = os.environ["EMAIL_RECIPIENT"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]

def run_research():
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    today = datetime.now().strftime("%A, %B %d, %Y")
    tickers = [h["ticker"] for h in HOLDINGS]
    price_res = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=1500,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": f"Today is {today}. Find current prices for: {', '.join(tickers)}, SPY, QQQ, VIX, GLD. Return ONLY JSON: {\"prices\": {\"AAPL\": {\"price\": 189.50, \"change_pct\": 1.2}}}"}]
    )
    price_json = {}
    for block in price_res.content:
        if block.type == "text":
            txt = block.text.strip()
            try:
                s, e = txt.index("{"), txt.rindex("}")
                price_json = json.loads(txt[s:e+1]); break
            except: pass
    prices = price_json.get("prices", {})
    price_ctx = ", ".join([f"{t}: ${d['price']} ({d.get('change_pct',0):+.1f}%)" for t,d in prices.items()])
    h_str = "\n".join([f"- {h['ticker']} ({h['company']}, {h['shares']} shares, cost ${h['cost']})" for h in HOLDINGS])
    research_res = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": f"Senior equity analyst. Today: {today}.\nPRICES: {price_ctx}\nPORTFOLIO:\n{h_str}\n\nWrite 3-4 sentence research paragraph for each holding. Return ONLY JSON: {\"summary\":{\"outlook\":\"...\"},\"macro\":{\"fed_rate\":\"...\",\"ten_year\":\"...\",\"vix\":\"...\",\"cpi\":\"...\"},\"portfolio\":[{\"ticker\":\"NVDA\",\"sentiment\":\"bullish\",\"current_price\":177.39,\"company\":\"NVIDIA\",\"paragraph\":\"...\"}],\"ideas\":[{\"ticker\":\"...\",\"company\":\"...\",\"paragraph\":\"...\"}]}"}]
    )
    for block in research_res.content:
        if block.type == "text":
            txt = block.text.strip()
            try:
                s, e = txt.index("{"), txt.rindex("}")
                return json.loads(txt[s:e+1]), price_json
            except: pass
    return {}, price_json

def build_email(report, price_data):
    r, date = report, datetime.now().strftime("%A, %B %d, %Y")
    m = r.get("macro", {})
    rows = ""
    for s in r.get("portfolio", []):
        c = "#16A34A" if s.get("sentiment")=="bullish" else "#DC2626" if s.get("sentiment")=="bearish" else "#B45309"
        rows += f'<tr><td style="padding:14px 16px;border-bottom:1px solid #E5E7EB"><b style="font-family:monospace">{s["ticker"]}</b> <span style="color:{c};font-size:11px">{s.get("sentiment","").upper()}</span> <span style="color:#6B7280">{s.get("company","")}</span><br><p style="font-size:13px;color:#374151;line-height:1.7">{s.get("paragraph","")}</p></td></tr>'
    ideas = ""
    for i in r.get("ideas", []):
        ideas += f'<div style="border:1px solid #E5E7EB;border-radius:8px;padding:14px;margin-bottom:10px"><b style="color:#2563EB;font-family:monospace">{i.get("ticker","")} - {i.get("company","")}</b><p style="font-size:13px;color:#374151;line-height:1.7;margin:6px 0 0">{i.get("paragraph","")}</p></div>'
    macro_bar = ""
    if m:
        macro_bar = f'<div style="background:#fff;border:1px solid #E5E7EB;border-radius:10px;padding:14px;margin-bottom:16px;display:flex;gap:20px"><div><div style="font-size:10px;color:#6B7280">Fed Rate</div><b>{m.get("fed_rate","--")}</b></div><div><div style="font-size:10px;color:#6B7280">10Y</div><b>{m.get("ten_year","--")}</b></div><div><div style="font-size:10px;color:#6B7280">VIX</div><b>{m.get("vix","--")}</b></div><div><div style="font-size:10px;color:#6B7280">CPI</div><b>{m.get("cpi","--")}</b></div></div>'
    return f"""<!DOCTYPE html><html><body style="font-family:-apple-system,sans-serif;background:#F9FAFB;margin:0;padding:0"><div style="max-width:640px;margin:0 auto;padding:20px"><div style="background:#1E3A5F;border-radius:12px;padding:24px;color:#fff;margin-bottom:16px"><div style="font-size:22px;font-weight:700">Daily Research Brief</div><div style="font-size:12px;color:#CBD5E1">{date}</div><p style="font-size:13px;color:#E2E8F0;line-height:1.7">{r.get("summary",{}).get("outlook","")}</p></div>{macro_bar}<h2 style="font-size:15px;font-weight:700;border-bottom:2px solid #E5E7EB;padding-bottom:8px">Portfolio</h2><table style="width:100%;border-collapse:collapse;background:#fff;border:1px solid #E5E7EB;border-radius:10px">{rows}</table>{("<h2>Ideas</h2>" + ideas) if ideas else ""}<p style="font-size:11px;color:#9CA3AF;text-align:center;margin-top:20px">For research purposes only. Not financial advice.</p></div></body></html>"""

def send_email(html_body, subject):
    sender = os.environ.get("GMAIL_SENDER", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if sender and password:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = RECIPIENT
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(sender, password)
            s.sendmail(sender, RECIPIENT, msg.as_string())
        print(f"Email sent to {RECIPIENT}")
    else:
        print("Set GMAIL_SENDER + GMAIL_APP_PASSWORD in GitHub Secrets.")

if __name__ == "__main__":
    print(f"Running digest - {datetime.now()}")
    report, price_data = run_research()
    html = build_email(report, price_data)
    subject = f"Portfolio Brief - {datetime.now().strftime('%b %d, %Y')}"
    send_email(html, subject)
    print("Done.")
