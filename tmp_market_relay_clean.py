from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
import requests
import os

app = FastAPI()
RELAY_TOKEN = os.getenv("RELAY_TOKEN", "campusquant-relay-hk")

UA = {"User-Agent": "Mozilla/5.0"}


def check_auth(auth: str | None):
    if auth != f"Bearer {RELAY_TOKEN}":
        raise HTTPException(status_code=403, detail="Unauthorized")


def fetch_json(url: str):
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    return r.json()


@app.get("/relay/market/kline")
def kline(
    symbol: str = Query(...),
    period: str = Query("1d"),
    count: int = Query(120),
    authorization: str | None = Header(None),
):
    check_auth(authorization)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval={period}&range=1y"
    return JSONResponse(fetch_json(url))


@app.get("/relay/market/fundamental")
def fundamental(symbol: str, authorization: str | None = Header(None)):
    check_auth(authorization)
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=defaultKeyStatistics,financialData,assetProfile"
    return JSONResponse(fetch_json(url))


@app.get("/relay/market/news")
def news(symbol: str, authorization: str | None = Header(None)):
    check_auth(authorization)
    url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
    return JSONResponse(fetch_json(url))


@app.get("/relay/market/deep")
def deep(symbol: str, authorization: str | None = Header(None)):
    check_auth(authorization)
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=incomeStatementHistory,balanceSheetHistory,cashflowStatementHistory"
    return JSONResponse(fetch_json(url))
