# Cryptocurrency Order Book Analyzer

A password-protected Flask web application for visualizing cryptocurrency candlestick charts overlaid with significant order book levels. It tracks large ask and bid orders over time, filters out likely spoof orders, and annotates the nearest support or resistance wall on the chart.

## Features

- Candlestick charts for BTC/USDT, ETH/USDT, and SOL/USDT fetched from Bybit via ccxt
- Real-time order book data fetched from the Binance public API (depth endpoint)
- Persistent tracking of large orders in SQLite databases across chart refreshes
- Spoof order filtering: orders present for less than 5 minutes are not displayed
- Color-coded order wall rectangles rendered to the right of the price chart using Plotly
- Arrow annotation pointing to the nearest significant limit order relative to the current price
- Non-zero volume (NZ Volume) display: combined size of tracked asks and bids
- Automatic chart refresh every 27 seconds
- Timeframe support: 1m, 5m, 15m, 30m, 1h, 2h, 4h
- Session-based authentication with optional 30-day persistent login

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Flask 3.0 |
| ORM | SQLAlchemy 2.0 |
| Database | SQLite (two separate files: asks, bids) |
| Chart rendering | Plotly (server-side JSON, client-side rendering) |
| Exchange data | ccxt (Bybit OHLCV), Binance REST API (order book) |
| WSGI server | Gunicorn |
| Containerization | Docker |

## Project Structure

```
.
├── app.py                  # Flask application, chart generation, auth routes
├── db_func.py              # SQLAlchemy-based order storage and retrieval
├── orders_db_v1_5.py       # Legacy sqlite3-based version (reference only)
├── delete_db_v5.py         # Utility script to drop all order tables
├── requirements.txt
├── Dockerfile
├── templates/
│   ├── index.html          # Main chart + order book page
│   ├── authorisation.html  # Login page
│   └── error.html          # Wrong password page
└── static/
    ├── styles.css
    └── favicon.svg
```

## Configuration

Create a `.env` file in the project root:

```
SECRET_KEY=your_flask_secret_key
PSW=sha256_hash_of_your_password
```

`PSW` must be the SHA-256 hex digest of the plain-text password:

```python
import hashlib
print(hashlib.sha256("your_password".encode()).hexdigest())
```

## Running Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

The application will be available at `http://127.0.0.1:5000`.

## Running with Docker

```bash
docker build -t order-book-analyzer .
docker run --env-file .env -p 5000:5000 order-book-analyzer
```

Gunicorn starts with 4 worker processes bound to `0.0.0.0:5000`.

## Database Management

Order data is stored in two SQLite files at the project root:

- `orders_asks.db` — tracked sell-side orders
- `orders_bids.db` — tracked buy-side orders

To reset all order tables:

```bash
python delete_db_v5.py
```

## Order Filtering Logic

The minimum order size threshold is defined per symbol in `SYMBOLS_CONSTANTS` inside `app.py`. The second element of each list is the minimum USD notional value:

```python
SYMBOLS_CONSTANTS = {
    "BTCUSDT": [10000, 2000000, 30],
    "ETHUSDT": [7000,  2000000,  2],
    "SOLUSDT": [5000,  2000000,  0.4],
}
```

Orders below this threshold are ignored. Orders that appeared less than 5 minutes ago are not rendered on the chart (spoof filter). When a price level is updated between fetches, the volume is accumulated rather than replaced.

## Color Scheme for Order Walls

| Intensity (volume / max volume) | Ask color | Bid color |
|---|---|---|
| > 0.58 | darkred | darkgreen |
| > 0.39 | red | green |
| > 0.10 | orange | lime |
| <= 0.10 | lightcoral | lightgreen |
