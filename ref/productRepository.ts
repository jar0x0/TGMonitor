// bot/src/repositories/productRepository.ts
import pool from '../config/database';
import { Product, ProductType, ProductStatus, PurchaseStrategy, PurchaseLimitPeriod } from '../types/product';
import { logger } from '../utils/logger';
import { RowDataPacket } from 'mysql2';

/**
 * ProductRepository - 产品数据库访问层
 * 负责 relinx_product 表的增删改查操作
 */
export class ProductRepository {
  constructor() {
    // Only database operations, no Redis operations
  }

  /**
   * 创建新产品（带事务）- 返回带有数据库生成ID的产品
   */
  async createProductWithTransaction(productData: Partial<Product>): Promise<Product> {
    let connection;
    try {
      connection = await pool.getConnection();
      await connection.beginTransaction();

      const product = new Product(productData);
      const query = `
        INSERT INTO relinx_product (
          sku, name, description, category, type,
          issuer_code, issuer_name, region,
          face_value, currency, selling_price, cost_price, discount_price,
          stock_quantity, reserved_quantity, sold_quantity,
          primary_vendor_id, primary_vendor_name, primary_vendor_product_sku,
          secondary_vendor_id, secondary_vendor_name, secondary_vendor_product_sku,
          purchase_strategy, status, is_featured, is_trial,
          display_order, image_url, icon_emoji,
          max_quantity_per_order, max_quantity_per_user, purchase_limit_period,
          validity_days, expiry_warning_days, message,
          created_at, updated_at, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `;

      const [result]: any = await connection.execute(query, [
        product.sku, product.name, product.description, product.category, product.type,
        product.issuerCode, product.issuerName, product.region,
        product.faceValue, product.currency, product.sellingPrice, product.costPrice, product.discountPrice,
        product.stockQuantity, product.reservedQuantity, product.soldQuantity,
        product.primaryVendorId, product.primaryVendorName, product.primaryVendorProductSku,
        product.secondaryVendorId, product.secondaryVendorName, product.secondaryVendorProductSku,
        product.purchaseStrategy, product.status, product.isFeatured ? 1 : 0, product.isTrial ? 1 : 0,
        product.displayOrder, product.imageUrl, product.iconEmoji,
        product.maxQuantityPerOrder, product.maxQuantityPerUser, product.purchaseLimitPeriod,
        product.validityDays, product.expiryWarningDays, product.message || null,
        product.createdAt, product.updatedAt, product.deletedAt || null
      ]);

      product.id = result.insertId;
      await connection.commit();
      logger.info(`✅ Product created in database: ${product.name} (ID: ${product.id})`);
      return product;

    } catch (error) {
      if (connection) await connection.rollback();
      logger.error('❌ Failed to create product with transaction:', error);
      throw error;
    } finally {
      if (connection) connection.release();
    }
  }

  /**
   * 保存产品到数据库（由 ProductService 调用）
   * 如果存在则更新，不存在则插入
   */
  async saveProductToDatabase(product: Product): Promise<void> {
    try {
      const existingProduct = product.id ? await this.getProductByIdFromDatabase(product.id) : null;

      if (existingProduct) {
        await this.updateProductInDatabase(product);
      } else {
        const created = await this.createProductWithTransaction(product);
        product.id = created.id;
      }
    } catch (error) {
      logger.error('❌ Failed to save product to database:', error);
      throw error;
    }
  }

  /**
   * 根据 ID 从数据库获取产品
   */
  async getProductByIdFromDatabase(id: number): Promise<Product | null> {
    try {
      const query = `SELECT * FROM relinx_product WHERE id = ? AND deleted_at IS NULL LIMIT 1`;
      const [rows] = await pool.execute<RowDataPacket[]>(query, [id]);
      return rows.length > 0 ? this.rowToProduct(rows[0]) : null;
    } catch (error) {
      logger.error('❌ Failed to get product by ID from database:', error);
      throw error;
    }
  }

  /**
   * 根据 SKU 从数据库获取产品
   */
  async getProductBySkuFromDatabase(sku: string): Promise<Product | null> {
    try {
      const query = `SELECT * FROM relinx_product WHERE sku = ? AND deleted_at IS NULL LIMIT 1`;
      const [rows] = await pool.execute<RowDataPacket[]>(query, [sku]);
      return rows.length > 0 ? this.rowToProduct(rows[0]) : null;
    } catch (error) {
      logger.error('❌ Failed to get product by SKU from database:', error);
      throw error;
    }
  }

  /**
   * 根据分类获取产品列表
   */
  async getProductsByCategoryFromDatabase(category: string): Promise<Product[]> {
    try {
      const query = `SELECT * FROM relinx_product WHERE category = ? AND deleted_at IS NULL ORDER BY display_order ASC`;
      const [rows] = await pool.execute<RowDataPacket[]>(query, [category]);
      return rows.map(row => this.rowToProduct(row));
    } catch (error) {
      logger.error('❌ Failed to get products by category from database:', error);
      throw error;
    }
  }

  /**
   * 根据类型获取产品列表
   */
  async getProductsByTypeFromDatabase(type: ProductType): Promise<Product[]> {
    try {
      const query = `SELECT * FROM relinx_product WHERE type = ? AND deleted_at IS NULL ORDER BY display_order ASC`;
      const [rows] = await pool.execute<RowDataPacket[]>(query, [type]);
      return rows.map(row => this.rowToProduct(row));
    } catch (error) {
      logger.error('❌ Failed to get products by type from database:', error);
      throw error;
    }
  }

  /**
   * 根据运营商代码获取产品列表
   */
  async getProductsByIssuerCodeFromDatabase(issuerCode: string): Promise<Product[]> {
    try {
      const query = `SELECT * FROM relinx_product WHERE issuer_code = ? AND deleted_at IS NULL ORDER BY display_order ASC`;
      const [rows] = await pool.execute<RowDataPacket[]>(query, [issuerCode]);
      return rows.map(row => this.rowToProduct(row));
    } catch (error) {
      logger.error('❌ Failed to get products by issuer code from database:', error);
      throw error;
    }
  }

  /**
   * 根据地区获取产品列表
   */
  async getProductsByRegionFromDatabase(region: string): Promise<Product[]> {
    try {
      const query = `SELECT * FROM relinx_product WHERE region = ? AND deleted_at IS NULL ORDER BY display_order ASC`;
      const [rows] = await pool.execute<RowDataPacket[]>(query, [region]);
      return rows.map(row => this.rowToProduct(row));
    } catch (error) {
      logger.error('❌ Failed to get products by region from database:', error);
      throw error;
    }
  }

  /**
   * 根据状态获取产品列表
   */
  async getProductsByStatusFromDatabase(status: ProductStatus): Promise<Product[]> {
    try {
      const query = `SELECT * FROM relinx_product WHERE status = ? AND deleted_at IS NULL ORDER BY display_order ASC`;
      const [rows] = await pool.execute<RowDataPacket[]>(query, [status]);
      return rows.map(row => this.rowToProduct(row));
    } catch (error) {
      logger.error('❌ Failed to get products by status from database:', error);
      throw error;
    }
  }

  /**
   * 获取推荐产品列表
   */
  async getFeaturedProductsFromDatabase(): Promise<Product[]> {
    try {
      const query = `SELECT * FROM relinx_product WHERE is_featured = 1 AND status = 'ACTIVE' AND deleted_at IS NULL ORDER BY display_order ASC`;
      const [rows] = await pool.execute<RowDataPacket[]>(query);
      return rows.map(row => this.rowToProduct(row));
    } catch (error) {
      logger.error('❌ Failed to get featured products from database:', error);
      throw error;
    }
  }

  /**
   * 获取试单产品列表
   */
  async getTrialProductsFromDatabase(): Promise<Product[]> {
    try {
      const query = `SELECT * FROM relinx_product WHERE is_trial = 1 AND status = 'ACTIVE' AND deleted_at IS NULL ORDER BY display_order ASC`;
      const [rows] = await pool.execute<RowDataPacket[]>(query);
      return rows.map(row => this.rowToProduct(row));
    } catch (error) {
      logger.error('❌ Failed to get trial products from database:', error);
      throw error;
    }
  }

  /**
   * 根据主供应商ID获取产品列表
   */
  async getProductsByPrimaryVendorIdFromDatabase(vendorId: number): Promise<Product[]> {
    try {
      const query = `SELECT * FROM relinx_product WHERE primary_vendor_id = ? AND deleted_at IS NULL ORDER BY display_order ASC`;
      const [rows] = await pool.execute<RowDataPacket[]>(query, [vendorId]);
      return rows.map(row => this.rowToProduct(row));
    } catch (error) {
      logger.error('❌ Failed to get products by primary vendor ID from database:', error);
      throw error;
    }
  }

  /**
   * 获取所有产品
   */
  async getAllProductsFromDatabase(): Promise<Product[]> {
    try {
      const query = `SELECT * FROM relinx_product WHERE deleted_at IS NULL ORDER BY display_order ASC`;
      const [rows] = await pool.execute<RowDataPacket[]>(query);
      return rows.map(row => this.rowToProduct(row));
    } catch (error) {
      logger.error('❌ Failed to get all products from database:', error);
      throw error;
    }
  }

  /**
   * 更新产品到数据库
   */
  async updateProductInDatabase(product: Product): Promise<void> {
    try {
      const query = `
        UPDATE relinx_product SET
          sku = ?, name = ?, description = ?, category = ?, type = ?,
          issuer_code = ?, issuer_name = ?, region = ?,
          face_value = ?, currency = ?, selling_price = ?, cost_price = ?, discount_price = ?,
          stock_quantity = ?, reserved_quantity = ?, sold_quantity = ?,
          primary_vendor_id = ?, primary_vendor_name = ?, primary_vendor_product_sku = ?,
          secondary_vendor_id = ?, secondary_vendor_name = ?, secondary_vendor_product_sku = ?,
          purchase_strategy = ?, status = ?, is_featured = ?, is_trial = ?,
          display_order = ?, image_url = ?, icon_emoji = ?,
          max_quantity_per_order = ?, max_quantity_per_user = ?, purchase_limit_period = ?,
          validity_days = ?, expiry_warning_days = ?, message = ?,
          updated_at = ?, deleted_at = ?
        WHERE id = ?
      `;

      await pool.execute(query, [
        product.sku, product.name, product.description, product.category, product.type,
        product.issuerCode, product.issuerName, product.region,
        product.faceValue, product.currency, product.sellingPrice, product.costPrice, product.discountPrice,
        product.stockQuantity, product.reservedQuantity, product.soldQuantity,
        product.primaryVendorId, product.primaryVendorName, product.primaryVendorProductSku,
        product.secondaryVendorId, product.secondaryVendorName, product.secondaryVendorProductSku,
        product.purchaseStrategy, product.status, product.isFeatured ? 1 : 0, product.isTrial ? 1 : 0,
        product.displayOrder, product.imageUrl, product.iconEmoji,
        product.maxQuantityPerOrder, product.maxQuantityPerUser, product.purchaseLimitPeriod,
        product.validityDays, product.expiryWarningDays, product.message || null,
        product.updatedAt, product.deletedAt || null,
        product.id
      ]);

      logger.info(`✅ Product updated in database: ${product.name} (ID: ${product.id})`);
    } catch (error) {
      logger.error('❌ Failed to update product in database:', error);
      throw error;
    }
  }

  /**
   * 软删除产品
   */
  async deleteProductFromDatabase(id: number): Promise<void> {
    try {
      const query = `UPDATE relinx_product SET deleted_at = ?, status = 'DISCONTINUED' WHERE id = ?`;
      await pool.execute(query, [Date.now(), id]);
      logger.info(`✅ Product soft deleted from database: ID ${id}`);
    } catch (error) {
      logger.error('❌ Failed to delete product from database:', error);
      throw error;
    }
  }

  /**
   * 将数据库行转换为 Product 对象
   */
  private rowToProduct(row: RowDataPacket): Product {
    return new Product({
      id: row.id,
      sku: row.sku,
      name: row.name,
      description: row.description,
      category: row.category,
      type: row.type as ProductType,
      issuerCode: row.issuer_code,
      issuerName: row.issuer_name,
      region: row.region,
      faceValue: row.face_value ? parseFloat(row.face_value) : undefined,
      currency: row.currency,
      sellingPrice: row.selling_price ? parseFloat(row.selling_price) : undefined,
      costPrice: row.cost_price ? parseFloat(row.cost_price) : undefined,
      discountPrice: row.discount_price ? parseFloat(row.discount_price) : undefined,
      stockQuantity: row.stock_quantity || 0,
      reservedQuantity: row.reserved_quantity || 0,
      soldQuantity: row.sold_quantity || 0,
      primaryVendorId: row.primary_vendor_id,
      primaryVendorName: row.primary_vendor_name,
      primaryVendorProductSku: row.primary_vendor_product_sku,
      secondaryVendorId: row.secondary_vendor_id,
      secondaryVendorName: row.secondary_vendor_name,
      secondaryVendorProductSku: row.secondary_vendor_product_sku,
      purchaseStrategy: row.purchase_strategy as PurchaseStrategy,
      status: row.status as ProductStatus,
      isFeatured: row.is_featured === 1,
      isTrial: row.is_trial === 1,
      displayOrder: row.display_order || 0,
      imageUrl: row.image_url,
      iconEmoji: row.icon_emoji,
      maxQuantityPerOrder: row.max_quantity_per_order,
      maxQuantityPerUser: row.max_quantity_per_user,
      purchaseLimitPeriod: row.purchase_limit_period as PurchaseLimitPeriod,
      validityDays: row.validity_days,
      expiryWarningDays: row.expiry_warning_days || 7,
      message: row.message,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
      deletedAt: row.deleted_at
    });
  }

  /**
   * 将 camelCase 转换为 snake_case
   */
  private camelToSnake(str: string): string {
    return str.replace(/[A-Z]/g, letter => `_${letter.toLowerCase()}`);
  }
  
  /**
   * 更新产品的库存统计信息
   * @param productId 产品ID
   * @param stats 库存统计数据
   */
  async updateProductStockStats(productId: number, stats: {
    stockQuantity: number;
    reservedQuantity: number;
    soldQuantity: number;
  }): Promise<void> {
    try {
      const query = `
        UPDATE relinx_product SET
          stock_quantity = ?,
          reserved_quantity = ?,
          sold_quantity = ?,
          updated_at = ?
        WHERE id = ?
      `;
      
      await pool.execute(query, [
        stats.stockQuantity,
        stats.reservedQuantity,
        stats.soldQuantity,
        Date.now(),
        productId
      ]);
      
      logger.info(`✅ Product stock stats updated: ID ${productId} (stock: ${stats.stockQuantity}, reserved: ${stats.reservedQuantity}, sold: ${stats.soldQuantity})`);
      
    } catch (error) {
      logger.error('❌ Failed to update product stock stats:', error);
      throw error;
    }
  }
}

// 导出单例实例
export const productRepository = new ProductRepository();
export default productRepository;
