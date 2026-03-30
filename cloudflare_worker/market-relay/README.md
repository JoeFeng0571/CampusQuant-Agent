# Cloudflare Market Relay

This Worker provides a minimal relay for Hong Kong and US market data.

## Routes

- `GET /relay/market/spot?symbol=00700.HK`
- `GET /relay/market/quotes?market=hk&symbols=00700.HK,09988.HK`
- `GET /relay/market/kline?symbol=AAPL&period=daily&count=120`

## Deploy

1. Install Wrangler.
2. Copy `wrangler.toml.example` to `wrangler.toml`.
3. Optionally set a bearer token:
   - `wrangler secret put RELAY_TOKEN`
4. Deploy:

```bash
wrangler deploy
```

## Main-site env

Set these on the mainland application server:

```env
MARKET_RELAY_BASE_URL=https://your-worker.your-subdomain.workers.dev
MARKET_RELAY_TOKEN=replace-me
```

When `MARKET_RELAY_BASE_URL` is set, Hong Kong and US spot/quotes/kline requests will prefer the relay.
