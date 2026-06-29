# MarketLab Backend

Run locally without Docker:

```powershell
cd C:\Code\marketlab\backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Run collectors once:

```powershell
cd C:\Code\marketlab
backend\.venv\Scripts\python scripts\run_collector.py all
```

Run the continuous 1-minute collector loop:

```powershell
cd C:\Code\marketlab
backend\.venv\Scripts\python backend\scripts\run_collector_loop.py
```

Run a bounded local test:

```powershell
cd C:\Code\marketlab
backend\.venv\Scripts\python backend\scripts\run_collector_loop.py --cycles 3
```

Run rich futures collectors separately:

```powershell
cd C:\Code\marketlab
backend\.venv\Scripts\python backend\scripts\run_rich_futures_collector.py
```

Run a bounded rich futures validation cycle:

```powershell
cd C:\Code\marketlab
backend\.venv\Scripts\python backend\scripts\run_rich_futures_collector.py --cycles 1 --periods 5m --include-funding
```

## Binance data resolution

MarketLab uses a multi-resolution Binance data layer. Not all Binance datasets are available at 1m resolution:

- 1m data is used for OHLCV and kline taker buy fields.
- 5m data is used for open interest history, global long/short ratio, top trader ratios, and the futures taker buy/sell volume endpoint.
- Funding data and book ticker snapshots have separate freshness/alignment handling.

See `backend/docs/binance_data_availability.md` for the full endpoint, field, caveat, and alignment audit.
