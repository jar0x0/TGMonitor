import Redis from 'ioredis';
import { redisConfig } from './redis';
import { logger } from '../utils/logger';

/**
 * Redis 客户端单例
 * 提供统一的 Redis 连接管理
 */
class RedisClientManager {
  private static instance: RedisClientManager;
  private client: Redis | null = null; // 普通数据操作客户端
  private bullmqClient: Redis | null = null; // BullMQ 专用客户端
  private isConnected: boolean = false;

  private constructor() {}

  /**
   * 获取 RedisClientManager 单例
   */
  public static getInstance(): RedisClientManager {
    if (!RedisClientManager.instance) {
      RedisClientManager.instance = new RedisClientManager();
    }
    return RedisClientManager.instance;
  }

  /**
   * 获取 Redis 客户端连接（普通数据操作）
   * 如果未启用 Redis，返回 null
   */
  public getClient(): Redis | null {
    const useRedis = process.env.USE_REDIS === 'true';
    
    if (!useRedis) {
      return null;
    }

    if (!this.client) {
      this.connectNormal();
    }

    return this.client;
  }

  /**
   * 获取 BullMQ 专用 Redis 客户端
   */
  public getBullMQClient(): Redis | null {
    const useRedis = process.env.USE_REDIS === 'true';
    
    if (!useRedis) {
      return null;
    }

    if (!this.bullmqClient) {
      this.connectBullMQ();
    }

    return this.bullmqClient;
  }

  /**
   * 连接到 Redis（普通数据操作）
   */
  private connectNormal(): void {
    try {
      const options: any = {
        host: this.parseHost(redisConfig.url || 'redis://localhost:6379'),
        port: this.parsePort(redisConfig.url || 'redis://localhost:6379'),
        db: redisConfig.database || 0,
        password: redisConfig.password,
        retryStrategy: (times: number) => {
          const delay = Math.min(times * 50, 2000);
          return delay;
        },
        maxRetriesPerRequest: 3, // 普通操作：允许重试3次
        enableReadyCheck: true,  // 普通操作：启用就绪检查
        enableOfflineQueue: true, // 普通操作：启用离线队列
      };

      this.client = new Redis(options);

      this.client.on('connect', () => {
        logger.info('✅ Redis client (normal) connected');
        this.isConnected = true;
      });

      this.client.on('ready', () => {
        logger.info('✅ Redis client (normal) ready');
      });

      this.client.on('error', (error: Error) => {
        logger.error('❌ Redis client (normal) error:', error.message);
        this.isConnected = false;
      });

      this.client.on('close', () => {
        logger.info('⚠️  Redis connection (normal) closed');
        this.isConnected = false;
      });

      this.client.on('reconnecting', () => {
        logger.info('🔄 Redis (normal) reconnecting...');
      });

    } catch (error) {
      logger.error('❌ Failed to create Redis client (normal):', error);
      this.client = null;
    }
  }

  /**
   * 连接到 Redis（BullMQ 专用）
   */
  private connectBullMQ(): void {
    try {
      const options: any = {
        host: this.parseHost(redisConfig.url || 'redis://localhost:6379'),
        port: this.parsePort(redisConfig.url || 'redis://localhost:6379'),
        db: redisConfig.database || 0,
        password: redisConfig.password,
        retryStrategy: (times: number) => {
          const delay = Math.min(times * 50, 2000);
          return delay;
        },
        maxRetriesPerRequest: null, // BullMQ 要求必须为 null
        enableReadyCheck: false,     // BullMQ 推荐禁用
        enableOfflineQueue: true,    // 启用离线队列以处理临时网络中断
        lazyConnect: false,          // 立即连接，不等待第一个命令
      };

      this.bullmqClient = new Redis(options);

      this.bullmqClient.on('connect', () => {
        logger.info('✅ Redis client (BullMQ) connected');
      });

      this.bullmqClient.on('ready', () => {
        logger.info('✅ Redis client (BullMQ) ready');
      });

      this.bullmqClient.on('error', (error: Error) => {
        logger.error('❌ Redis client (BullMQ) error:', error.message);
      });

      this.bullmqClient.on('close', () => {
        logger.info('⚠️  Redis connection (BullMQ) closed');
      });

      this.bullmqClient.on('reconnecting', () => {
        logger.info('🔄 Redis (BullMQ) reconnecting...');
      });

    } catch (error) {
      logger.error('❌ Failed to create Redis client (BullMQ):', error);
      this.bullmqClient = null;
    }
  }

  /**
   * 解析 Redis URL 获取主机名
   */
  private parseHost(url: string): string {
    try {
      const parsed = new URL(url);
      return parsed.hostname || 'localhost';
    } catch {
      return 'localhost';
    }
  }

  /**
   * 解析 Redis URL 获取端口
   */
  private parsePort(url: string): number {
    try {
      const parsed = new URL(url);
      return parseInt(parsed.port, 10) || 6379;
    } catch {
      return 6379;
    }
  }

  /**
   * 检查 Redis 是否已连接
   */
  public isRedisConnected(): boolean {
    return this.isConnected && this.client !== null;
  }

  /**
   * 优雅关闭 Redis 连接
   */
  public async disconnect(): Promise<void> {
    const promises = [];
    
    if (this.client) {
      promises.push(
        this.client.quit()
          .then(() => logger.info('✅ Redis client (normal) disconnected gracefully'))
          .catch((error) => logger.error('❌ Error disconnecting Redis (normal):', error))
      );
      this.client = null;
    }
    
    if (this.bullmqClient) {
      promises.push(
        this.bullmqClient.quit()
          .then(() => logger.info('✅ Redis client (BullMQ) disconnected gracefully'))
          .catch((error) => logger.error('❌ Error disconnecting Redis (BullMQ):', error))
      );
      this.bullmqClient = null;
    }
    
    await Promise.all(promises);
    this.isConnected = false;
  }
}

// 导出单例实例
export const redisClientManager = RedisClientManager.getInstance();

// 便捷方法：获取 Redis 客户端（普通数据操作）
export function getRedisClient(): Redis | null {
  return redisClientManager.getClient();
}

// 便捷方法：获取 BullMQ 专用 Redis 客户端
export function getBullMQRedisClient(): Redis | null {
  return redisClientManager.getBullMQClient();
}

// 便捷方法：检查 Redis 是否可用
export function isRedisEnabled(): boolean {
  return process.env.USE_REDIS === 'true';
}
