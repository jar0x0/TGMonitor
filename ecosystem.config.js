const path = require('path');

module.exports = {
  apps: [
    {
      name: 'tg-monitor',
      script: 'src/main.py',
      // 使用项目根目录上一层的 .venv；如果部署路径不同，请修改此处
      interpreter: path.resolve(__dirname, '..', '.venv', 'bin', 'python3'),
      cwd: __dirname,
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        NODE_ENV: 'development'
      },
      env_production: {
        NODE_ENV: 'production'
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: './logs/pm2-error.log',
      out_file: './logs/pm2-out.log',
      merge_logs: true
    }
  ]
};
