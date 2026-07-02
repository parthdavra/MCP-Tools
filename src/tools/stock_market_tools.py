from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

import yfinance as yf


PROJECT_ID = "stock-market-agent"

TOP_10_STOCKS = ["AAPL", "MSFT", "NVDA", "META", "AMZN", "GOOGL", "AVGO", "TSLA", "COST", "NFLX"]

COMPANY_NAME_TO_TICKER = {
    "apple": "AAPL",
    "apple inc": "AAPL",
    "amazon": "AMZN",
    "amazon.com": "AMZN",
    "amazon com": "AMZN",
    "microsoft": "MSFT",
    "meta": "META",
    "facebook": "META",
    "nvidia": "NVDA",
    "nvdia": "NVDA",
    "alphabet": "GOOGL",
    "google": "GOOGL",
    "tesla": "TSLA",
    "broadcom": "AVGO",
    "costco": "COST",
    "netflix": "NFLX",
    "walmart": "WMT",
    "walmart inc": "WMT",
    "target": "TGT",
    "target corporation": "TGT",
    "pepsico": "PEP",
    "pepsi": "PEP",
    "cisco": "CSCO",
    "cisco systems": "CSCO",
    "csx": "CSX",
    "csx corporation": "CSX",
}

SECTOR_USER_BLUEPRINTS = [
    ("technology", "aggressive", "AI, cloud, semiconductors, and software growth", ["AAPL", "MSFT", "NVDA", "AVGO"]),
    ("consumer defensive", "balanced", "stable retail, groceries, and essential consumer demand", ["WMT", "COST", "PEP", "PG"]),
    ("healthcare", "balanced", "large-cap healthcare, devices, and pharmaceutical exposure", ["UNH", "JNJ", "LLY", "MRK"]),
    ("financial services", "balanced", "banks, payment networks, and diversified financials", ["JPM", "BAC", "V", "MA"]),
    ("energy", "moderate", "oil, gas, and energy cash-flow opportunities", ["XOM", "CVX", "COP", "SLB"]),
    ("communication services", "aggressive", "digital advertising, streaming, and connectivity growth", ["GOOGL", "META", "NFLX", "TMUS"]),
    ("consumer cyclical", "aggressive", "e-commerce, autos, travel, and discretionary spending", ["AMZN", "TSLA", "HD", "MCD"]),
    ("industrials", "balanced", "transport, aerospace, machinery, and infrastructure", ["CAT", "BA", "UPS", "CSX"]),
    ("utilities", "conservative", "dividend-focused regulated utilities and stable cash flow", ["NEE", "DUK", "SO", "AEP"]),
    ("real estate", "moderate", "REIT income and property-sector diversification", ["PLD", "AMT", "EQIX", "O"]),
]

DIVERSIFIED_STOCK_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AVGO", "WMT", "COST", "PEP", "PG", "UNH", "JNJ",
    "LLY", "MRK", "JPM", "BAC", "V", "MA", "XOM", "CVX", "COP", "SLB",
    "GOOGL", "META", "NFLX", "TMUS", "AMZN", "TSLA", "HD", "MCD", "CAT", "BA",
    "UPS", "CSX", "NEE", "DUK", "SO", "AEP", "PLD", "AMT", "EQIX", "O",
]

SEED_DISPLAY_NAMES = [
    "Aarav Patel", "Sophia Johnson", "Liam Smith", "Maya Rodriguez", "Noah Williams",
    "Emma Brown", "Ethan Davis", "Olivia Wilson", "Lucas Martinez", "Ava Anderson",
    "Mason Thomas", "Isabella Taylor", "Logan Moore", "Mia Jackson", "James Martin",
    "Charlotte Lee", "Benjamin Harris", "Amelia Clark", "Henry Lewis", "Harper Walker",
    "Alexander Hall", "Evelyn Allen", "Daniel Young", "Abigail King", "Michael Wright",
    "Emily Scott", "Sebastian Green", "Elizabeth Adams", "Jack Baker", "Sofia Gonzalez",
    "William Nelson", "Grace Carter", "David Mitchell", "Chloe Perez", "Joseph Roberts",
    "Victoria Turner", "Samuel Phillips", "Aria Campbell", "Matthew Parker", "Ella Evans",
    "John Edwards", "Layla Collins", "Anthony Stewart", "Scarlett Sanchez",
    "Christopher Morris", "Zoey Rogers", "Andrew Reed", "Nora Cook", "Joshua Morgan",
    "Lily Bell",
]


@dataclass
class Quote:
    ticker: str
    company_name: str | None
    price: float | None
    previous_close: float | None
    currency: str
    market_cap: int | None
    sector: str | None
    industry: str | None


def build_seed_users() -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    users: dict[str, dict[str, Any]] = {
        "demo-user": {
            "user_id": "demo-user",
            "display_name": "Demo User",
            "sector": "technology",
            "risk_profile": "balanced",
            "investment_goal": "long-term growth",
            "watchlist": TOP_10_STOCKS,
        }
    }
    portfolios: dict[str, list[dict[str, Any]]] = {
        "demo-user": [
            {"ticker": ticker, "quantity": index + 4, "average_buy_price": float(100 + index * 20)}
            for index, ticker in enumerate(TOP_10_STOCKS, start=1)
        ]
    }

    for sector_index, (sector, risk_profile, goal, watchlist) in enumerate(SECTOR_USER_BLUEPRINTS, start=1):
        sector_slug = re.sub(r"[^a-z0-9]+", "-", sector.lower()).strip("-")
        for investor_index in range(1, 6):
            user_number = ((sector_index - 1) * 5) + investor_index
            user_id = f"user-{sector_slug}-{investor_index:03d}"
            universe_offset = (user_number - 1) % len(DIVERSIFIED_STOCK_UNIVERSE)
            rotated_universe = DIVERSIFIED_STOCK_UNIVERSE[universe_offset:] + DIVERSIFIED_STOCK_UNIVERSE[:universe_offset]
            diversified_watchlist = list(dict.fromkeys([*watchlist, *rotated_universe]))[:10]
            rotated_watchlist = diversified_watchlist[investor_index - 1:] + diversified_watchlist[: investor_index - 1]
            users[user_id] = {
                "user_id": user_id,
                "display_name": SEED_DISPLAY_NAMES[user_number - 1],
                "sector": sector,
                "risk_profile": risk_profile,
                "investment_goal": f"{goal}; profile #{user_number:02d}",
                "watchlist": rotated_watchlist,
            }
            portfolios[user_id] = [
                {
                    "ticker": ticker,
                    "quantity": 4 + investor_index + ticker_index,
                    "average_buy_price": float(80 + (sector_index * 9) + (ticker_index * 17)),
                }
                for ticker_index, ticker in enumerate(rotated_watchlist, start=1)
            ]
    return users, portfolios


SEED_USERS, SEED_PORTFOLIOS = build_seed_users()


def extract_tickers_or_company_names(text: str) -> list[str]:
    normalized = text.lower()
    matched: list[tuple[int, str]] = []
    for company_name, ticker in sorted(COMPANY_NAME_TO_TICKER.items(), key=lambda item: len(item[0]), reverse=True):
        match = re.search(rf"\b{re.escape(company_name)}\b", normalized)
        if match:
            matched.append((match.start(), ticker))
    for token in re.findall(r"\b[A-Z]{1,5}\b", text):
        if token not in {"A", "I", "AM", "IS", "IT", "THE", "USA", "PDF", "RAG", "MCP", "AWS", "API"}:
            token_match = re.search(rf"\b{re.escape(token)}\b", text)
            matched.append((token_match.start() if token_match else 0, token))
    unique: list[str] = []
    for _, ticker in sorted(matched, key=lambda item: item[0]):
        if ticker not in unique:
            unique.append(ticker)
    return unique


def resolve_ticker_or_company(text: str) -> str:
    tickers = extract_tickers_or_company_names(text)
    if tickers:
        return tickers[0]
    cleaned = re.sub(
        r"\b(stock price|share price|current price|price|stock|shares|quote|what is|show me|can i buy|should i buy|the|please)\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[^A-Za-z0-9 .,&-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.upper() if cleaned else text.upper()


def get_quote(ticker: str) -> Quote:
    stock = yf.Ticker(ticker)
    info: dict[str, Any] = {}
    fast_info: dict[str, Any] = {}
    try:
        info = stock.get_info() or {}
    except Exception:
        info = {}
    try:
        fast_info = dict(stock.fast_info or {})
    except Exception:
        fast_info = {}
    price = info.get("currentPrice") or info.get("regularMarketPrice") or fast_info.get("last_price") or fast_info.get("lastPrice")
    previous_close = info.get("previousClose") or info.get("regularMarketPreviousClose") or fast_info.get("previous_close") or fast_info.get("previousClose")
    return Quote(
        ticker=ticker.upper(),
        company_name=info.get("longName") or info.get("shortName"),
        price=float(price) if price is not None else None,
        previous_close=float(previous_close) if previous_close is not None else None,
        currency=info.get("currency") or fast_info.get("currency") or "USD",
        market_cap=info.get("marketCap") or fast_info.get("market_cap"),
        sector=info.get("sector"),
        industry=info.get("industry"),
    )


def format_money(value: float | int | None, currency: str = "USD") -> str:
    if value is None:
        return "not available"
    if abs(value) >= 1_000_000_000_000:
        return f"{currency} {value / 1_000_000_000_000:.2f}T"
    if abs(value) >= 1_000_000_000:
        return f"{currency} {value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{currency} {value / 1_000_000:.2f}M"
    return f"{currency} {value:,.2f}"


def risk_alerts_for_portfolio(holdings: list[dict[str, Any]], quotes: dict[str, Quote]) -> list[str]:
    values: dict[str, float] = {}
    costs: dict[str, float] = {}
    sectors: dict[str, float] = {}
    missing: list[str] = []
    for holding in holdings:
        ticker = str(holding["ticker"]).upper()
        quote = quotes.get(ticker)
        price = quote.price if quote else None
        if price is None:
            missing.append(ticker)
        quantity = float(holding["quantity"])
        cost = quantity * float(holding["average_buy_price"])
        value = quantity * float(price or 0)
        costs[ticker] = cost
        values[ticker] = value
        sector = quote.sector if quote and quote.sector else "Unknown sector"
        sectors[sector] = sectors.get(sector, 0) + value
    total_value = sum(values.values())
    total_cost = sum(costs.values())
    if total_value <= 0:
        return ["Portfolio value cannot be calculated because prices are unavailable."]
    alerts: list[str] = []
    if missing:
        alerts.append(f"Data quality alert: live prices were unavailable for {', '.join(missing)}.")
    for ticker, value in values.items():
        weight = (value / total_value) * 100
        gain_loss_percent = ((value - costs[ticker]) / costs[ticker] * 100) if costs[ticker] else 0
        if weight > 35:
            alerts.append(f"High concentration alert: {ticker} is {weight:.1f}% of the portfolio.")
        elif weight > 25:
            alerts.append(f"Moderate concentration alert: {ticker} is {weight:.1f}% of the portfolio.")
        if gain_loss_percent <= -20:
            alerts.append(f"Loss alert: {ticker} is down {gain_loss_percent:.1f}% versus average buy price.")
        elif gain_loss_percent <= -10:
            alerts.append(f"Watch alert: {ticker} is down {gain_loss_percent:.1f}% versus average buy price.")
    for sector, sector_value in sectors.items():
        sector_weight = (sector_value / total_value) * 100
        if sector_weight > 60:
            alerts.append(f"Sector concentration alert: {sector} represents {sector_weight:.1f}% of portfolio value.")
    total_gain_loss_percent = ((total_value - total_cost) / total_cost * 100) if total_cost else 0
    if total_gain_loss_percent <= -10:
        alerts.append(f"Portfolio drawdown alert: total unrealized return is {total_gain_loss_percent:.1f}%.")
    if not alerts:
        alerts.append("No major concentration, sector, or unrealized-loss risk alert found from current data.")
    return alerts


def classify_risk_alert(alert: str) -> dict[str, str]:
    normalized = alert.lower()
    if any(word in normalized for word in ["high concentration", "loss alert", "drawdown"]):
        severity = "high"
    elif any(word in normalized for word in ["moderate", "sector concentration", "watch alert", "data quality"]):
        severity = "medium"
    elif "no major" in normalized:
        severity = "low"
    else:
        severity = "info"
    return {"severity": severity, "message": alert}


def register_stock_market_tools(mcp: Any) -> None:
    @mcp.tool()
    def list_investment_users(sector: str | None = None) -> dict[str, Any]:
        """List the 50 seeded Stock Market Agent users, optionally filtered by sector."""
        users = [user for user_id, user in sorted(SEED_USERS.items()) if user_id != "demo-user"]
        if sector:
            users = [user for user in users if sector.lower() in user.get("sector", "").lower()]
        return {"answer": f"Returned {len(users)} seeded investment users.", "users": users, "sources": ["MCP seed users"]}

    @mcp.tool()
    def get_user_watchlist(user_id: str) -> dict[str, Any]:
        """Get one Stock Market Agent user's 10-stock watchlist."""
        user = SEED_USERS.get(user_id)
        watchlist = user.get("watchlist", []) if user else []
        return {
            "answer": f"Your watchlist contains: {', '.join(watchlist)}." if watchlist else f"No watchlist found for `{user_id}`.",
            "user_id": user_id,
            "watchlist": watchlist,
            "sources": ["MCP seed users"],
        }

    @mcp.tool()
    def user_context(user_id: str, question: str) -> dict[str, Any]:
        """Return Stock Market Agent user profile, watchlist, and risk preference."""
        user = SEED_USERS.get(user_id)
        if not user:
            return {"answer": f"No seeded user found for `{user_id}`.", "user_id": user_id, "watchlist": []}
        if "watchlist" in question.lower():
            answer = f"Your watchlist contains: {', '.join(user['watchlist'])}."
        else:
            answer = f"{user['display_name']} ({user_id}) has a {user['risk_profile']} risk profile and focuses on {user['sector']}."
        return {**user, "answer": answer, "sources": ["MCP seed users"]}

    @mcp.tool()
    def get_stock_quote(ticker_or_company: str) -> dict[str, Any]:
        """Get a live quote for a ticker or company name."""
        ticker = resolve_ticker_or_company(ticker_or_company)
        quote = get_quote(ticker)
        return {
            "answer": (
                f"{quote.ticker} — {quote.company_name or 'Company name unavailable'}\n"
                f"Price: {format_money(quote.price, quote.currency)}\n"
                f"Previous close: {format_money(quote.previous_close, quote.currency)}"
            ),
            "quote": asdict(quote),
            "sources": ["Yahoo Finance via yfinance"],
        }

    @mcp.tool()
    def stock_research(question: str) -> dict[str, Any]:
        """Answer stock price, detail, and comparison questions."""
        tickers = extract_tickers_or_company_names(question)
        if not tickers:
            tickers = [resolve_ticker_or_company(question)]
        quotes = [get_quote(ticker) for ticker in tickers]
        sections = []
        for quote in quotes:
            change_text = "change not available"
            if quote.price is not None and quote.previous_close not in (None, 0):
                change = ((quote.price - quote.previous_close) / quote.previous_close) * 100
                change_text = f"{change:+.2f}% vs previous close"
            sections.append(
                "\n".join(
                    [
                        f"{quote.ticker} — {quote.company_name or 'Company name unavailable'}",
                        f"- Price: {format_money(quote.price, quote.currency)}",
                        f"- Previous close: {format_money(quote.previous_close, quote.currency)}",
                        f"- Daily change: {change_text}",
                        f"- Market cap: {format_money(quote.market_cap, quote.currency)}",
                        f"- Sector: {quote.sector or 'not available'}",
                        f"- Industry: {quote.industry or 'not available'}",
                    ]
                )
            )
        return {
            "answer": ("Stock comparison:\n\n" if len(quotes) > 1 else "Stock details:\n\n") + "\n\n".join(sections),
            "tickers": [quote.ticker for quote in quotes],
            "quotes": [asdict(quote) for quote in quotes],
            "sources": ["Yahoo Finance via yfinance"],
        }

    @mcp.tool()
    def compare_stocks(question: str) -> dict[str, Any]:
        """Compare two or more stocks requested in natural language."""
        return stock_research(question)

    @mcp.tool()
    def portfolio_analysis(user_id: str, question: str = "analyze my portfolio") -> dict[str, Any]:
        """Analyze user portfolio value, allocation, gain/loss, and risk alerts."""
        holdings = SEED_PORTFOLIOS.get(user_id, [])
        if not holdings:
            return {"answer": f"No portfolio holdings found for `{user_id}`.", "total_value": 0, "risk_alerts": [], "holdings": []}
        tickers = [str(holding["ticker"]).upper() for holding in holdings]
        quotes = {ticker: get_quote(ticker) for ticker in tickers}
        rows: list[dict[str, Any]] = []
        total_value = 0.0
        total_cost = 0.0
        for holding in holdings:
            ticker = str(holding["ticker"]).upper()
            quantity = float(holding["quantity"])
            average_buy_price = float(holding["average_buy_price"])
            quote = quotes[ticker]
            current_price = float(quote.price or 0)
            market_value = quantity * current_price
            cost_value = quantity * average_buy_price
            gain_loss = market_value - cost_value
            total_value += market_value
            total_cost += cost_value
            rows.append(
                {
                    "ticker": ticker,
                    "quantity": quantity,
                    "average_buy_price": average_buy_price,
                    "current_price": current_price,
                    "market_value": market_value,
                    "gain_loss": gain_loss,
                }
            )
        alerts = risk_alerts_for_portfolio(holdings, quotes)
        total_gain_loss = total_value - total_cost
        total_gain_loss_percent = (total_gain_loss / total_cost * 100) if total_cost else 0
        return {
            "answer": (
                "Portfolio analysis:\n"
                f"- Total value: {format_money(total_value)}\n"
                f"- Total gain/loss: {format_money(total_gain_loss)} ({total_gain_loss_percent:+.2f}%)\n\n"
                "Risk alerts:\n" + "\n".join(f"- {alert}" for alert in alerts)
            ),
            "total_value": total_value,
            "total_gain_loss": total_gain_loss,
            "total_gain_loss_percent": total_gain_loss_percent,
            "holdings": rows,
            "risk_alerts": alerts,
            "risk_alert_details": [classify_risk_alert(alert) for alert in alerts],
            "sources": ["MCP seed users", "Yahoo Finance via yfinance"],
        }

    @mcp.tool()
    def stock_performance_analysis(question: str, investment_amount: float = 1000.0) -> dict[str, Any]:
        """Return real 5-year monthly stock performance using Yahoo Finance history."""
        tickers = extract_tickers_or_company_names(question) or [resolve_ticker_or_company(question)]
        sections: list[str] = []
        histories: dict[str, list[dict[str, Any]]] = {}

        for ticker in tickers:
            quote = get_quote(ticker)
            try:
                history = yf.Ticker(quote.ticker).history(period="5y", interval="1mo", auto_adjust=False)
            except Exception as exc:
                sections.append(
                    f"{quote.ticker} — {quote.company_name or 'Company name unavailable'}\n"
                    f"- Current price: {format_money(quote.price, quote.currency)}\n"
                    f"- 5-year monthly history unavailable from Yahoo Finance: {exc}"
                )
                histories[quote.ticker] = []
                continue

            if history is None or history.empty or "Close" not in history.columns:
                sections.append(
                    f"{quote.ticker} — {quote.company_name or 'Company name unavailable'}\n"
                    f"- Current price: {format_money(quote.price, quote.currency)}\n"
                    "- 5-year monthly history unavailable from Yahoo Finance."
                )
                histories[quote.ticker] = []
                continue

            monthly = history.dropna(subset=["Close"]).copy()
            monthly_rows: list[dict[str, Any]] = []
            for idx, row in monthly.iterrows():
                close = float(row.get("Close", 0) or 0)
                open_price = float(row.get("Open", close) or close)
                high = float(row.get("High", close) or close)
                low = float(row.get("Low", close) or close)
                volume = int(row.get("Volume", 0) or 0)
                monthly_rows.append(
                    {
                        "month": idx.strftime("%Y-%m"),
                        "open": round(open_price, 2),
                        "high": round(high, 2),
                        "low": round(low, 2),
                        "close": round(close, 2),
                        "volume": volume,
                    }
                )
            histories[quote.ticker] = monthly_rows

            first_close = monthly_rows[0]["close"]
            last_close = monthly_rows[-1]["close"]
            high_5y = max(row["high"] for row in monthly_rows)
            low_5y = min(row["low"] for row in monthly_rows)
            five_year_return = ((last_close - first_close) / first_close * 100) if first_close else 0
            shares_at_start = investment_amount / first_close if first_close else 0
            current_value = shares_at_start * last_close
            profit_loss = current_value - investment_amount

            yearly_lines: list[str] = []
            years = sorted({row["month"][:4] for row in monthly_rows})
            for year in years:
                year_rows = [row for row in monthly_rows if row["month"].startswith(year)]
                if not year_rows:
                    continue
                y_start = year_rows[0]["close"]
                y_end = year_rows[-1]["close"]
                y_return = ((y_end - y_start) / y_start * 100) if y_start else 0
                yearly_lines.append(f"  - {year}: {y_start:.2f} -> {y_end:.2f} ({y_return:+.2f}%)")

            recent_lines = [
                f"  - {row['month']}: open {row['open']:.2f}, high {row['high']:.2f}, low {row['low']:.2f}, close {row['close']:.2f}, volume {row['volume']:,}"
                for row in monthly_rows[-6:]
            ]
            trend = "positive" if five_year_return > 0 else "negative" if five_year_return < 0 else "flat"
            sections.append(
                "\n".join(
                    [
                        f"{quote.ticker} — {quote.company_name or 'Company name unavailable'}",
                        f"- Current price: {format_money(quote.price, quote.currency)}",
                        f"- 5-year start close: {format_money(first_close, quote.currency)}",
                        f"- Latest monthly close: {format_money(last_close, quote.currency)}",
                        f"- 5-year return: {five_year_return:+.2f}% ({trend} trend)",
                        f"- 5-year high/low: {format_money(high_5y, quote.currency)} / {format_money(low_5y, quote.currency)}",
                        f"- Profit/loss scenario: {format_money(investment_amount, quote.currency)} invested 5 years ago would be about {format_money(current_value, quote.currency)} ({format_money(profit_loss, quote.currency)} gain/loss).",
                        "- Year-by-year monthly-close performance:",
                        *yearly_lines,
                        "- Recent 6 monthly records:",
                        *recent_lines,
                        "- Full 5-year monthly close history is returned as structured chart data for the UI.",
                    ]
                )
            )

        return {
            "answer": "5-year stock analysis:\n\n" + "\n\n".join(sections) + "\n\nDisclaimer: Educational research only, not financial advice.",
            "tickers": tickers,
            "history": histories,
            "sources": ["Yahoo Finance via yfinance monthly history"],
        }

    @mcp.tool()
    def suggest_best_stock_of_month(question: str, universe: list[str] | None = None, top_n: int = 5) -> dict[str, Any]:
        """Suggest top stocks from the configured universe for educational screening."""
        tickers = universe or TOP_10_STOCKS
        quotes = [get_quote(ticker) for ticker in tickers[: max(1, min(top_n, 10))]]
        lines = [
            f"{idx}. {quote.ticker} — {quote.company_name or 'Company name unavailable'}: {format_money(quote.price, quote.currency)}, sector {quote.sector or 'not available'}"
            for idx, quote in enumerate(quotes, start=1)
        ]
        return {
            "answer": "Educational stock screen:\n\n" + "\n".join(lines) + "\n\nDisclaimer: Educational research only, not financial advice.",
            "ranked": [asdict(quote) for quote in quotes],
            "sources": ["Yahoo Finance via yfinance"],
        }
