module.exports = {
  apps: [
    {
      name: "marketlab-backend",
      cwd: "/var/www/marketlab/backend",
      script: ".venv/bin/python",
      args: "-m uvicorn app.main:app --host 0.0.0.0 --port 8000",
      interpreter: "none",
      env: {
        APP_ENV: "production",
      },
    },
    {
      name: "marketlab-frontend",
      cwd: "/var/www/marketlab/frontend",
      script: "/root/.nvm/versions/node/v22.22.2/bin/npm",
      args: "start -- -H 0.0.0.0 -p 3000",
      interpreter: "none",
      env: {
        NODE_ENV: "production",
        PATH: "/root/.nvm/versions/node/v22.22.2/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
      },
    },
    {
      name: "marketlab-snapshot-loop",
      cwd: "/var/www/marketlab/backend",
      script: ".venv/bin/python",
      args: "scripts/run_snapshot_collector.py --interval-seconds 300",
      interpreter: "none",
      env: {
        APP_ENV: "production",
      },
    },
    {
      name: "marketlab-kline-loop",
      cwd: "/var/www/marketlab/backend",
      script: ".venv/bin/python",
      args: "scripts/run_kline_collector.py --markets futures spot --cycles 100000 --interval-seconds 60",
      interpreter: "none",
      env: {
        APP_ENV: "production",
      },
    },
    {
      name: "marketlab-research-loop",
      cwd: "/var/www/marketlab",
      script: "backend/scripts/run_marketlab_research_loop.sh",
      interpreter: "bash",
      env: {
        APP_ENV: "production",
        MARKETLAB_LOOP_SLEEP_SECONDS: "300",
        MARKETLAB_UNIVERSE_INTERVAL_SECONDS: "3600",
        MARKETLAB_RICH_INTERVAL_SECONDS: "1800",
      },
    },
  ],
};
