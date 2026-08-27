"""Official TWSE, TPEx, and MOPS source adapters."""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import certifi
import requests


USER_AGENT = "StockRevenueLab/1.0 (+https://github.com/Richard82611/StockRevenueLab)"
TWSE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
MOPS_HOST = "https://mopsov.twse.com.tw"
TAIPEI = ZoneInfo("Asia/Taipei")


class SourceError(RuntimeError):
    pass


class _RowParser(HTMLParser):
    """Collect HTML rows without depending on pandas/lxml."""

    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _get(url: str, *, params: dict | None = None, attempts: int = 3) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html"},
                timeout=30,
                verify=certifi.where(),
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise SourceError(f"official source request failed: {type(last_error).__name__}")


def _number(value, *, integer: bool = False):
    text = str(value).replace(",", "").replace("−", "-").strip()
    if not text or text in {"-", "--", "---", "－", "N/A"}:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group())
    return int(number) if integer else number


def _is_company_code(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}", str(value).strip()))


def _roc_date(value: date) -> str:
    return f"{value.year - 1911:03d}/{value.month:02d}/{value.day:02d}"


def _previous_month(value: date, offset: int = 1) -> tuple[int, int]:
    year, month = value.year, value.month - offset
    while month <= 0:
        year -= 1
        month += 12
    return year, month


def fetch_twse_prices(trading_date: date) -> tuple[list[dict], str]:
    response = _get(
        TWSE_URL,
        params={"date": trading_date.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"},
    )
    payload = response.json()
    if payload.get("stat") != "OK" or payload.get("date") != trading_date.strftime("%Y%m%d"):
        raise SourceError("TWSE did not return the requested completed trading day")
    table = next(
        (item for item in payload.get("tables", []) if "每日收盤行情" in str(item.get("title"))),
        None,
    )
    if not table:
        raise SourceError("TWSE daily close table missing")
    rows = []
    for item in table.get("data", []):
        code = str(item[0]).strip() if item else ""
        if not _is_company_code(code):
            continue
        open_price, high, low, close = (_number(item[i]) for i in (5, 6, 7, 8))
        if close is None:
            continue
        rows.append(
            {
                "date": trading_date.isoformat(),
                "symbol": f"{code}.TW",
                "stock_id": code,
                "stock_name": str(item[1]).strip(),
                "market": "TWSE",
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": _number(item[2], integer=True),
            }
        )
    return rows, response.url


def fetch_tpex_prices(trading_date: date) -> tuple[list[dict], str]:
    response = _get(
        TPEX_URL,
        params={"date": _roc_date(trading_date), "id": "", "response": "json"},
    )
    payload = response.json()
    if str(payload.get("stat", "")).lower() != "ok" or payload.get("date") != trading_date.strftime("%Y%m%d"):
        raise SourceError("TPEx did not return the requested completed trading day")
    table = next(
        (item for item in payload.get("tables", []) if "上櫃股票行情" in str(item.get("title"))),
        None,
    )
    if not table:
        raise SourceError("TPEx daily quote table missing")
    rows = []
    for item in table.get("data", []):
        code = str(item[0]).strip() if item else ""
        if not _is_company_code(code):
            continue
        close, open_price, high, low = (_number(item[i]) for i in (2, 4, 5, 6))
        if close is None:
            continue
        rows.append(
            {
                "date": trading_date.isoformat(),
                "symbol": f"{code}.TWO",
                "stock_id": code,
                "stock_name": str(item[1]).strip(),
                "market": "TPEx",
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": _number(item[8], integer=True),
            }
        )
    return rows, response.url


def fetch_latest_official_prices(
    as_of: date | None = None,
    *,
    minimum_twse: int = 900,
    minimum_tpex: int = 750,
) -> tuple[str, list[dict], list[str], dict]:
    as_of = as_of or datetime.now(TAIPEI).date()
    failures = []
    for offset in range(7):
        candidate = as_of - timedelta(days=offset)
        try:
            twse, twse_url = fetch_twse_prices(candidate)
            tpex, tpex_url = fetch_tpex_prices(candidate)
        except (SourceError, ValueError, requests.JSONDecodeError) as exc:
            failures.append(f"{candidate}:{type(exc).__name__}")
            continue
        if len(twse) < minimum_twse or len(tpex) < minimum_tpex:
            failures.append(f"{candidate}:coverage={len(twse)}+{len(tpex)}")
            continue
        combined = twse + tpex
        symbols = [row["symbol"] for row in combined]
        if len(symbols) != len(set(symbols)):
            raise SourceError("duplicate price keys in official snapshot")
        return (
            candidate.isoformat(),
            combined,
            [twse_url, tpex_url],
            {"twse_rows": len(twse), "tpex_rows": len(tpex), "price_rows": len(combined)},
        )
    raise SourceError("no complete common trading day: " + ";".join(failures))


def _parse_mops_page(html: str, market_type: str, report_month: str) -> list[dict]:
    parser = _RowParser()
    parser.feed(html)
    output = []
    for row in parser.rows:
        if len(row) < 10:
            continue
        code = row[0].replace(" ", "").strip()
        if not _is_company_code(code) or _number(row[2], integer=True) is None:
            continue
        output.append(
            {
                "report_month": report_month,
                "market_type": market_type,
                "stock_id": code,
                "stock_name": row[1].strip(),
                "rev_current": _number(row[2], integer=True),
                "rev_last_month": _number(row[3], integer=True),
                "rev_last_year": _number(row[4], integer=True),
                "mom_pct": _number(row[5]),
                "yoy_pct": _number(row[6]),
                "rev_accumulated": _number(row[7], integer=True),
                "rev_accumulated_last_year": _number(row[8], integer=True),
                "yoy_accumulated_pct": _number(row[9]),
                "remark": row[10].strip() if len(row) > 10 else "",
            }
        )
    return output


def fetch_mops_month(year: int, month: int) -> tuple[list[dict], list[str], dict]:
    roc_year = year - 1911
    report_month = f"{roc_year}_{month:02d}"
    sources = []
    rows: list[dict] = []
    page_counts = {}
    for market in ("sii", "otc", "rotc"):
        for foreign in (0, 1):
            market_type = market + ("_ky" if foreign else "")
            url = f"{MOPS_HOST}/nas/t21/{market}/t21sc03_{roc_year}_{month}_{foreign}.html"
            response = _get(url)
            response.encoding = "big5"
            page_rows = _parse_mops_page(response.text, market_type, report_month)
            sources.append(response.url)
            page_counts[market_type] = len(page_rows)
            rows.extend(page_rows)
    deduplicated: dict[str, dict] = {}
    for row in rows:
        deduplicated.setdefault(row["stock_id"], row)
    output = list(deduplicated.values())
    return output, sources, {
        "revenue_rows": len(output),
        "revenue_raw_rows": len(rows),
        "revenue_duplicates": len(rows) - len(output),
        "mops_page_rows": page_counts,
    }


def fetch_latest_mops_revenue(
    as_of: date | None = None,
    *,
    minimum_rows: int = 2000,
) -> tuple[str, list[dict], list[str], dict]:
    as_of = as_of or datetime.now(TAIPEI).date()
    failures = []
    for offset in range(1, 4):
        year, month = _previous_month(as_of, offset)
        try:
            rows, urls, quality = fetch_mops_month(year, month)
        except SourceError as exc:
            failures.append(f"{year}-{month:02d}:{type(exc).__name__}")
            continue
        if len(rows) < minimum_rows:
            failures.append(f"{year}-{month:02d}:coverage={len(rows)}")
            continue
        return f"{year - 1911}_{month:02d}", rows, urls, quality
    raise SourceError("no complete MOPS month: " + ";".join(failures))
