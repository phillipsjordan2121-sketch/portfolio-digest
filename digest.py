#!/usr/bin/env python3
import os, json, anthropic, smtplib, time
import yfinance as yf
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from urllib.parse import quote

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

def fetch_prices():
    prices = {}
    print("Fetching prices from Yahoo Finance...")
    for h in HOLDINGS:
        ticker = h["ticker"]
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            price = round(float(info.last_price), 2)
            prev_close = round(float(info.previous_close), 2)
            change_pct = round(((price - prev_close) / prev_close) * 100, 2) if prev_close else 0
            prices[ticker] = {"price": price, "change_pct": change_pct}
            print(ticker + ": $" + str(price) + " (" + ("+" if change_pct >= 0 else "") + str(change_pct) + "%)")
        except Exception as ex:
            print("Failed to get price for " + ticker + ": " + str(ex))
    return {"prices": prices}

def run_research(client, today, price_data):
    prices = price_data.get("prices", {})
    price_parts = []
    for h in HOLDINGS:
        p = prices.get(h["ticker"], {})
        if p.get("price"):
            chg = p.get("change_pct") or 0
            sign = "+" if chg >= 0 else ""
            price_parts.append(h["ticker"] + ": $" + str(p["price"]) + " (" + sign + str(chg) + "%)")
    price_ctx = ", ".join(price_parts)
    h_parts = []
    for h in HOLDINGS:
        h_parts.append("- " + h["ticker"] + " (" + h["company"] + ", " + str(h["shares"]) + " shares, cost $" + str(h["cost"]) + ")")
    h_str = "\n".join(h_parts)
    prompt = (
        "You are a senior equity analyst. Today: " + today + ".\n"
        "CONFIRMED PRICES from Yahoo Finance (do NOT search for prices, use these exactly):\n"
        + price_ctx + "\n\n"
        "PORTFOLIO:\n" + h_str + "\n\n"
        "Use web search for news, analyst ratings, earnings, and macro commentary only. "
        "Use the confirmed prices above for current_price fields. "
        "For each holding write a 3-4 sentence research paragraph. "
        "Provide exactly ONE high-conviction investment idea. "
        "Return ONLY valid JSON:\n"
        "{\"summary\":{\"outlook\":\"...\"},"
        "\"macro\":{\"fed_rate\":\"...\",\"ten_year\":\"...\",\"vix\":\"...\",\"cpi\":\"...\"},"
        "\"portfolio\":[{\"ticker\":\"NVDA\",\"company\":\"NVIDIA Corp\",\"sentiment\":\"bullish\","
        "\"current_price\":174.88,\"paragraph\":\"...\"}],"
        "\"idea\":{\"ticker\":\"...\",\"company\":\"...\",\"conviction\":\"High\",\"paragraph\":\"...\"}}"
    )
    res = client.messages.create(
        model="claude-sonnet-4-20250514", max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}]
    )
    for block in res.content:
        if block.type == "text":
            txt = block.text.strip()
            try:
                s, e = txt.index("{"), txt.rindex("}")
                return json.loads(txt[s:e+1])
            except Exception:
                pass
    return {}

def build_claude_url(report, price_data):
    date = datetime.now().strftime("%B %d, %Y")
    prices = price_data.get("prices", {})
    lines = ["I just received my daily portfolio brief for " + date + ". Here is my portfolio context:", ""]
    for h in HOLDINGS:
        p = prices.get(h["ticker"], {})
        price_str = "$" + str(p.get("price","?")) if p.get("price") else "price unavailable"
        lines.append("- " + h["ticker"] + " (" + h["company"] + "): " + str(h["shares"]) + " shares, cost $" + str(h["cost"]) + ", current " + price_str)
    m = report.get("macro", {})
    if m:
        lines.append("")
        lines.append("Macro: Fed " + m.get("fed_rate","--") + ", 10Y " + m.get("ten_year","--") + ", VIX " + m.get("vix","--") + ", CPI " + m.get("cpi","--"))
    lines.append("")
    lines.append("Please help me think through any questions I have about this brief.")
    return "https://claude.ai/new?q=" + quote("\n".join(lines))

def build_email(report, price_data):
    date = datetime.now().strftime("%A, %B %d, %Y")
    m = report.get("macro", {})
    prices = price_data.get("prices", {})
    total_cost = 0
    total_value = 0
    for h in HOLDINGS:
        cost_total = h["shares"] * h["cost"]
        total_cost += cost_total
        p = prices.get(h["ticker"], {})
        if p.get("price"):
            total_value += h["shares"] * float(p["price"])
        else:
            stock = next((s for s in report.get("portfolio", []) if s.get("ticker") == h["ticker"]), None)
            total_value += h["shares"] * float(stock["current_price"]) if stock and stock.get("current_price") else cost_total
    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    pnl_color = "#16A34A" if total_pnl >= 0 else "#DC2626"
    pnl_sign = "+" if total_pnl >= 0 else ""
    macro_html = ""
    if m:
        macro_html = "<div style='margin-bottom:24px'>"
        for label, bg, color in [("Fed " + m.get("fed_rate","--"), "#f3f4f6", "#374151"), ("10Y " + m.get("ten_year","--"), "#f3f4f6", "#374151"), ("VIX " + m.get("vix","--"), "#fef3c7", "#d97706"), ("CPI " + m.get("cpi","--"), "#f3f4f6", "#374151")]:
            if "--" not in label:
                macro_html += "<span style='background:" + bg + ";color:" + color + ";font-size:11px;font-weight:600;padding:4px 12px;border-radius:20px;margin-right:6px;margin-bottom:6px;display:inline-block'>" + label + "</span>"
        macro_html += "</div>"
    rows = ""
    for s in report.get("portfolio", []):
        sent = s.get("sentiment", "neutral")
        if sent == "bullish":
            badge_bg, badge_color, badge_text = "#dcfce7", "#15803d", "BULLISH"
        elif sent == "bearish":
            badge_bg, badge_color, badge_text = "#fee2e2", "#dc2626", "BEARISH"
        else:
            badge_bg, badge_color, badge_text = "#fef3c7", "#d97706", "NEUTRAL"
        ticker = s.get("ticker", "")
        company = s.get("company", "")
        paragraph = s.get("paragraph", "")
        p = prices.get(ticker, {})
        price = float(p["price"]) if p.get("price") else s.get("current_price", "")
        holding = next((h for h in HOLDINGS if h["ticker"] == ticker), None)
        if holding and price:
            ret = ((float(str(price)) - holding["cost"]) / holding["cost"] * 100)
            ret_str = ("+" if ret >= 0 else "") + str(round(ret, 1)) + "% since cost"
            ret_color = "#16A34A" if ret >= 0 else "#DC2626"
        else:
            ret_str = "price unavailable"
            ret_color = "#9ca3af"
        rows += "<div style='margin-bottom:12px;background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,0.06)'>"
        rows += "<table style='width:100%;border-collapse:collapse;margin-bottom:12px'><tr>"
        rows += "<td><span style='font-size:15px;font-weight:700;color:#111'>" + ticker + "</span><span style='font-size:12px;color:#9ca3af;margin-left:8px'>" + company + "</span><span style='background:" + badge_bg + ";color:" + badge_color + ";font-size:10px;font-weight:600;padding:2px 8px;border-radius:20px;margin-left:8px'>" + badge_text + "</span></td>"
        rows += "<td style='text-align:right'><div style='font-family:monospace;font-size:16px;font-weight:700;color:#111'>$" + str(price) + "</div><div style='font-family:monospace;font-size:11px;color:" + ret_color + "'>" + ret_str + "</div></td>"
        rows += "</tr></table><p style='font-size:13px;color:#374151;line-height:1.75;margin:0'>" + paragraph + "</p></div>"
    idea = report.get("idea", {})
    idea_html = ""
    if idea:
        idea_html = "<div style='margin-bottom:24px'><div style='font-size:11px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#9ca3af;margin-bottom:12px'>Today's Top Idea</div>"
        idea_html += "<div style='background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:20px'>"
        idea_html += "<div style='font-size:14px;font-weight:700;color:#111;margin-bottom:4px'>" + idea.get("ticker","") + " &mdash; " + idea.get("company","") + "</div>"
        idea_html += "<div style='font-size:11px;color:#16A34A;font-weight:600;margin-bottom:10px'>High Conviction</div>"
        idea_html += "<p style='font-size:13px;color:#374151;line-height:1.75;margin:0'>" + idea.get("paragraph","") + "</p></div></div>"
    summary_html = "<div style='background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,0.06);margin-bottom:24px'>"
    summary_html += "<div style='font-size:11px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#9ca3af;margin-bottom:14px'>Portfolio Summary</div>"
    summary_html += "<table style='width:100%;border-collapse:collapse'><tr>"
    summary_html += "<td style='text-align:center;padding:8px'><div style='font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px'>Cost Basis</div><div style='font-family:monospace;font-size:17px;font-weight:700;color:#111'>$" + "{:,.0f}".format(total_cost) + "</div></td>"
    summary_html += "<td style='text-align:center;padding:8px;border-left:1px solid #f3f4f6'><div style='font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px'>Market Value</div><div style='font-family:monospace;font-size:17px;font-weight:700;color:#111'>$" + "{:,.0f}".format(total_value) + "</div></td>"
    summary_html += "<td style='text-align:center;padding:8px;border-left:1px solid #f3f4f6'><div style='font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px'>Unrealized P&amp;L</div><div style='font-family:monospace;font-size:17px;font-weight:700;color:" + pnl_color + "'>" + pnl_sign + "$" + "{:,.0f}".format(abs(total_pnl)) + "</div></td>"
    summary_html += "<td style='text-align:center;padding:8px;border-left:1px solid #f3f4f6'><div style='font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px'>Total Return</div><div style='font-family:monospace;font-size:17px;font-weight:700;color:" + pnl_color + "'>" + pnl_sign + str(round(total_pnl_pct, 1)) + "%</div></td>"
    summary_html += "</tr></table></div>"
    claude_url = build_claude_url(report, price_data)
    claude_btn = "<div style='text-align:center;margin-bottom:28px'><a href='" + claude_url + "' style='display:inline-block;background:#2563EB;color:#fff;font-size:13px;font-weight:600;padding:12px 28px;border-radius:8px;text-decoration:none'>&#x1F4AC; Ask Claude about this brief &rarr;</a><div style='font-size:11px;color:#9ca3af;margin-top:8px'>Opens Claude with your portfolio context pre-loaded</div></div>"
    outlook = report.get("summary", {}).get("outlook", "")
    body = "<!DOCTYPE html><html><head><meta charset='UTF-8'></head><body style='margin:0;padding:0;background:#f8f9fa;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif'>"
    body += "<div style='max-width:600px;margin:0 auto;padding:32px 16px'>"
    body += "<div style='margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid #e5e7eb'>"
    body += "<div style='font-size:11px;color:#9ca3af;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px'>" + date + "</div>"
    body += "<div style='font-size:26px;font-weight:700;color:#111;letter-spacing:-0.03em;margin-bottom:8px'>Your Portfolio Brief</div>"
    body += "<div style='font-size:14px;color:#4b5563;line-height:1.6'>" + outlook + "</div></div>"
    body += macro_html
    body += "<div style='font-size:11px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#9ca3af;margin-bottom:16px'>Holdings</div>"
    body += rows + idea_html + summary_html + claude_btn
    body += "<div style='text-align:center;font-size:11px;color:#9ca3af;line-height:1.8;padding-top:20px;border-top:1px solid #e5e7eb'>Portfolio Intelligence &nbsp;&middot;&nbsp; " + date + "<br><em>For research purposes only. Not financial advice.</em></div>"
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
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    today = datetime.now().strftime("%A, %B %d, %Y")
    print("Step 1: Fetching live prices from Yahoo Finance...")
    price_data = fetch_prices()
    print("Step 2: Waiting 60 seconds...")
    time.sleep(60)
    print("Step 3: Running AI research...")
    report = run_research(client, today, price_data)
    print("Step 4: Sending email...")
    html = build_email(report, price_data)
    subject = "Portfolio Brief - " + datetime.now().strftime("%b %d, %Y")
    send_email(html, subject)
    print("Done.")
