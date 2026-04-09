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
    """Pull live prices and daily changes directly from Yahoo Finance."""
    prices = {}
    print("Fetching prices from Yahoo Finance...")
    for h in HOLDINGS:
        ticker = h["ticker"]
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            price = round(float(info.last_price), 2)
            prev_close = round(float(info.previous_close), 2)
            change_dollar = round(price - prev_close, 2)
            change_pct = round((change_dollar / prev_close) * 100, 2) if prev_close else 0
            prices[ticker] = {
                "price": price,
                "prev_close": prev_close,
                "change_dollar": change_dollar,
                "change_pct": change_pct
            }
            sign = "+" if change_dollar >= 0 else ""
            print(ticker + ": $" + str(price) + " " + sign + "$" + str(change_dollar) + " (" + sign + str(change_pct) + "%)")
        except Exception as ex:
            print("Failed to get price for " + ticker + ": " + str(ex))
    return {"prices": prices}

def run_research(client, today, price_data):
    """Run AI research with confirmed prices. AI only searches for news and explanations."""
    prices = price_data.get("prices", {})

    # Build price context string for the prompt
    price_parts = []
    for h in HOLDINGS:
        p = prices.get(h["ticker"], {})
        if p.get("price"):
            chg_d = p.get("change_dollar", 0)
            chg_p = p.get("change_pct", 0)
            sign = "+" if chg_d >= 0 else ""
            price_parts.append(
                h["ticker"] + ": $" + str(p["price"]) +
                " (" + sign + "$" + str(chg_d) + " / " + sign + str(chg_p) + "% today)"
            )
    price_ctx = ", ".join(price_parts)

    # Build portfolio-level daily change summary for the prompt
    total_cost = sum(h["shares"] * h["cost"] for h in HOLDINGS)
    today_pnl = 0
    for h in HOLDINGS:
        p = prices.get(h["ticker"], {})
        if p.get("change_dollar") is not None:
            today_pnl += h["shares"] * p["change_dollar"]
    today_pct = round((today_pnl / total_cost) * 100, 2) if total_cost else 0
    today_sign = "+" if today_pnl >= 0 else ""

    h_parts = []
    for h in HOLDINGS:
        h_parts.append("- " + h["ticker"] + " (" + h["company"] + ", " + str(h["shares"]) + " shares, cost $" + str(h["cost"]) + ")")
    h_str = "\n".join(h_parts)

    prompt = (
        "You are a senior equity analyst. Today is " + today + ".\n"
        "CONFIRMED PRICES AND DAILY CHANGES from Yahoo Finance (do NOT search for prices):\n"
        + price_ctx + "\n\n"
        "PORTFOLIO DAILY MOVE: " + today_sign + "$" + str(round(today_pnl, 2)) +
        " (" + today_sign + str(today_pct) + "%) today\n\n"
        "HOLDINGS:\n" + h_str + "\n\n"
        "Use web search to find:\n"
        "1. What happened in the broad US market today (S&P 500, Nasdaq, Dow performance and the specific reasons why)\n"
        "2. Why each of the portfolio holdings moved the way they did today specifically\n"
        "3. News, analyst ratings, earnings, and macro commentary for each holding\n\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        "  \"market_summary\": \"2-8 sentences explaining what the S&P 500, Nasdaq, and Dow did today and WHY. Cite specific catalysts: Fed commentary, macro data releases, earnings, geopolitical events, sector rotation. If no clear driver exists, say 'no clear catalyst today'.\",\n"
        "  \"portfolio_summary\": \"2-8 sentences explaining why YOUR specific holdings moved the way they did today. Name which stocks led gains and which were the biggest drags. Give specific news or sector reasons for each notable mover. Compare the portfolio's overall move to the S&P 500.\",\n"
        "  \"macro\": {\"fed_rate\": \"...\", \"ten_year\": \"...\", \"vix\": \"...\", \"cpi\": \"...\"},\n"
        "  \"portfolio\": [\n"
        "    {\n"
        "      \"ticker\": \"NVDA\",\n"
        "      \"company\": \"NVIDIA Corp\",\n"
        "      \"sentiment\": \"bullish\",\n"
        "      \"current_price\": 174.88,\n"
        "      \"paragraph\": \"3-4 sentence research paragraph covering latest news, analyst views, and outlook\"\n"
        "    }\n"
        "  ],\n"
        "  \"idea\": {\"ticker\": \"...\", \"company\": \"...\", \"conviction\": \"High\", \"paragraph\": \"...\"}\n"
        "}"
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

def calc_portfolio_stats(price_data):
    """Calculate all portfolio-level numbers from yfinance data."""
    prices = price_data.get("prices", {})
    total_cost = 0
    total_value = 0
    today_pnl = 0

    for h in HOLDINGS:
        cost_total = h["shares"] * h["cost"]
        total_cost += cost_total
        p = prices.get(h["ticker"], {})
        if p.get("price"):
            value = h["shares"] * float(p["price"])
            total_value += value
            if p.get("change_dollar") is not None:
                today_pnl += h["shares"] * p["change_dollar"]
        else:
            total_value += cost_total

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0
    today_pct = (today_pnl / total_cost * 100) if total_cost else 0

    return {
        "total_cost": total_cost,
        "total_value": total_value,
        "total_pnl": total_pnl,
        "total_pnl_pct": round(total_pnl_pct, 1),
        "today_pnl": today_pnl,
        "today_pct": round(today_pct, 2)
    }

def build_claude_url(report, price_data):
    date = datetime.now().strftime("%B %d, %Y")
    prices = price_data.get("prices", {})
    lines = ["I just received my daily portfolio brief for " + date + ". Here is my portfolio context:", ""]
    for h in HOLDINGS:
        p = prices.get(h["ticker"], {})
        if p.get("price"):
            sign = "+" if p.get("change_dollar", 0) >= 0 else ""
            price_str = "$" + str(p["price"]) + " (" + sign + "$" + str(p.get("change_dollar","?")) + " today)"
        else:
            price_str = "price unavailable"
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
    stats = calc_portfolio_stats(price_data)

    # Colors and signs
    today_color = "#16A34A" if stats["today_pnl"] >= 0 else "#DC2626"
    total_color = "#16A34A" if stats["total_pnl"] >= 0 else "#DC2626"
    today_sign = "+" if stats["today_pnl"] >= 0 else ""
    total_sign = "+" if stats["total_pnl"] >= 0 else ""

    # ── DUAL SUMMARY BOXES ──────────────────────────────────────────────────
    market_summary = report.get("market_summary", "")
    portfolio_summary = report.get("portfolio_summary", "")

    summary_html = ""

    # Box 1: US Market Today
    if market_summary:
        summary_html += (
            "<div style='background:linear-gradient(135deg,#1B4B6B,#2E7FAB);border-radius:12px;padding:22px 24px;margin-bottom:12px'>"
            "<div style='font-size:10px;color:rgba(255,255,255,0.5);font-weight:600;letter-spacing:0.08em;text-transform:uppercase;margin-bottom:6px'>🌍 US Market Today</div>"
            "<div style='font-size:13px;color:rgba(255,255,255,0.9);line-height:1.75'>" + market_summary + "</div>"
            "</div>"
        )

    # Box 2: Your Portfolio Today
    if portfolio_summary:
        summary_html += (
            "<div style='background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:22px 24px;margin-bottom:24px'>"
            "<div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:10px'>"
            "<div style='font-size:10px;color:#9ca3af;font-weight:600;letter-spacing:0.08em;text-transform:uppercase'>💼 Your Portfolio Today</div>"
            "<div style='font-family:monospace;font-size:15px;font-weight:700;color:" + today_color + "'>"
            + today_sign + "$" + "{:,.0f}".format(abs(stats["today_pnl"])) +
            " (" + today_sign + str(stats["today_pct"]) + "%)"
            "</div>"
            "</div>"
            "<div style='font-size:13px;color:#374151;line-height:1.75'>" + portfolio_summary + "</div>"
            "</div>"
        )

    # ── MACRO PILLS ──────────────────────────────────────────────────────────
    macro_html = ""
    if m:
        macro_html = "<div style='margin-bottom:24px'>"
        for label, bg, color in [
            ("Fed " + m.get("fed_rate","--"), "#f3f4f6", "#374151"),
            ("10Y " + m.get("ten_year","--"), "#f3f4f6", "#374151"),
            ("VIX " + m.get("vix","--"), "#fef3c7", "#d97706"),
            ("CPI " + m.get("cpi","--"), "#f3f4f6", "#374151"),
        ]:
            if "--" not in label:
                macro_html += "<span style='background:" + bg + ";color:" + color + ";font-size:11px;font-weight:600;padding:4px 12px;border-radius:20px;margin-right:6px;margin-bottom:6px;display:inline-block'>" + label + "</span>"
        macro_html += "</div>"

    # ── STOCK CARDS ──────────────────────────────────────────────────────────
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

        # Always use confirmed Yahoo Finance price
        p = prices.get(ticker, {})
        price = float(p["price"]) if p.get("price") else s.get("current_price", "")
        chg_d = p.get("change_dollar", 0)
        chg_p = p.get("change_pct", 0)
        chg_sign = "+" if chg_d >= 0 else ""
        chg_color = "#16A34A" if chg_d >= 0 else "#DC2626"
        chg_arrow = "▲" if chg_d >= 0 else "▼"

        # Total return since cost
        holding = next((h for h in HOLDINGS if h["ticker"] == ticker), None)
        if holding and price:
            ret = ((float(str(price)) - holding["cost"]) / holding["cost"] * 100)
            ret_str = ("+" if ret >= 0 else "") + str(round(ret, 1)) + "% since cost"
            ret_color = "#16A34A" if ret >= 0 else "#DC2626"
        else:
            ret_str = ""
            ret_color = "#9ca3af"

        rows += "<div style='margin-bottom:12px;background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,0.06)'>"
        rows += "<table style='width:100%;border-collapse:collapse;margin-bottom:12px'><tr>"
        rows += "<td><span style='font-size:15px;font-weight:700;color:#111'>" + ticker + "</span>"
        rows += "<span style='font-size:12px;color:#9ca3af;margin-left:8px'>" + company + "</span>"
        rows += "<span style='background:" + badge_bg + ";color:" + badge_color + ";font-size:10px;font-weight:600;padding:2px 8px;border-radius:20px;margin-left:8px'>" + badge_text + "</span></td>"
        rows += "<td style='text-align:right'>"
        # Current price + today's change
        rows += "<div style='font-family:monospace;font-size:16px;font-weight:700;color:#111'>$" + str(price) + "</div>"
        rows += "<div style='font-family:monospace;font-size:12px;font-weight:600;color:" + chg_color + "'>"
        rows += chg_arrow + " " + chg_sign + "$" + str(abs(chg_d)) + " (" + chg_sign + str(chg_p) + "% today)</div>"
        rows += "<div style='font-family:monospace;font-size:11px;color:" + ret_color + ";margin-top:1px'>" + ret_str + "</div>"
        rows += "</td></tr></table>"
        rows += "<p style='font-size:13px;color:#374151;line-height:1.75;margin:0'>" + paragraph + "</p>"
        rows += "</div>"

    # ── TOP IDEA ─────────────────────────────────────────────────────────────
    idea = report.get("idea", {})
    idea_html = ""
    if idea:
        idea_html = (
            "<div style='margin-bottom:24px'>"
            "<div style='font-size:11px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#9ca3af;margin-bottom:12px'>Today's Top Idea</div>"
            "<div style='background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:20px'>"
            "<div style='font-size:14px;font-weight:700;color:#111;margin-bottom:4px'>" + idea.get("ticker","") + " &mdash; " + idea.get("company","") + "</div>"
            "<div style='font-size:11px;color:#16A34A;font-weight:600;margin-bottom:10px'>High Conviction</div>"
            "<p style='font-size:13px;color:#374151;line-height:1.75;margin:0'>" + idea.get("paragraph","") + "</p>"
            "</div></div>"
        )

    # ── PORTFOLIO SUMMARY BOX (Option B: today + total) ──────────────────────
    portfolio_box = (
        "<div style='background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,0.06);margin-bottom:24px'>"
        "<div style='font-size:11px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#9ca3af;margin-bottom:14px'>Portfolio Summary</div>"
        "<table style='width:100%;border-collapse:collapse'><tr>"
        "<td style='text-align:center;padding:8px'>"
        "<div style='font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px'>Cost Basis</div>"
        "<div style='font-family:monospace;font-size:17px;font-weight:700;color:#111'>$" + "{:,.0f}".format(stats["total_cost"]) + "</div>"
        "</td>"
        "<td style='text-align:center;padding:8px;border-left:1px solid #f3f4f6'>"
        "<div style='font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px'>Market Value</div>"
        "<div style='font-family:monospace;font-size:17px;font-weight:700;color:#111'>$" + "{:,.0f}".format(stats["total_value"]) + "</div>"
        "</td>"
        "<td style='text-align:center;padding:8px;border-left:1px solid #f3f4f6'>"
        "<div style='font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px'>Today's P&amp;L</div>"
        "<div style='font-family:monospace;font-size:17px;font-weight:700;color:" + today_color + "'>"
        + today_sign + "$" + "{:,.0f}".format(abs(stats["today_pnl"])) +
        " (" + today_sign + str(stats["today_pct"]) + "%)</div>"
        "</td>"
        "<td style='text-align:center;padding:8px;border-left:1px solid #f3f4f6'>"
        "<div style='font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:4px'>Total Return</div>"
        "<div style='font-family:monospace;font-size:17px;font-weight:700;color:" + total_color + "'>"
        + total_sign + "$" + "{:,.0f}".format(abs(stats["total_pnl"])) +
        " (" + total_sign + str(stats["total_pnl_pct"]) + "%)</div>"
        "</td>"
        "</tr></table>"
        "</div>"
    )

    # ── ASK CLAUDE BUTTON ─────────────────────────────────────────────────────
    claude_url = build_claude_url(report, price_data)
    claude_btn = (
        "<div style='text-align:center;margin-bottom:28px'>"
        "<a href='" + claude_url + "' style='display:inline-block;background:#2563EB;color:#fff;font-size:13px;font-weight:600;padding:12px 28px;border-radius:8px;text-decoration:none'>&#x1F4AC; Ask Claude about this brief &rarr;</a>"
        "<div style='font-size:11px;color:#9ca3af;margin-top:8px'>Opens Claude with your portfolio context pre-loaded</div>"
        "</div>"
    )

    # ── ASSEMBLE ──────────────────────────────────────────────────────────────
    body = "<!DOCTYPE html><html><head><meta charset='UTF-8'></head>"
    body += "<body style='margin:0;padding:0;background:#f8f9fa;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif'>"
    body += "<div style='max-width:600px;margin:0 auto;padding:32px 16px'>"

    # Header
    body += (
        "<div style='margin-bottom:24px;padding-bottom:20px;border-bottom:1px solid #e5e7eb'>"
        "<div style='font-size:11px;color:#9ca3af;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px'>" + date + "</div>"
        "<div style='font-size:26px;font-weight:700;color:#111;letter-spacing:-0.03em;margin-bottom:0'>Your Portfolio Brief</div>"
        "</div>"
    )

    body += summary_html
    body += macro_html
    body += "<div style='font-size:11px;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;color:#9ca3af;margin-bottom:16px'>Holdings</div>"
    body += rows
    body += idea_html
    body += portfolio_box
    body += claude_btn
    body += (
        "<div style='text-align:center;font-size:11px;color:#9ca3af;line-height:1.8;padding-top:20px;border-top:1px solid #e5e7eb'>"
        "Portfolio Intelligence &nbsp;&middot;&nbsp; " + date + "<br>"
        "<em>For research purposes only. Not financial advice.</em>"
        "</div>"
    )
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
