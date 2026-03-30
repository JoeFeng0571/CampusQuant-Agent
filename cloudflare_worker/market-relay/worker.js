// Cloudflare Worker: CampusQuant Global Data Relay (2026 Edition)
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const pathname = url.pathname;
    const symbol = url.searchParams.get("symbol");
    const auth = request.headers.get("Authorization");

    // 1. 安全校验
    if (auth !== `Bearer ${env.RELAY_TOKEN}`) {
      return new Response(JSON.stringify({ status: "error", detail: "Unauthorized" }), { status: 403 });
    }

    if (!symbol) return new Response(JSON.stringify({ status: "error", detail: "Symbol required" }), { status: 400 });

    try {
      let yahooUrl = "";
      // 2. 路由分发
      if (pathname.endsWith("/spot")) {
        yahooUrl = `https://query1.finance.yahoo.com/v7/finance/quote?symbols=${symbol}`;
      } else if (pathname.endsWith("/kline")) {
        const interval = url.searchParams.get("period") || "1d";
        yahooUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?interval=${interval}&range=1y`;
      } else if (pathname.endsWith("/news")) {
        yahooUrl = `https://query1.finance.yahoo.com/v1/finance/search?q=${symbol}`;
      } else if (pathname.endsWith("/fundamental")) {
        yahooUrl = `https://query1.finance.yahoo.com/v10/finance/quoteSummary/${symbol}?modules=defaultKeyStatistics,financialData,assetProfile`;
      } else if (pathname.endsWith("/deep")) {
        yahooUrl = `https://query1.finance.yahoo.com/v10/finance/quoteSummary/${symbol}?modules=incomeStatementHistory,balanceSheetHistory,cashflowStatementHistory`;
      }

      const response = await fetch(yahooUrl, {
        headers: { "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" }
      });
      const data = await response.text();
      return new Response(data, { headers: { "Content-Type": "application/json" } });

    } catch (e) {
      return new Response(JSON.stringify({ status: "error", message: e.message }), { status: 500 });
    }
  }
};