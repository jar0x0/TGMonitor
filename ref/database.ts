// bot/src/config/database.ts
import mysql from 'mysql2/promise';
import { logger } from '../utils/logger';

// 创建数据库连接池
const pool = mysql.createPool({
  host: process.env.DB_HOST || 'localhost',
  port: parseInt(process.env.DB_PORT || '3306', 10),
  user: process.env.DB_USER || 'root',
  password: process.env.DB_PASSWORD || '',
  database: process.env.DB_NAME || 'relinx',
  waitForConnections: true,
  connectionLimit: 10,
  queueLimit: 0,
  timezone: '+08:00', // 中国时区
  charset: 'utf8mb4',  // 支持表情符号
  multipleStatements: false,
  namedPlaceholders: false
});

// 测试连接
pool.getConnection()
  .then((conn: any) => {
    logger.info(`✅ Database connected successfully (Thread ID: ${conn.threadId})`);
    conn.release();
  })
  .catch((err: any) => {
    logger.error('⚠️ Database connection failed:', err.message);
  });

export default pool;
