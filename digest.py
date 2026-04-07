#!/usr/bin/env python3
import os, json, anthropic, smtplib, time
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

def run_research():
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    today = datetime.now().strftime("%A, %B %d, %Y")
    tickers = [h["ticker"] for h in HOLDINGS]
    ticker_str = ", ".join(tickers)

    price_prompt = (
        "Today is " + today + ". Use web search to find the current trading price for EACH of these tickers: "
        + ticker_str + ". "
        "Search for each one. Include ETFs and mutual funds. "
        "Return ONLY a JSON object with no extra text: "
        "{\"prices\": {\"NVDA\": {\"price\": 177.39, \"change_pct\": -0.93}, "
        "\"CEG\": {\"price\": 301.49, \"change_pct\": -2.38}, "
        "\"FNDE\": {\"price\": 38.26, \"change_pct\": 0.03}, "
        "\"QQQ\": {\"price\": 588.50, \"change_pct\": 0.11}, "
        "\"CGGR\": {\"price\": 40.41, \"change_pct\": -0.47}, "
        "\"QTUM\": {\"price\": 109.96, \"change_pct\": 0.61}, "
        "\"SWEGX\": {\"price\": 26.30, \"change_pct\": -0.04}}}"
    )

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
        if not isinstance(d, dict):
            continue
        chg = d.get("change_pct") or 0
        sign = "+" if chg >= 0 else ""
        price_parts.append(t + ": $" + str(d.get("price", "?")) + " (" + sign + str(chg) + "%)")
    price_ctx = ", ".join(price_parts)

    h_parts = []
    for h in HOLDINGS:
        h_parts.append("- " + h["ticker"] + " (" + h["company"] + ", " + str(h["shares"]) + " shares, cost $" + str(h["cost"]) + ")")
    h_str = "\n".join(h_parts)

    print("Waiting 90 seconds to avoid rate limit...")
    time.sleep(90)

    research_prompt = (
        "Senior equity analyst. Today: " + today + ".\n"
        "CONFIRMED PRICES: " + price_ctx + "\n"
        "PORTFOLIO:\n" + h_str + "\n\n"
        "Use the confirmed prices above for current_price fields - do not search for prices again. "
        "For each holding write a 3-4 sentence research paragraph covering news, analyst views, and outlook. "
        "Also provide exactly ONE best investment idea. "
        "Return ONLY JSON: {\"summary\":{\"outlook\":\"...\"},"
        "\"macro\":{\"fed_rate\":\"...\",\"ten_year\":\"...\",\"vix\":\"...\",\"cpi\":\"...\"},"
        "\"portfolio\":[{\"ticker\":\"NVDA\",\"sentiment\":\"bullish\",\"current_price\":177.39,\"company\":\"NVIDIA\",\"paragraph\":\"...\"}],"
        "\"idea\":{\"ticker\":\"...\",\"company\":\"...\",\"conviction\":\"High\",\"paragraph\":\"...\"}}"
    )

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

def build_claude_url(report, price_data):
    date = datetime.now().strftime("%B %d, %Y")
    prices = price_data.get("prices", {})
    lines = ["I just received my daily portfolio brief for " + date + ". Here is my portfolio context:"]
    lines.append("")
    for h in HOLDINGS:
        p = prices.get(h["ticker"], {})
        if isinstance(p, dict) and p.get("price"):
            price_str = "$" + str(p.get("price"))
        else:
            price_str = "price unavailable"
        lines.append("- " + h["ticker"] + " (" + h["company"] + "): " + str(h["shares"]) + " shares, cost $" + str(h["cost"]) + ", current " + price_str)
    m = report.get("macro", {})
    if m:
        lines.append("")
        lines.append("Macro: Fed Rate " + m.get("fed_rate", "--") + ", 10Y " + m.get("ten_year", "--") + ", VIX " + m.get("vix", "--") + ", CPI " + m.get("cpi", "--"))
    lines.append("")
    lines.append("Please help me think through any questions I have about this brief.")
    prompt = "\n".join(lines)
    return "https://claude.ai/new?q=" + quote(prompt)

def build_email(report, price_data):
    r = report
    date = datetime.now().strftime("%A, %B %d, %Y")
    m = r.get("macro", {})
    prices = price_data.get("prices", {})

    # Portfolio summary - only use real prices
    total_cost = 0
    total_value = 0
    priced_count = 0
    for h in HOLDINGS:
        cost_total = h["shares"] * h["cost"]
        total_cost += cost_total
        p = prices.get(h["ticker"], {})
        if isinstance(p, dict) and p.get("price"):
            current_price = float(p.get("price"))
            total_value += h["shares"] * current_price
            priced_count += 1
        else:
            # Fall back to portfolio stock data if available
            stock = next((s for s in r.get("portfolio", []) if s.get("ticker") == h["ticker"]), None)
            if stock and stock.get("current_price"):
                current_price = float(stock.get("current_price"))
                total_value += h["shares"] * current_price
                priced_count += 1
            else:
                total_value += cost_total

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
    pnl_color = "#16A34A" if total_pnl >= 0 else "#DC2626"
    pnl_sign = "+" if total_pnl >= 0 else ""

    claude_url = build_claude_url(report, price_data)

    # Macro pills
    macro_html = ""
    if m:
        macro_html = "<div style='margin-bottom:24px'>"
        pills = [
            ("Fed " + m.get("fed_rate", "--"), "#f3f4f6", "#374151"),
            ("10Y " + m.get("ten_year", "--"), "#f3f4f6", "#374151"),
            ("VIX " + m.get("vix", "--"), "#fef3c7", "#d97706"),
            ("CPI " + m.get("cpi", "--"), "#f3f4f6", "#374151"),
        ]
        for label, bg, color in pills:
            if "--" not in label:
                macro_html += "<span style='background:" + bg + ";color:" + color + ";font-size:11px;font-weight:600;padding:4px 12px;border-radius:20px;margin-right:6px;margin-bottom:6px;display:inline-block'>" + label + "</span>"
        macro_html += "</div>"

    # Stock cards
    rows = ""
    for s in r.get("portfolio", []):
        sent = s.get("sentiment", "neutral")
        if sent == "bullish":
            badge_bg, badge_color, badge_text = "#dcfce7", "#15803d", "BULLISH"
        elif sent == "bearish":
            badge_bg, badge_color, badge_text = "#fee2e2", "#dc2626", "BEARISH"
        else:
            badge_bg, badge_color, badge_text = "#fef3c7", "#d97706", "NEUTRAL"

        ticker = s.get("ticker", "")
        company = s.get("company", "")
        price = s.get("current_price", "")
        paragraph = s.get("paragraph", "")

        # Override with confirmed price if available
        p = prices.get(ticker, {})
        if isinstance(p, dict) and p.get("price"):
            price = p.get("price")

        holding = next((h for h in HOLDINGS if h["ticker"] == ticker), None)
        if holding and price and float(str(price)) != holding["cost"]:
            ret = ((float(str(price)) - holding["cost"]) / holding["cost"] * 100)
            ret_str = ("+" if ret >= 0 else "") + str(round(ret, 1)) + "% since cost"
            ret_color = "#16A34A" if ret >= 0 else "#DC2626"
        else:
            ret_str = "price pending"
            ret_color = "#9ca3af"

        rows += "<div style='margin-bottom:12px;background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,0.06)'>"
        rows += "<table style='width:100%;border-collapse:collapse;margin-bottom:12px'><tr>"
        rows += "<td><span style='font-size:15px;font-weight:700;color:#111'>" + ticker + "</span>"
        rows += "<span style='font-size:12px;color:#9ca3af;margin-left:8px'>" + company + "</span>"
        rows += "<span style='background:" + badge_bg + ";color:" + badge_color + ";font-size:10px;font-weight:600;padding:2px 8px;border-radius:20px;margin-left:8px'>" + badge_text + "</span></td>"
        rows += "<td style='text-align:right'>"
        rows += "<div style='font-family:monospace;font-size:16px;font-weight:700;color:#111'>$" + str(price) + "</div>"
        rows += "<div style='font-family:monospace;font-size:11px;color:" + ret_color + "'>" + ret_str + "</div>"
        rows += "</td></tr></table>"
        rows += "<p style='font-size:13px;color:#374151;line-height:1.75;margin:0'>" + paragraph + "</p>"
        rows += "</div>"

    # Single idea
    idea = r.get("idea", {})
    idea_html = ""
    if idea:
        idea_html = "<div style='margin-bottom:24px'>"
        idea_html += "<div style='font-size:11px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#9ca3af;margin-bottom:12px'>Today's Top Idea</div>"
        idea_html += "<div style='background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:20px'>"
        idea_html += "<div style='font-size:14px;font-weight:700;color:#111;margin-bottom:4px'>" + idea.get("ticker", "") + " &mdash; " + idea.get("company", "") + "</div>"
        idea_html += "<div style='font-size:11px;color:#16A34A;font-weight:600;margin-bottom:10px'>High Conviction</div>"
        idea_html += "<p style='font-size:13px;color:#374151;line-height:1.75;margin:0'>" + idea.get("paragraph", "") + "</p>"
        idea_html += "</div></div>"

    # Portfolio summary
    summary_html = "<div style='background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,0.06);margin-bottom:24px'>"
    summary_html += "<div style='font-size:11px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#9ca3af;margin-bottom:14px'>Portfolio Summary</div>"
    summary_html += "<table style='width:100%;border-collapse:collapse'><tr>"
    summary_html += "<td style='text-align:center;padding:8px'><div style='font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px'>Cost Basis</div><div style='font-family:monospace;font-size:17px;font-weight:700;color:#111'>$" + "{:,.0f}".format(total_cost) + "</div></td>"
    summary_html += "<td style='text-align:center;padding:8px;border-left:1px solid #f3f4f6'><div style='font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px'>Market Value</div><div style='font-family:monospace;font-size:17px;font-weight:700;color:#111'>$" + "{:,.0f}".format(total_value) + "</div></td>"
    summary_html += "<td style='text-align:center;padding:8px;border-left:1px solid #f3f4f6'><div style='font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px'>Unrealized P&amp;L</div><div style='font-family:monospace;font-size:17px;font-weight:700;color:" + pnl_color + "'>" + pnl_sign + "$" + "{:,.0f}".format(abs(total_pnl)) + "</div></td>"
    summary_html += "<td style='text-align:center;padding:8px;border-left:1px solid #f3f4f6'><div style='font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px'>Total Return</div><div style='font-family:monospace;font-size:17px;font-weight:700;color:" + pnl_color + "'>" + pnl_sign + str(round(total_pnl_pct, 1)) + "%</div></td>"
    summary_html += "</tr></table></div>"

    # Ask Claude button
    claude_btn = "<div style='text-align:center;margin-bottom:28px'>"
    claude_btn += "<a href='" + claude_url + "' style='display:inline-block;background:#2563EB;color:#fff;font-size:13px;font-weight:600;padding:12px 28px;border-radius:8px;text-decoration:none;letter-spacing:-0.01em'>&#x1F4AC; Ask Claude about this brief &rarr;</a>"
    claude_btn += "<div style='font-size:11px;color:#9ca3af;margin-top:8px'>Opens Claude with your portfolio context pre-loaded</div>"
    claude_btn += "</div>"

    outlook = r.get("summary", {}).get("outlook", "")

    body = "<!DOCTYPE html><html><head><meta charset='UTF-8'></head>"
    body += "<body style='margin:0;padding:0;background:#f8f9fa;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif'>"
    body += "<div style='max-width:600px;margin:0 auto;padding:32px 16px'>"
    body += "<div style='margin-bottom:28px;padding-bottom:20px;border-bottom:1px solid #e5e7eb'>"
    body += "<div style='font-size:11px;color:#9ca3af;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px'>" + date + "</div>"
    body += "<div style='font-size:26px;font-weight:700;color:#111;letter-spacing:-0.03em;margin-bottom:8px'>Your Portfolio Brief</div>"
    body += "<div style='font-size:14px;color:#4b5563;line-height:1.6'>" + outlook + "</div>"
    body += "</div>"
    body += macro_html
    body += "<div style='font-size:11px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#9ca3af;margin-bottom:16px'>Holdings</div>"
    body += rows
    body += idea_html
    body += summary_html
    body += claude_btn
    body += "<div style='text-align:center;font-size:11px;color:#9ca3af;line-height:1.8;padding-top:20px;border-top:1px solid #e5e7eb'>"
    body += "Portfolio Intelligence &nbsp;&middot;&nbsp; " + date + "<br>"
    body += "<em>For research purposes only. Not financial advice.</em>"
    body += "</div></div></body></html>"
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
