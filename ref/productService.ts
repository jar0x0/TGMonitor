// bot/src/services/productService.ts
import { Product, ProductType, ProductStatus, PurchaseStrategy, PurchaseLimitPeriod } from '../types/product';
import { productRepository } from '../repositories/productRepository';
import { inventoryRepository } from '../repositories/inventoryRepository';
import { getRedisClient } from '../config/redisClient';
import { logger } from '../utils/logger';
import type { Redis } from 'ioredis';

/**
 * ProductService - 产品业务逻辑层
 * 负责 Redis 缓存管理和调用 ProductRepository
 * 实现 2 级存储：Redis(缓存) + MySQL(持久化)
 */
class ProductService {
  private isInitialized: boolean = false;
  private isRunning: boolean = false;
  private lastUpdateTime: number | null = null;

  // Redis 键前缀和索引定义（参考 OrderService 和 InventoryService 模式）
  private readonly REDIS_PREFIX = 'product:';
  private readonly REDIS_KEYS = {
    // 主数据存储: product:id:{id} - 存储完整 Product JSON
    BY_ID: `${this.REDIS_PREFIX}id:`,
    
    // 索引键 - 用户要求的18个索引
    BY_SKU: `${this.REDIS_PREFIX}sku:`,                              // STRING: 1-to-1
    BY_NAME: `${this.REDIS_PREFIX}name:`,                            // SET: 1-to-many
    BY_CATEGORY: `${this.REDIS_PREFIX}category:`,                    // SET: 1-to-many
    BY_TYPE: `${this.REDIS_PREFIX}type:`,                            // SET: 1-to-many
    BY_ISSUER_CODE: `${this.REDIS_PREFIX}issuer_code:`,              // SET: 1-to-many
    BY_ISSUER_NAME: `${this.REDIS_PREFIX}issuer_name:`,              // SET: 1-to-many
    BY_REGION: `${this.REDIS_PREFIX}region:`,                        // SET: 1-to-many
    BY_CURRENCY: `${this.REDIS_PREFIX}currency:`,                    // SET: 1-to-many
    BY_PRIMARY_VENDOR_ID: `${this.REDIS_PREFIX}primary_vendor_id:`,  // SET: 1-to-many
    BY_PRIMARY_VENDOR_SKU: `${this.REDIS_PREFIX}primary_vendor_product_sku:`,  // STRING: 1-to-1
    BY_SECONDARY_VENDOR_ID: `${this.REDIS_PREFIX}secondary_vendor_id:`,  // SET: 1-to-many
    BY_SECONDARY_VENDOR_SKU: `${this.REDIS_PREFIX}secondary_vendor_product_sku:`,  // STRING: 1-to-1
    BY_PURCHASE_STRATEGY: `${this.REDIS_PREFIX}purchase_strategy:`,  // SET: 1-to-many
    BY_STATUS: `${this.REDIS_PREFIX}status:`,                        // SET: 1-to-many
    BY_IS_FEATURED: `${this.REDIS_PREFIX}is_featured:`,              // SET: featured products
    BY_IS_TRIAL: `${this.REDIS_PREFIX}is_trial:`,                    // SET: trial products
    BY_VALIDITY_DAYS: `${this.REDIS_PREFIX}validity_days:`,          // SET: 1-to-many
    
    // 统计和元数据
    ALL_PRODUCTS: `${this.REDIS_PREFIX}all`,                         // SET: 所有产品ID
    STATS: `${this.REDIS_PREFIX}stats`,
    LAST_UPDATE: `${this.REDIS_PREFIX}last_update`
  };

  constructor() {}

  /**
   * 获取 Redis 客户端（带类型注解）
   */
  private getRedis(): Redis {
    const redis = getRedisClient();
    if (!redis) {
      throw new Error('Redis client is not available');
    }
    return redis;
  }

  /**
   * 初始化服务
   */
  async initialize(): Promise<void> {
    try {
      logger.info('🔧 Initializing ProductService...');

      await this.loadProductsFromDatabase();

      this.isInitialized = true;
      logger.info('✅ ProductService initialized successfully');

    } catch (error) {
      logger.error('❌ Failed to initialize ProductService:', error);
      throw error;
    }
  }

  /**
   * 启动服务
   */
  async start(): Promise<void> {
    try {
      if (this.isRunning) {
        logger.warn('⚠️ ProductService is already running');
        return;
      }

      logger.info('🚀 Starting ProductService...');
      await this.initialize();

      this.isRunning = true;
      logger.info('✅ ProductService started successfully');

    } catch (error) {
      logger.error('❌ Failed to start ProductService:', error);
      throw error;
    }
  }

  /**
   * 从数据库加载产品数据到 Redis
   */
  async loadProductsFromDatabase(): Promise<void> {
    try {
      logger.info('📥 Loading products from database...');

      // 1. 清理所有现有 Redis 数据
      await this.clearAllRedisData();

      // 2. 从数据库获取所有产品
      const products = await productRepository.getAllProductsFromDatabase();

      let successCount = 0;
      let errorCount = 0;

      // 3. 遍历产品，存储到 Redis 并建立索引
      for (const product of products) {
        try {
          // 建立索引（包含主数据存储）
          await this.createProductIndexes(product);

          successCount++;
        } catch (error) {
          logger.error(`❌ Failed to load product ${product.id} to Redis:`, error);
          errorCount++;
        }
      }

      this.lastUpdateTime = Date.now();
      logger.info(`✅ Loaded ${successCount} products from database to Redis (${errorCount} failed)`);

    } catch (error) {
      logger.error('❌ Failed to load products from database:', error);
      throw error;
    }
  }

  /**
   * 创建产品的 Redis 索引
   * 包括主数据存储（BY_ID）和所有18个查询索引
   */
  private async createProductIndexes(product: Product): Promise<void> {
    try {
      const redis = this.getRedis();

      // 1. BY_ID 索引（存储完整产品 JSON 数据）
      await redis.set(`${this.REDIS_KEYS.BY_ID}${product.id}`, JSON.stringify(product.toObject()));

      // 2. SKU 索引 - STRING 类型（1-to-1，唯一）
      await redis.set(`${this.REDIS_KEYS.BY_SKU}${product.sku}`, product.id.toString());

      // 3. Name 索引 - SET 类型（1-to-many）
      if (product.name) {
        await redis.sadd(`${this.REDIS_KEYS.BY_NAME}${product.name}`, product.id.toString());
      }

      // 4. Category 索引 - SET 类型（1-to-many）
      if (product.category) {
        await redis.sadd(`${this.REDIS_KEYS.BY_CATEGORY}${product.category}`, product.id.toString());
      }

      // 5. Type 索引 - SET 类型（1-to-many）
      await redis.sadd(`${this.REDIS_KEYS.BY_TYPE}${product.type}`, product.id.toString());

      // 6. Issuer Code 索引 - SET 类型（1-to-many）
      if (product.issuerCode) {
        await redis.sadd(`${this.REDIS_KEYS.BY_ISSUER_CODE}${product.issuerCode}`, product.id.toString());
      }

      // 7. Issuer Name 索引 - SET 类型（1-to-many）
      if (product.issuerName) {
        await redis.sadd(`${this.REDIS_KEYS.BY_ISSUER_NAME}${product.issuerName}`, product.id.toString());
      }

      // 8. Region 索引 - SET 类型（1-to-many）
      await redis.sadd(`${this.REDIS_KEYS.BY_REGION}${product.region}`, product.id.toString());

      // 9. Currency 索引 - SET 类型（1-to-many）
      await redis.sadd(`${this.REDIS_KEYS.BY_CURRENCY}${product.currency}`, product.id.toString());

      // 10. Primary Vendor ID 索引 - SET 类型（1-to-many）
      if (product.primaryVendorId) {
        await redis.sadd(`${this.REDIS_KEYS.BY_PRIMARY_VENDOR_ID}${product.primaryVendorId}`, product.id.toString());
      }

      // 11. Primary Vendor SKU 索引 - STRING 类型（1-to-1）
      if (product.primaryVendorProductSku) {
        await redis.set(`${this.REDIS_KEYS.BY_PRIMARY_VENDOR_SKU}${product.primaryVendorProductSku}`, product.id.toString());
      }

      // 12. Secondary Vendor ID 索引 - SET 类型（1-to-many）
      if (product.secondaryVendorId) {
        await redis.sadd(`${this.REDIS_KEYS.BY_SECONDARY_VENDOR_ID}${product.secondaryVendorId}`, product.id.toString());
      }

      // 13. Secondary Vendor SKU 索引 - STRING 类型（1-to-1）
      if (product.secondaryVendorProductSku) {
        await redis.set(`${this.REDIS_KEYS.BY_SECONDARY_VENDOR_SKU}${product.secondaryVendorProductSku}`, product.id.toString());
      }

      // 14. Purchase Strategy 索引 - SET 类型（1-to-many）
      await redis.sadd(`${this.REDIS_KEYS.BY_PURCHASE_STRATEGY}${product.purchaseStrategy}`, product.id.toString());

      // 15. Status 索引 - SET 类型（1-to-many）
      await redis.sadd(`${this.REDIS_KEYS.BY_STATUS}${product.status}`, product.id.toString());

      // 16. Is Featured 索引 - SET 类型（boolean flag）
      const featuredKey = product.isFeatured ? '1' : '0';
      await redis.sadd(`${this.REDIS_KEYS.BY_IS_FEATURED}${featuredKey}`, product.id.toString());

      // 17. Is Trial 索引 - SET 类型（boolean flag）
      const trialKey = product.isTrial ? '1' : '0';
      await redis.sadd(`${this.REDIS_KEYS.BY_IS_TRIAL}${trialKey}`, product.id.toString());

      // 18. Validity Days 索引 - SET 类型（1-to-many）
      if (product.validityDays !== undefined && product.validityDays !== null) {
        await redis.sadd(`${this.REDIS_KEYS.BY_VALIDITY_DAYS}${product.validityDays}`, product.id.toString());
      }

      // 添加到所有产品集合
      await redis.sadd(this.REDIS_KEYS.ALL_PRODUCTS, product.id.toString());

    } catch (error) {
      logger.error(`❌ Failed to create indexes for product ${product.id}:`, error);
      throw error;
    }
  }

  /**
   * 更新产品的 Redis 索引
   * 删除旧索引，创建新索引（支持所有18个索引）
   */
  private async updateProductIndexes(oldProduct: Product, newProduct: Product): Promise<void> {
    try {
      const redis = this.getRedis();

      // 1. 更新主数据 (BY_ID)
      await redis.set(`${this.REDIS_KEYS.BY_ID}${newProduct.id}`, JSON.stringify(newProduct.toObject()));

      // 2. SKU 索引 - STRING（1-to-1）
      if (oldProduct.sku !== newProduct.sku) {
        await redis.del(`${this.REDIS_KEYS.BY_SKU}${oldProduct.sku}`);
        await redis.set(`${this.REDIS_KEYS.BY_SKU}${newProduct.sku}`, newProduct.id.toString());
      }

      // 3. Name 索引 - SET
      if (oldProduct.name !== newProduct.name) {
        if (oldProduct.name) {
          await redis.srem(`${this.REDIS_KEYS.BY_NAME}${oldProduct.name}`, oldProduct.id.toString());
        }
        if (newProduct.name) {
          await redis.sadd(`${this.REDIS_KEYS.BY_NAME}${newProduct.name}`, newProduct.id.toString());
        }
      }

      // 4. Category 索引 - SET
      if (oldProduct.category !== newProduct.category) {
        if (oldProduct.category) {
          await redis.srem(`${this.REDIS_KEYS.BY_CATEGORY}${oldProduct.category}`, oldProduct.id.toString());
        }
        if (newProduct.category) {
          await redis.sadd(`${this.REDIS_KEYS.BY_CATEGORY}${newProduct.category}`, newProduct.id.toString());
        }
      }

      // 5. Type 索引 - SET
      if (oldProduct.type !== newProduct.type) {
        await redis.srem(`${this.REDIS_KEYS.BY_TYPE}${oldProduct.type}`, oldProduct.id.toString());
        await redis.sadd(`${this.REDIS_KEYS.BY_TYPE}${newProduct.type}`, newProduct.id.toString());
      }

      // 6. Issuer Code 索引 - SET
      if (oldProduct.issuerCode !== newProduct.issuerCode) {
        if (oldProduct.issuerCode) {
          await redis.srem(`${this.REDIS_KEYS.BY_ISSUER_CODE}${oldProduct.issuerCode}`, oldProduct.id.toString());
        }
        if (newProduct.issuerCode) {
          await redis.sadd(`${this.REDIS_KEYS.BY_ISSUER_CODE}${newProduct.issuerCode}`, newProduct.id.toString());
        }
      }

      // 7. Issuer Name 索引 - SET
      if (oldProduct.issuerName !== newProduct.issuerName) {
        if (oldProduct.issuerName) {
          await redis.srem(`${this.REDIS_KEYS.BY_ISSUER_NAME}${oldProduct.issuerName}`, oldProduct.id.toString());
        }
        if (newProduct.issuerName) {
          await redis.sadd(`${this.REDIS_KEYS.BY_ISSUER_NAME}${newProduct.issuerName}`, newProduct.id.toString());
        }
      }

      // 8. Region 索引 - SET
      if (oldProduct.region !== newProduct.region) {
        await redis.srem(`${this.REDIS_KEYS.BY_REGION}${oldProduct.region}`, oldProduct.id.toString());
        await redis.sadd(`${this.REDIS_KEYS.BY_REGION}${newProduct.region}`, newProduct.id.toString());
      }

      // 9. Currency 索引 - SET
      if (oldProduct.currency !== newProduct.currency) {
        await redis.srem(`${this.REDIS_KEYS.BY_CURRENCY}${oldProduct.currency}`, oldProduct.id.toString());
        await redis.sadd(`${this.REDIS_KEYS.BY_CURRENCY}${newProduct.currency}`, newProduct.id.toString());
      }

      // 10. Primary Vendor ID 索引 - SET
      if (oldProduct.primaryVendorId !== newProduct.primaryVendorId) {
        if (oldProduct.primaryVendorId) {
          await redis.srem(`${this.REDIS_KEYS.BY_PRIMARY_VENDOR_ID}${oldProduct.primaryVendorId}`, oldProduct.id.toString());
        }
        if (newProduct.primaryVendorId) {
          await redis.sadd(`${this.REDIS_KEYS.BY_PRIMARY_VENDOR_ID}${newProduct.primaryVendorId}`, newProduct.id.toString());
        }
      }

      // 11. Primary Vendor SKU 索引 - STRING
      if (oldProduct.primaryVendorProductSku !== newProduct.primaryVendorProductSku) {
        if (oldProduct.primaryVendorProductSku) {
          await redis.del(`${this.REDIS_KEYS.BY_PRIMARY_VENDOR_SKU}${oldProduct.primaryVendorProductSku}`);
        }
        if (newProduct.primaryVendorProductSku) {
          await redis.set(`${this.REDIS_KEYS.BY_PRIMARY_VENDOR_SKU}${newProduct.primaryVendorProductSku}`, newProduct.id.toString());
        }
      }

      // 12. Secondary Vendor ID 索引 - SET
      if (oldProduct.secondaryVendorId !== newProduct.secondaryVendorId) {
        if (oldProduct.secondaryVendorId) {
          await redis.srem(`${this.REDIS_KEYS.BY_SECONDARY_VENDOR_ID}${oldProduct.secondaryVendorId}`, oldProduct.id.toString());
        }
        if (newProduct.secondaryVendorId) {
          await redis.sadd(`${this.REDIS_KEYS.BY_SECONDARY_VENDOR_ID}${newProduct.secondaryVendorId}`, newProduct.id.toString());
        }
      }

      // 13. Secondary Vendor SKU 索引 - STRING
      if (oldProduct.secondaryVendorProductSku !== newProduct.secondaryVendorProductSku) {
        if (oldProduct.secondaryVendorProductSku) {
          await redis.del(`${this.REDIS_KEYS.BY_SECONDARY_VENDOR_SKU}${oldProduct.secondaryVendorProductSku}`);
        }
        if (newProduct.secondaryVendorProductSku) {
          await redis.set(`${this.REDIS_KEYS.BY_SECONDARY_VENDOR_SKU}${newProduct.secondaryVendorProductSku}`, newProduct.id.toString());
        }
      }

      // 14. Purchase Strategy 索引 - SET
      if (oldProduct.purchaseStrategy !== newProduct.purchaseStrategy) {
        await redis.srem(`${this.REDIS_KEYS.BY_PURCHASE_STRATEGY}${oldProduct.purchaseStrategy}`, oldProduct.id.toString());
        await redis.sadd(`${this.REDIS_KEYS.BY_PURCHASE_STRATEGY}${newProduct.purchaseStrategy}`, newProduct.id.toString());
      }

      // 15. Status 索引 - SET
      if (oldProduct.status !== newProduct.status) {
        await redis.srem(`${this.REDIS_KEYS.BY_STATUS}${oldProduct.status}`, oldProduct.id.toString());
        await redis.sadd(`${this.REDIS_KEYS.BY_STATUS}${newProduct.status}`, newProduct.id.toString());
      }

      // 16. Is Featured 索引 - SET
      if (oldProduct.isFeatured !== newProduct.isFeatured) {
        const oldFeaturedKey = oldProduct.isFeatured ? '1' : '0';
        const newFeaturedKey = newProduct.isFeatured ? '1' : '0';
        await redis.srem(`${this.REDIS_KEYS.BY_IS_FEATURED}${oldFeaturedKey}`, oldProduct.id.toString());
        await redis.sadd(`${this.REDIS_KEYS.BY_IS_FEATURED}${newFeaturedKey}`, newProduct.id.toString());
      }

      // 17. Is Trial 索引 - SET
      if (oldProduct.isTrial !== newProduct.isTrial) {
        const oldTrialKey = oldProduct.isTrial ? '1' : '0';
        const newTrialKey = newProduct.isTrial ? '1' : '0';
        await redis.srem(`${this.REDIS_KEYS.BY_IS_TRIAL}${oldTrialKey}`, oldProduct.id.toString());
        await redis.sadd(`${this.REDIS_KEYS.BY_IS_TRIAL}${newTrialKey}`, newProduct.id.toString());
      }

      // 18. Validity Days 索引 - SET
      if (oldProduct.validityDays !== newProduct.validityDays) {
        if (oldProduct.validityDays !== undefined && oldProduct.validityDays !== null) {
          await redis.srem(`${this.REDIS_KEYS.BY_VALIDITY_DAYS}${oldProduct.validityDays}`, oldProduct.id.toString());
        }
        if (newProduct.validityDays !== undefined && newProduct.validityDays !== null) {
          await redis.sadd(`${this.REDIS_KEYS.BY_VALIDITY_DAYS}${newProduct.validityDays}`, newProduct.id.toString());
        }
      }

    } catch (error) {
      logger.error(`❌ Failed to update indexes for product ${newProduct.id}:`, error);
      throw error;
    }
  }

  /**
   * 删除产品的 Redis 索引
   * 清理所有18个索引
   */
  private async deleteProductIndexes(product: Product): Promise<void> {
    try {
      const redis = this.getRedis();

      // 1. 删除主数据 (BY_ID)
      await redis.del(`${this.REDIS_KEYS.BY_ID}${product.id}`);

      // 2. 删除 SKU 索引 - STRING
      await redis.del(`${this.REDIS_KEYS.BY_SKU}${product.sku}`);

      // 3. 删除 Name 索引 - SET
      if (product.name) {
        await redis.srem(`${this.REDIS_KEYS.BY_NAME}${product.name}`, product.id.toString());
      }

      // 4. 删除 Category 索引 - SET
      if (product.category) {
        await redis.srem(`${this.REDIS_KEYS.BY_CATEGORY}${product.category}`, product.id.toString());
      }

      // 5. 删除 Type 索引 - SET
      await redis.srem(`${this.REDIS_KEYS.BY_TYPE}${product.type}`, product.id.toString());

      // 6. 删除 Issuer Code 索引 - SET
      if (product.issuerCode) {
        await redis.srem(`${this.REDIS_KEYS.BY_ISSUER_CODE}${product.issuerCode}`, product.id.toString());
      }

      // 7. 删除 Issuer Name 索引 - SET
      if (product.issuerName) {
        await redis.srem(`${this.REDIS_KEYS.BY_ISSUER_NAME}${product.issuerName}`, product.id.toString());
      }

      // 8. 删除 Region 索引 - SET
      await redis.srem(`${this.REDIS_KEYS.BY_REGION}${product.region}`, product.id.toString());

      // 9. 删除 Currency 索引 - SET
      await redis.srem(`${this.REDIS_KEYS.BY_CURRENCY}${product.currency}`, product.id.toString());

      // 10. 删除 Primary Vendor ID 索引 - SET
      if (product.primaryVendorId) {
        await redis.srem(`${this.REDIS_KEYS.BY_PRIMARY_VENDOR_ID}${product.primaryVendorId}`, product.id.toString());
      }

      // 11. 删除 Primary Vendor SKU 索引 - STRING
      if (product.primaryVendorProductSku) {
        await redis.del(`${this.REDIS_KEYS.BY_PRIMARY_VENDOR_SKU}${product.primaryVendorProductSku}`);
      }

      // 12. 删除 Secondary Vendor ID 索引 - SET
      if (product.secondaryVendorId) {
        await redis.srem(`${this.REDIS_KEYS.BY_SECONDARY_VENDOR_ID}${product.secondaryVendorId}`, product.id.toString());
      }

      // 13. 删除 Secondary Vendor SKU 索引 - STRING
      if (product.secondaryVendorProductSku) {
        await redis.del(`${this.REDIS_KEYS.BY_SECONDARY_VENDOR_SKU}${product.secondaryVendorProductSku}`);
      }

      // 14. 删除 Purchase Strategy 索引 - SET
      await redis.srem(`${this.REDIS_KEYS.BY_PURCHASE_STRATEGY}${product.purchaseStrategy}`, product.id.toString());

      // 15. 删除 Status 索引 - SET
      await redis.srem(`${this.REDIS_KEYS.BY_STATUS}${product.status}`, product.id.toString());

      // 16. 删除 Is Featured 索引 - SET
      const featuredKey = product.isFeatured ? '1' : '0';
      await redis.srem(`${this.REDIS_KEYS.BY_IS_FEATURED}${featuredKey}`, product.id.toString());

      // 17. 删除 Is Trial 索引 - SET
      const trialKey = product.isTrial ? '1' : '0';
      await redis.srem(`${this.REDIS_KEYS.BY_IS_TRIAL}${trialKey}`, product.id.toString());

      // 18. 删除 Validity Days 索引 - SET
      if (product.validityDays !== undefined && product.validityDays !== null) {
        await redis.srem(`${this.REDIS_KEYS.BY_VALIDITY_DAYS}${product.validityDays}`, product.id.toString());
      }

      // 从所有产品集合中删除
      await redis.srem(this.REDIS_KEYS.ALL_PRODUCTS, product.id.toString());

    } catch (error) {
      logger.error(`❌ Failed to delete indexes for product ${product.id}:`, error);
      throw error;
    }
  }

  /**
   * 创建新产品
   * 流程：数据库插入 → Redis 存储 → 建立索引
   */
  async createProduct(productData: {
    sku: string;
    name: string;
    description?: string | null;
    category?: string | null;
    type: ProductType;
    issuerCode?: string | null;
    issuerName?: string | null;
    region: string;
    faceValue: number;
    currency: string;
    sellingPrice: number;
    costPrice?: number | null;
    discountPrice?: number | null;
    stockQuantity?: number;
    primaryVendorId?: number | null;
    primaryVendorName?: string | null;
    primaryVendorProductSku?: string | null;
    secondaryVendorId?: number | null;
    secondaryVendorName?: string | null;
    secondaryVendorProductSku?: string | null;
    purchaseStrategy?: PurchaseStrategy;
    status?: ProductStatus;
    isFeatured?: boolean;
    isTrial?: boolean;
    displayOrder?: number;
    imageUrl?: string | null;
    iconEmoji?: string | null;
    maxQuantityPerOrder?: number | null;
    maxQuantityPerUser?: number | null;
    purchaseLimitPeriod?: string | null;
    validityDays?: number | null;
    expiryWarningDays?: number | null;
  }): Promise<Product> {
    try {
      logger.info('🆕 Creating new product:', productData.name);

      // 转换数据以匹配 Product 类型（null 转为 undefined）
      const cleanedData: any = {
        ...productData,
        description: productData.description ?? undefined,
        category: productData.category ?? undefined,
        issuerCode: productData.issuerCode ?? undefined,
        issuerName: productData.issuerName ?? undefined,
        costPrice: productData.costPrice ?? undefined,
        discountPrice: productData.discountPrice ?? undefined,
        primaryVendorId: productData.primaryVendorId ?? undefined,
        primaryVendorName: productData.primaryVendorName ?? undefined,
        primaryVendorProductSku: productData.primaryVendorProductSku ?? undefined,
        secondaryVendorId: productData.secondaryVendorId ?? undefined,
        secondaryVendorName: productData.secondaryVendorName ?? undefined,
        secondaryVendorProductSku: productData.secondaryVendorProductSku ?? undefined,
        imageUrl: productData.imageUrl ?? undefined,
        iconEmoji: productData.iconEmoji ?? undefined,
        maxQuantityPerOrder: productData.maxQuantityPerOrder ?? undefined,
        maxQuantityPerUser: productData.maxQuantityPerUser ?? undefined,
        purchaseLimitPeriod: productData.purchaseLimitPeriod ?? undefined,
        validityDays: productData.validityDays ?? undefined,
        expiryWarningDays: productData.expiryWarningDays ?? undefined,
      };

      // 1. 先创建数据库记录以获取 ID
      const product = await productRepository.createProductWithTransaction(cleanedData);

      // 2. 建立索引（包含主数据存储）
      await this.createProductIndexes(product);

      logger.info(`✅ Product created: ${product.name} (ID: ${product.id})`);
      return product;

    } catch (error) {
      logger.error('❌ Failed to create product:', error);
      throw error;
    }
  }

  /**
   * 根据 ID 获取产品
   * 查询流程：Redis → 数据库 → 加载到 Redis
   */
  async getProductById(id: number): Promise<Product | null> {
    try {
      // 1. 先查 Redis
      const redisKey = `${this.REDIS_KEYS.BY_ID}${id}`;
      const data = await this.getRedis().get(redisKey);

      if (data) {
        const productData = JSON.parse(data);
        return Product.fromObject(productData);
      }

      // 2. Redis 没有，查数据库
      logger.info(`Product ${id} not found in Redis, fetching from database`);
      const product = await productRepository.getProductByIdFromDatabase(id);

      if (!product) {
        return null;
      }

      // 3. 加载到 Redis（包含索引）
      await this.createProductIndexes(product);

      return product;

    } catch (error) {
      logger.error('❌ Failed to get product by ID:', error);
      throw error;
    }
  }

  /**
   * 根据产品类型获取产品列表
   */
  async getProductsByType(type: ProductType): Promise<Product[]> {
    try {
      const redis = this.getRedis();
      const productIds = await redis.smembers(`${this.REDIS_KEYS.BY_TYPE}${type}`);

      if (productIds.length === 0) {
        logger.info(`No products found in Redis for type ${type}, fetching from database`);
        const products = await productRepository.getProductsByTypeFromDatabase(type);
        
        // 加载到 Redis
        for (const product of products) {
          await this.createProductIndexes(product);
        }
        
        return products;
      }

      const products: Product[] = [];
      for (const id of productIds) {
        const product = await this.getProductById(parseInt(id));
        if (product) {
          products.push(product);
        }
      }

      return products;

    } catch (error) {
      logger.error('❌ Failed to get products by type:', error);
      throw error;
    }
  }

  /**
   * 根据 SKU 获取产品
   */
  async getProductBySku(sku: string): Promise<Product | null> {
    try {
      // 1. 先查 Redis SKU 索引
      const redis = this.getRedis();
      const productIdStr = await redis.get(`${this.REDIS_KEYS.BY_SKU}${sku}`);

      if (productIdStr) {
        return await this.getProductById(parseInt(productIdStr));
      }

      // 2. Redis 没有，查数据库
      logger.info(`Product with SKU ${sku} not found in Redis, fetching from database`);
      const product = await productRepository.getProductBySkuFromDatabase(sku);

      if (!product) {
        return null;
      }

      // 3. 加载到 Redis
      await this.createProductIndexes(product);

      return product;

    } catch (error) {
      logger.error('❌ Failed to get product by SKU:', error);
      throw error;
    }
  }

  /**
   * 根据发行方代码获取产品列表
   */
  async getProductsByIssuerCode(issuerCode: string): Promise<Product[]> {
    try {
      const redis = this.getRedis();
      const productIds = await redis.smembers(`${this.REDIS_KEYS.BY_ISSUER_CODE}${issuerCode}`);
      const products: Product[] = [];

      for (const id of productIds) {
        const product = await this.getProductById(parseInt(id));
        if (product) {
          products.push(product);
        }
      }

      return products;

    } catch (error) {
      logger.error('❌ Failed to get products by issuer code:', error);
      throw error;
    }
  }

  /**
   * 根据地区获取产品列表
   */
  async getProductsByRegion(region: string): Promise<Product[]> {
    try {
      const redis = this.getRedis();
      const productIds = await redis.smembers(`${this.REDIS_KEYS.BY_REGION}${region}`);
      const products: Product[] = [];

      for (const id of productIds) {
        const product = await this.getProductById(parseInt(id));
        if (product) {
          products.push(product);
        }
      }

      return products;

    } catch (error) {
      logger.error('❌ Failed to get products by region:', error);
      throw error;
    }
  }

  /**
   * 根据币种获取产品列表
   */
  async getProductsByCurrency(currency: string): Promise<Product[]> {
    try {
      const redis = this.getRedis();
      const productIds = await redis.smembers(`${this.REDIS_KEYS.BY_CURRENCY}${currency}`);
      const products: Product[] = [];

      for (const id of productIds) {
        const product = await this.getProductById(parseInt(id));
        if (product) {
          products.push(product);
        }
      }

      return products;

    } catch (error) {
      logger.error('❌ Failed to get products by currency:', error);
      throw error;
    }
  }

  /**
   * 根据采购策略获取产品列表
   */
  async getProductsByPurchaseStrategy(strategy: PurchaseStrategy): Promise<Product[]> {
    try {
      const redis = this.getRedis();
      const productIds = await redis.smembers(`${this.REDIS_KEYS.BY_PURCHASE_STRATEGY}${strategy}`);
      const products: Product[] = [];

      for (const id of productIds) {
        const product = await this.getProductById(parseInt(id));
        if (product) {
          products.push(product);
        }
      }

      return products;

    } catch (error) {
      logger.error('❌ Failed to get products by purchase strategy:', error);
      throw error;
    }
  }

  /**
   * 根据状态获取产品列表
   */
  async getProductsByStatus(status: ProductStatus): Promise<Product[]> {
    try {
      const redis = this.getRedis();
      const productIds = await redis.smembers(`${this.REDIS_KEYS.BY_STATUS}${status}`);

      if (productIds.length === 0) {
        logger.info(`No products found in Redis for status ${status}, fetching from database`);
        const products = await productRepository.getProductsByStatusFromDatabase(status);
        
        // 加载到 Redis
        for (const product of products) {
          await this.createProductIndexes(product);
        }
        
        return products;
      }

      const products: Product[] = [];
      for (const id of productIds) {
        const product = await this.getProductById(parseInt(id));
        if (product) {
          products.push(product);
        }
      }

      return products;

    } catch (error) {
      logger.error('❌ Failed to get products by status:', error);
      throw error;
    }
  }

  /**
   * 获取所有活跃产品（状态为 active）
   */
  async getActiveProducts(): Promise<Product[]> {
    return this.getProductsByStatus(ProductStatus.ACTIVE);
  }

  /**
   * 获取所有可用于试用的产品
   */
  async getTrialProducts(): Promise<Product[]> {
    try {
      const redis = this.getRedis();
      const productIds = await redis.smembers(`${this.REDIS_KEYS.BY_IS_TRIAL}1`);

      if (productIds.length === 0) {
        logger.info('No trial products found in Redis, fetching from database');
        const products = await productRepository.getTrialProductsFromDatabase();
        
        // 加载到 Redis
        for (const product of products) {
          await this.createProductIndexes(product);
        }
        
        return products;
      }

      const products: Product[] = [];
      for (const id of productIds) {
        const product = await this.getProductById(parseInt(id));
        if (product) {
          products.push(product);
        }
      }

      return products;

    } catch (error) {
      logger.error('❌ Failed to get trial products:', error);
      throw error;
    }
  }

  /**
   * 根据分类获取产品列表（NEW - 索引3）
   */
  async getProductsByCategory(category: string): Promise<Product[]> {
    try {
      const redis = this.getRedis();
      const productIds = await redis.smembers(`${this.REDIS_KEYS.BY_CATEGORY}${category}`);

      if (productIds.length === 0) {
        logger.info(`No products found in Redis for category ${category}, fetching from database`);
        const products = await productRepository.getProductsByCategoryFromDatabase(category);
        
        // 加载到 Redis
        for (const product of products) {
          await this.createProductIndexes(product);
        }
        
        return products;
      }

      const products: Product[] = [];
      for (const id of productIds) {
        const product = await this.getProductById(parseInt(id));
        if (product) {
          products.push(product);
        }
      }

      return products;

    } catch (error) {
      logger.error('❌ Failed to get products by category:', error);
      throw error;
    }
  }

  /**
   * 根据发行方名称获取产品列表（NEW - 索引7）
   */
  async getProductsByIssuerName(issuerName: string): Promise<Product[]> {
    try {
      const redis = this.getRedis();
      const productIds = await redis.smembers(`${this.REDIS_KEYS.BY_ISSUER_NAME}${issuerName}`);
      const products: Product[] = [];

      for (const id of productIds) {
        const product = await this.getProductById(parseInt(id));
        if (product) {
          products.push(product);
        }
      }

      return products;

    } catch (error) {
      logger.error('❌ Failed to get products by issuer name:', error);
      throw error;
    }
  }

  /**
   * 获取所有推荐产品（NEW - 索引16）
   */
  async getFeaturedProducts(): Promise<Product[]> {
    try {
      const redis = this.getRedis();
      const productIds = await redis.smembers(`${this.REDIS_KEYS.BY_IS_FEATURED}1`);

      if (productIds.length === 0) {
        logger.info('No featured products found in Redis, fetching from database');
        const products = await productRepository.getFeaturedProductsFromDatabase();
        
        // 加载到 Redis
        for (const product of products) {
          await this.createProductIndexes(product);
        }
        
        return products;
      }

      const products: Product[] = [];
      for (const id of productIds) {
        const product = await this.getProductById(parseInt(id));
        if (product) {
          products.push(product);
        }
      }

      return products;

    } catch (error) {
      logger.error('❌ Failed to get featured products:', error);
      throw error;
    }
  }

  /**
   * 根据有效天数获取产品列表（NEW - 索引18）
   */
  async getProductsByValidityDays(validityDays: number): Promise<Product[]> {
    try {
      const redis = this.getRedis();
      const productIds = await redis.smembers(`${this.REDIS_KEYS.BY_VALIDITY_DAYS}${validityDays}`);
      const products: Product[] = [];

      for (const id of productIds) {
        const product = await this.getProductById(parseInt(id));
        if (product) {
          products.push(product);
        }
      }

      return products;

    } catch (error) {
      logger.error('❌ Failed to get products by validity days:', error);
      throw error;
    }
  }

  /**
   * 获取所有产品
   */
  async getAllProducts(): Promise<Product[]> {
    try {
      const redis = this.getRedis();
      const productIds = await redis.smembers(this.REDIS_KEYS.ALL_PRODUCTS);

      if (productIds.length === 0) {
        logger.info('No products found in Redis, fetching from database');
        const products = await productRepository.getAllProductsFromDatabase();
        
        // 加载到 Redis
        for (const product of products) {
          await this.createProductIndexes(product);
        }
        
        return products;
      }

      const products: Product[] = [];
      for (const id of productIds) {
        const product = await this.getProductById(parseInt(id));
        if (product) {
          products.push(product);
        }
      }

      return products;

    } catch (error) {
      logger.error('❌ Failed to get all products:', error);
      throw error;
    }
  }

  /**
   * 更新产品
   * 流程：Redis 更新 → 数据库更新 → 索引更新
   */
  async updateProduct(id: number, updates: Partial<{
    sku: string;
    name: string;
    description: string | null;
    category: string | null;
    type: ProductType;
    issuerCode: string | null;
    issuerName: string | null;
    region: string;
    faceValue: number;
    currency: string;
    sellingPrice: number;
    costPrice: number | null;
    discountPrice: number | null;
    stockQuantity: number;
    reservedQuantity: number;
    soldQuantity: number;
    primaryVendorId: number | null;
    primaryVendorName: string | null;
    primaryVendorProductSku: string | null;
    secondaryVendorId: number | null;
    secondaryVendorName: string | null;
    secondaryVendorProductSku: string | null;
    purchaseStrategy: PurchaseStrategy;
    status: ProductStatus;
    isFeatured: boolean;
    isTrial: boolean;
    displayOrder: number;
    imageUrl: string | null;
    iconEmoji: string | null;
    maxQuantityPerOrder: number | null;
    maxQuantityPerUser: number | null;
    purchaseLimitPeriod: string | null;
    validityDays: number | null;
    expiryWarningDays: number | null;
  }>, needUpdateDB: boolean = true): Promise<Product> {
    try {
      logger.info(`🔄 Updating product: ${id}`, JSON.stringify(updates));

      const existingProduct = await this.getProductById(id);
      if (!existingProduct) {
        throw new Error(`Product not found: ${id}`);
      }

      // 记录旧状态用于索引更新
      const oldProduct = Product.fromObject(existingProduct.toObject());

      // 过滤掉 undefined 值
      const filteredUpdates: any = {};
      Object.keys(updates).forEach(key => {
        if ((updates as any)[key] !== undefined) {
          filteredUpdates[key] = (updates as any)[key];
        }
      });

      // 合并更新数据
      Object.assign(existingProduct, filteredUpdates);
      existingProduct.updatedAt = Date.now();

      // 更新 Redis
      const redisKey = `${this.REDIS_KEYS.BY_ID}${id}`;
      await this.getRedis().set(redisKey, JSON.stringify(existingProduct.toObject()));

      // 更新索引
      await this.updateProductIndexes(oldProduct, existingProduct);

      // 同时更新数据库
      if (needUpdateDB) {
        await productRepository.updateProductInDatabase(existingProduct);
      }

      logger.info(`✅ Product updated: ${existingProduct.name} (ID: ${id})`);
      return existingProduct;

    } catch (error) {
      logger.error(`❌ Failed to update product ${id}:`, error);
      throw error;
    }
  }

  /**
   * 删除产品
   * 流程：从 Redis 删除 → 从数据库删除 → 删除索引
   */
  async deleteProduct(id: number): Promise<void> {
    try {
      const product = await this.getProductById(id);
      if (!product) {
        throw new Error(`Product not found: ${id}`);
      }

      // 1. 从 Redis 删除
      const redisKey = `${this.REDIS_KEYS.BY_ID}${id}`;
      await this.getRedis().del(redisKey);

      // 2. 删除索引
      await this.deleteProductIndexes(product);

      // 3. 从数据库删除
      await productRepository.deleteProductFromDatabase(id);

      logger.info(`✅ Product deleted: ${product.name} (ID: ${id})`);

    } catch (error) {
      logger.error('❌ Failed to delete product:', error);
      throw error;
    }
  }

  /**
   * 检查产品是否可售
   * @param product 产品对象
   * @returns 是否可售及原因
   */
  isProductAvailable(product: Product): { available: boolean; reason?: string } {
    // 检查产品状态
    if (product.status !== ProductStatus.ACTIVE) {
      return {
        available: false,
        reason: `产品状态为 ${product.status}，不可售`
      };
    }

    // 检查库存（如果启用库存管理）
    if (product.stockQuantity !== undefined && product.stockQuantity <= 0) {
      return {
        available: false,
        reason: '庫存不足'
      };
    }

    // 检查软删除
    if (product.deletedAt) {
      return {
        available: false,
        reason: '产品已删除'
      };
    }

    return { available: true };
  }

  /**
   * 检查产品库存
   * @param product 产品对象
   * @param requestedQuantity 请求数量（默认1）
   * @returns 库存检查结果
   */
  checkProductStock(
    product: Product,
    requestedQuantity: number = 1
  ): {
    hasStock: boolean;
    availableQuantity: number;
    reservedQuantity: number;
    message?: string;
  } {
    const { stockQuantity, reservedQuantity } = product;

    // 计算可用库存 = 总库存 - 已预留
    const availableQuantity = stockQuantity - reservedQuantity;

    // 检查是否有足够库存
    if (availableQuantity < requestedQuantity) {
      return {
        hasStock: false,
        availableQuantity,
        reservedQuantity,
        message: `庫存不足：需要 ${requestedQuantity}，可用 ${availableQuantity}`
      };
    }

    return {
      hasStock: true,
      availableQuantity,
      reservedQuantity
    };
  }

  /**
   * 验证产品完整性（综合验证）
   * @param product 产品对象
   * @param requestedQuantity 请求数量（默认1）
   * @returns 验证结果
   */
  validateProduct(
    product: Product,
    requestedQuantity: number = 1
  ): {
    valid: boolean;
    errors: string[];
  } {
    const errors: string[] = [];

    // 检查产品可售性
    const availabilityCheck = this.isProductAvailable(product);
    if (!availabilityCheck.available) {
      errors.push(availabilityCheck.reason!);
    }

    // 检查库存
    const stockCheck = this.checkProductStock(product, requestedQuantity);
    if (!stockCheck.hasStock) {
      errors.push(stockCheck.message!);
    }

    // 检查价格
    if (!product.sellingPrice || product.sellingPrice <= 0) {
      errors.push('产品售价无效');
    }

    // 检查SKU
    if (!product.sku) {
      errors.push('产品SKU缺失');
    }

    // 检查采购策略
    if (!product.purchaseStrategy) {
      errors.push('产品采购策略未设置');
    }

    // 检查主供应商（如果不是自营）
    if (
      product.purchaseStrategy !== PurchaseStrategy.SELF_DIRECT &&
      !product.primaryVendorId
    ) {
      errors.push('产品缺少主供应商配置');
    }

    return {
      valid: errors.length === 0,
      errors
    };
  }

  /**
   * 清理所有 Redis 数据（主数据和索引）
   */
  async clearAllRedisData(): Promise<void> {
    try {
      logger.info('🧹 Clearing all product Redis data...');

      const redis = this.getRedis();

      // 删除所有产品主数据和索引
      const keys: string[] = [];
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_ID}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_SKU}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_NAME}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_CATEGORY}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_TYPE}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_ISSUER_CODE}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_ISSUER_NAME}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_REGION}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_CURRENCY}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_PRIMARY_VENDOR_ID}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_PRIMARY_VENDOR_SKU}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_SECONDARY_VENDOR_ID}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_SECONDARY_VENDOR_SKU}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_PURCHASE_STRATEGY}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_STATUS}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_IS_FEATURED}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_IS_TRIAL}*`));
      keys.push(...await redis.keys(`${this.REDIS_KEYS.BY_VALIDITY_DAYS}*`));
      
      // 删除统计和元数据
      const metaKeys = [
        this.REDIS_KEYS.ALL_PRODUCTS,
        this.REDIS_KEYS.STATS,
        this.REDIS_KEYS.LAST_UPDATE
      ];
      
      for (const key of metaKeys) {
        if (await redis.exists(key)) {
          keys.push(key);
        }
      }

      if (keys.length > 0) {
        await redis.del(...keys);
      }

      logger.info(`✅ Cleared ${keys.length} product Redis keys (main data + indexes + metadata)`);

    } catch (error) {
      logger.error('❌ Failed to clear product Redis data:', error);
      throw error;
    }
  }

  /**
   * 停止服务
   */
  async stop(): Promise<void> {
    try {
      logger.info('⏸  Stopping ProductService...');
      this.isRunning = false;
      
      // 清空 Redis 中的所有产品数据
      await this.clearAllRedisData();
      
      logger.info('✅ ProductService stopped and Redis data cleared');
    } catch (error) {
      logger.error('❌ Failed to stop ProductService:', error);
      throw error;
    }
  }

  /**
   * 获取服务状态
   */
  getServiceStatus(): { isInitialized: boolean; isRunning: boolean; lastUpdateTime: number | null } {
    return {
      isInitialized: this.isInitialized,
      isRunning: this.isRunning,
      lastUpdateTime: this.lastUpdateTime
    };
  }
  
  /**
   * 更新产品的库存统计信息
   * 从 inventory 表统计并更新到 product 表和 Redis
   * @param productId 产品ID
   * @param stats 库存统计数据 (available, reserved, sold)
   */
  async updateProductStockStats(productId: number, stats: {
    available: number;
    reserved: number;
    sold: number;
  }): Promise<Product | null> {
    try {
      logger.info(`📦 Updating product stock stats: ID ${productId}, available=${stats.available}, reserved=${stats.reserved}, sold=${stats.sold}`);
      
      // 1. 获取产品
      const product = await this.getProductById(productId);
      if (!product) {
        logger.warn(`⚠️ Product not found: ${productId}`);
        return null;
      }
      
      // 2. 更新产品对象
      // stockQuantity = available (可用的库存)
      product.stockQuantity = stats.available;
      product.reservedQuantity = stats.reserved;
      product.soldQuantity = stats.sold;
      product.updatedAt = Date.now();
      
      // 3. 更新 Redis
      const redis = getRedisClient();
      if (redis) {
        const redisKey = `${this.REDIS_KEYS.BY_ID}${productId}`;
        await redis.set(redisKey, JSON.stringify(product.toObject()));
      }
      
      // 4. 更新数据库
      await productRepository.updateProductStockStats(productId, {
        stockQuantity: stats.available,
        reservedQuantity: stats.reserved,
        soldQuantity: stats.sold
      });
      
      logger.info(`✅ Product stock stats updated: ID ${productId}`);
      return product;
      
    } catch (error) {
      logger.error(`❌ Failed to update product stock stats for ID ${productId}:`, error);
      throw error;
    }
  }

  /**
   * 增加产品的预留数量
   * @param productId 产品ID
   * @param quantity 增加的数量
   */
  async incrementReservedQuantity(productId: number, quantity: number = 1): Promise<void> {
    try {
      const product = await this.getProductById(productId);
      if (!product) {
        logger.warn(`⚠️ Product not found: ${productId}`);
        return;
      }

      product.reserveStock(quantity);

      // 更新 Redis
      const redis = getRedisClient();
      if (redis) {
        const redisKey = `${this.REDIS_KEYS.BY_ID}${productId}`;
        await redis.set(redisKey, JSON.stringify(product.toObject()));
      }

      // 更新数据库
      await productRepository.updateProductStockStats(productId, {
        stockQuantity: product.stockQuantity,
        reservedQuantity: product.reservedQuantity,
        soldQuantity: product.soldQuantity
      });

      logger.info(`✅ Product ${productId} reservedQuantity increased by ${quantity} (now: ${product.reservedQuantity})`);
    } catch (error) {
      logger.error(`❌ Failed to increment reserved quantity for product ${productId}:`, error);
      throw error;
    }
  }

  /**
   * 减少产品的预留数量
   * @param productId 产品ID
   * @param quantity 减少的数量
   */
  async decrementReservedQuantity(productId: number, quantity: number = 1): Promise<void> {
    try {
      const product = await this.getProductById(productId);
      if (!product) {
        logger.warn(`⚠️ Product not found: ${productId}`);
        return;
      }

      product.releaseReservedStock(quantity);

      // 更新 Redis
      const redis = getRedisClient();
      if (redis) {
        const redisKey = `${this.REDIS_KEYS.BY_ID}${productId}`;
        await redis.set(redisKey, JSON.stringify(product.toObject()));
      }

      // 更新数据库
      await productRepository.updateProductStockStats(productId, {
        stockQuantity: product.stockQuantity,
        reservedQuantity: product.reservedQuantity,
        soldQuantity: product.soldQuantity
      });

      logger.info(`✅ Product ${productId} reservedQuantity decreased by ${quantity} (now: ${product.reservedQuantity})`);
    } catch (error) {
      logger.error(`❌ Failed to decrement reserved quantity for product ${productId}:`, error);
      throw error;
    }
  }

  /**
   * 同步单个产品的库存统计到 relinx_product 表及 Redis 缓存
   * 
   * @param productId 产品ID
   * @returns 是否同步成功
   */
  async syncProductInventoryStats(productId: number): Promise<boolean> {
    try {
      // 1. 获取库存统计 (from inventory table)
      const stats = await inventoryRepository.countInventoryByProductId(productId);
      
      // 2. 更新数据库
      await productRepository.updateProductStockStats(productId, {
        stockQuantity: stats.available,
        reservedQuantity: stats.reserved,
        soldQuantity: stats.sold
      });

      // 3. 同步到 Redis 缓存
      // 获取当前产品对象
      const product = await this.getProductById(productId);
      if (product) {
        product.stockQuantity = stats.available;
        product.reservedQuantity = stats.reserved;
        product.soldQuantity = stats.sold;
        
        // 重新索引以更新 Redis 中的数据 (BY_ID 及其它)
        await this.createProductIndexes(product);
      }

      logger.info(
        `[ProductService] ✅ Synced product ${productId}: ` +
        `stock=${stats.available}, reserved=${stats.reserved}, sold=${stats.sold}`
      );

      return true;
    } catch (error) {
      logger.error(`[ProductService] Failed to sync inventory stats for product ${productId}:`, error);
      return false;
    }
  }

  /**
   * 同步所有产品的库存统计
   * 遍历所有有库存记录的产品，更新其库存统计
   * 
   * @returns 成功同步的产品数量
   */
  async syncAllProductsInventoryStats(): Promise<number> {
    try {
      logger.info('[ProductService] Starting full inventory sync...');

      // 1. 获取所有产品的库存统计
      const allStats = await inventoryRepository.getAllProductsInventoryStats();

      if (allStats.length === 0) {
        logger.info('[ProductService] No inventory records to syntc');
        return 0;
      }

      logger.info(`[ProductService] Found ${allStats.length} products to sync`);

      let successCount = 0;
      
      // 2. 逐个同步产品的库存统计
      for (const stats of allStats) {
        try {
          // 更新数据库
          await productRepository.updateProductStockStats(stats.productId, {
            stockQuantity: stats.available,
            reservedQuantity: stats.reserved,
            soldQuantity: stats.sold
          });

          // 同步到 Redis
          const product = await this.getProductById(stats.productId);
          if (product) {
            product.stockQuantity = stats.available;
            product.reservedQuantity = stats.reserved;
            product.soldQuantity = stats.sold;
            await this.createProductIndexes(product);
          }

          successCount++;
        } catch (error) {
          logger.error(`[ProductService] Failed to sync product ${stats.productId}:`, error);
        }
      }

      logger.info(`[ProductService] Full inventory sync completed. Success: ${successCount}/${allStats.length}`);
      return successCount;

    } catch (error) {
      logger.error('[ProductService] Failed to sync all products inventory stats:', error);
      throw error;
    }
  }

  /**
   * 验证库存统计的一致性
   * 检查 relinx_product 表中的统计数字是否与 relinx_inventory 表一致
   * 
   * @returns 验证结果
   */
  async validateInventorySyncConsistency(): Promise<{
    totalProducts: number;
    consistentCount: number;
    inconsistentProducts: Array<{
      productId: number;
      expected: { stockQuantity: number; reservedQuantity: number; soldQuantity: number };
      actual: { stockQuantity: number; reservedQuantity: number; soldQuantity: number };
    }>;
  }> {
    try {
      logger.info('[ProductService] Starting inventory sync consistency validation...');

      const inconsistentProducts: any[] = [];

      // 1. 获取所有产品的库存统计（从 inventory 表）
      const expectedStats = await inventoryRepository.getAllProductsInventoryStats();

      if (expectedStats.length === 0) {
        logger.info('[ProductService] No inventory records to validate');
        return {
          totalProducts: 0,
          consistentCount: 0,
          inconsistentProducts: []
        };
      }

      // 2. 检查每个产品的统计是否一致
      let consistentCount = 0;
      for (const expected of expectedStats) {
        const product = await this.getProductById(expected.productId);

        if (!product) {
          inconsistentProducts.push({
            productId: expected.productId,
            expected: { 
              stockQuantity: expected.available, 
              reservedQuantity: expected.reserved, 
              soldQuantity: expected.sold 
            },
            actual: { stockQuantity: 0, reservedQuantity: 0, soldQuantity: 0 }
          });
          continue;
        }

        if (
          product.stockQuantity === expected.available &&
          product.reservedQuantity === expected.reserved &&
          product.soldQuantity === expected.sold
        ) {
          consistentCount++;
        } else {
          inconsistentProducts.push({
            productId: expected.productId,
            expected: { 
              stockQuantity: expected.available, 
              reservedQuantity: expected.reserved, 
              soldQuantity: expected.sold 
            },
            actual: { 
              stockQuantity: product.stockQuantity, 
              reservedQuantity: product.reservedQuantity, 
              soldQuantity: product.soldQuantity 
            }
          });
        }
      }

      logger.info(
        `[ProductService] ✅ Validation completed: ` +
        `${consistentCount}/${expectedStats.length} products consistent, ` +
        `${inconsistentProducts.length} inconsistent`
      );

      return {
        totalProducts: expectedStats.length,
        consistentCount,
        inconsistentProducts
      };

    } catch (error) {
      logger.error('[ProductService] Failed to validate inventory sync consistency:', error);
      throw error;
    }
  }

  /**
   * 增加产品的已售数量
   * @param productId 产品ID
   * @param quantity 增加的数量
   */
  async incrementSoldQuantity(productId: number, quantity: number = 1): Promise<void> {
    try {
      const product = await this.getProductById(productId);
      if (!product) {
        logger.warn(`⚠️ Product not found: ${productId}`);
        return;
      }

      product.recordSale(quantity);

      // 更新 Redis
      const redis = getRedisClient();
      if (redis) {
        const redisKey = `${this.REDIS_KEYS.BY_ID}${productId}`;
        await redis.set(redisKey, JSON.stringify(product.toObject()));
      }

      // 更新数据库
      await productRepository.updateProductStockStats(productId, {
        stockQuantity: product.stockQuantity,
        reservedQuantity: product.reservedQuantity,
        soldQuantity: product.soldQuantity
      });

      logger.info(`✅ Product ${productId} soldQuantity increased by ${quantity} (now: ${product.soldQuantity})`);
    } catch (error) {
      logger.error(`❌ Failed to increment sold quantity for product ${productId}:`, error);
      throw error;
    }
  }
}

// 导出单例实例
export const productService = new ProductService();
export default productService;
