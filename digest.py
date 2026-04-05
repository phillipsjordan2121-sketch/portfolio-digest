#!/usr/bin/env python3
import os, json, anthropic, smtplib, time
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
    ticker_str = ", ".join(tickers)
    price_prompt = "Today is " + today + ". Find current prices for: " + ticker_str + ". Return ONLY JSON: {\"prices\": {\"AAPL\": {\"price\": 189.50, \"change_pct\": 1.2}}}"
    price_res = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=1500,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": price_prompt}]
    )
    price_json = {}
    for block in price_res.content:
        if block.type == "text":
            txt = block.text.strip()
            try:
                s, e = txt.index("{"), txt.rindex("}")
                price_json = json.loads(txt[s:e+1])
                break
            except Exception:
                pass
    prices = price_json.get("prices", {})
    price_parts = []
    for t, d in prices.items():
        chg = d.get("change_pct", 0)
        sign = "+" if chg >= 0 else ""
        price_parts.append(t + ": $" + str(d["price"]) + " (" + sign + str(chg) + "%)")
    price_ctx = ", ".join(price_parts)
    h_parts = []
    for h in HOLDINGS:
        h_parts.append("- " + h["ticker"] + " (" + h["company"] + ", " + str(h["shares"]) + " shares, cost $" + str(h["cost"]) + ")")
    h_str = "\n".join(h_parts)
    print("Waiting 65 seconds to avoid rate limit...")
    time.sleep(65)
    research_prompt = "Senior equity analyst. Today: " + today + ".\nPRICES: " + price_ctx + "\nPORTFOLIO:\n" + h_str + "\n\nWrite 3-4 sentence research paragraph for each holding. Return ONLY JSON: {\"summary\":{\"outlook\":\"...\"},\"macro\":{\"fed_rate\":\"...\",\"ten_year\":\"...\",\"vix\":\"...\",\"cpi\":\"...\"},\"portfolio\":[{\"ticker\":\"NVDA\",\"sentiment\":\"bullish\",\"current_price\":177.39,\"company\":\"NVIDIA\",\"paragraph\":\"...\"}],\"ideas\":[{\"ticker\":\"...\",\"company\":\"...\",\"paragraph\":\"...\"}]}"
    research_res = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": research_prompt}]
    )
    for block in research_res.content:
        if block.type == "text":
            txt = block.text.strip()
            try:
                s, e = txt.index("{"), txt.rindex("}")
                return json.loads(txt[s:e+1]), price_json
            except Exception:
                pass
    return {}, price_json

def build_email(report, price_data):
    r = report
    date = datetime.now().strftime("%A, %B %d, %Y")
    m = r.get("macro", {})
    rows = ""
    for s in r.get("portfolio", []):
        c = "#16A34A" if s.get("sentiment") == "bullish" else "#DC2626" if s.get("sentiment") == "bearish" else "#B45309"
        rows += "<tr><td style='padding:14px 16px;border-bottom:1px solid #E5E7EB'><b style='font-family:monospace'>" + s.get("ticker","") + "</b> <span style='color:" + c + ";font-size:11px'>" + s.get("sentiment","").upper() + "</span> <span style='color:#6B7280'>" + s.get("company","") + "</span><br><p style='font-size:13px;color:#374151;line-height:1.7'>" + s.get("paragraph","") + "</p></td></tr>"
    ideas = ""
    for i in r.get("ideas", []):
        ideas += "<div style='border:1px solid #E5E7EB;border-radius:8px;padding:14px;margin-bottom:10px'><b style='color:#2563EB;font-family:monospace'>" + i.get("ticker","") + " - " + i.get("company","") + "</b><p style='font-size:13px;color:#374151;line-height:1.7;margin:6px 0 0'>" + i.get("paragraph","") + "</p></div>"
    macro_bar = ""
    if m:
        macro_bar = "<div style='background:#fff;border:1px solid #E5E7EB;border-radius:10px;padding:14px;margin-bottom:16px;display:flex;gap:20px'><div><div style='font-size:10px;color:#6B7280'>Fed Rate</div><b>" + m.get("fed_rate","--") + "</b></div><div><div style='font-size:10px;color:#6B7280'>10Y</div><b>" + m.get("ten_year","--") + "</b></div><div><div style='font-size:10px;color:#6B7280'>VIX</div><b>" + m.get("vix","--") + "</b></div><div><div style='font-size:10px;color:#6B7280'>CPI</div><b>" + m.get("cpi","--") + "</b></div></div>"
    outlook = r.get("summary", {}).get("outlook", "")
    body = "<!DOCTYPE html><html><body style='font-family:-apple-system,sans-serif;background:#F9FAFB;margin:0;padding:0'>"
    body += "<div style='max-width:640px;margin:0 auto;padding:20px'>"
    body += "<div style='background:#1E3A5F;border-radius:12px;padding:24px;color:#fff;margin-bottom:16px'>"
    body += "<div style='font-size:22px;font-weight:700'>Daily Research Brief</div>"
    body += "<div style='font-size:12px;color:#CBD5E1'>" + date + "</div>"
    body += "<p style='font-size:13px;color:#E2E8F0;line-height:1.7'>" + outlook + "</p></div>"
    body += macro_bar
    body += "<h2 style='font-size:15px;font-weight:700;border-bottom:2px solid #E5E7EB;padding-bottom:8px'>Portfolio</h2>"
    body += "<table style='width:100%;border-collapse:collapse;background:#fff;border:1px solid #E5E7EB;border-radius:10px'>" + rows + "</table>"
    if ideas:
        body += "<h2>Ideas</h2>" + ideas
    body += "<p style='font-size:11px;color:#9CA3AF;text-align:center;margin-top:20px'>For research purposes only. Not financial advice.</p>"
    body += "</div></body></html>"
    return body

def send_email(html_body, subject):
    sender = os.environ.get("GMAIL_SENDER", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if sender and password:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = RECIPIENT
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(sender, password)
            smtp.sendmail(sender, RECIPIENT, msg.as_string())
        print("Email sent to " + RECIPIENT)
    else:
        print("Missing GMAIL_SENDER or GMAIL_APP_PASSWORD secrets")

if __name__ == "__main__":
    print("Running digest - " + str(datetime.now()))
    report, price_data = run_research()
    html = build_email(report, price_data)
    subject = "Portfolio Brief - " + datetime.now().strftime("%b %d, %Y")
    send_email(html, subject)
    print("Done.")
