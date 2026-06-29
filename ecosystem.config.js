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
      script: "scripts/run_snapshot_collector.py",
      args: "--interval-seconds 60",
      interpreter: ".venv/bin/python",
      env: {
        APP_ENV: "production",
      },
    },
  ],
};
