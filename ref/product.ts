// bot/src/types/product.ts

import { FiatCurrency } from './currency';

/**
 * 产品类型枚举（交付类型）
 */
export enum ProductType {
  GIFT_CARD = 'GIFT_CARD',       // 卡密
  DIRECT_TOPUP = 'DIRECT_TOPUP'  // 直充
}

/**
 * 采购策略枚举
 */
export enum PurchaseStrategy {
  SELF_INVENTORY_FIRST = 'SELF_INVENTORY_FIRST',   // 优先使用自有库存
  VENDOR_DIRECT = 'VENDOR_DIRECT',                 // 直接供应商采购
  HYBRID = 'HYBRID',                               // 混合模式
  VENDOR_INVENTORY_FIRST = 'VENDOR_INVENTORY_FIRST', // 优先供应商库存
  SELF_DIRECT = 'SELF_DIRECT'                      // 自营直充
}

/**
 * 产品状态枚举
 */
export enum ProductStatus {
  ACTIVE = 'ACTIVE',                   // 上架销售中
  INACTIVE = 'INACTIVE',               // 下架
  OUT_OF_STOCK = 'OUT_OF_STOCK',       // 缺货
  DISCONTINUED = 'DISCONTINUED',       // 停售
  ERROR = 'ERROR'                      // 订单程序处理错误
}

/**
 * 限购周期枚举
 */
export enum PurchaseLimitPeriod {
  DAILY = 'DAILY',
  WEEKLY = 'WEEKLY',
  MONTHLY = 'MONTHLY',
  YEARLY = 'YEARLY'
}

/**
 * 产品信息类 - 数据实体
 * 对应数据库表: relinx_product
 * 业务主键: sku + type + issuer_code
 */
export class Product {
  // 数据库主键
  id: number;

  // 产品基本信息
  sku: string;                          // SKU（唯一标识）
  name?: string;                        // 产品名称
  description?: string;                 // 产品描述

  // 产品分类
  category?: string;                    // 产品分类：phone_recharge/gift_card/game_topup等
  type?: ProductType;                   // 交付类型：卡密/直充

  // 发行方信息（运营商/发行商）
  issuerCode?: string;                  // 运营商代码：chunghwa/taiwan_mobile/far_easttone
  issuerName?: string;                  // 运营商名称

  // 地区信息
  region?: string;                      // 地区代码：TW/CN/HK等

  // 面额和价格
  faceValue?: number;                   // 面额
  currency?: FiatCurrency;              // 币种
  sellingPrice?: number;                // 售价
  costPrice?: number;                   // 成本价
  discountPrice?: number;               // 折扣价

  // 库存信息
  stockQuantity: number;                // 当前库存数量（从 inventory 表统计）
  reservedQuantity: number;             // 已预留数量
  soldQuantity: number;                 // 已售出数量

  // 主供应商信息
  primaryVendorId?: number;             // 主供应商ID
  primaryVendorName?: string;           // 主供应商名称
  primaryVendorProductSku?: string;     // 供应商产品ID

  // 备用供应商信息
  secondaryVendorId?: number;           // 备用供应商ID（优先级2）
  secondaryVendorName?: string;         // 备用供应商名称
  secondaryVendorProductSku?: string;   // 备用供应商的产品ID

  // 采购策略
  purchaseStrategy: PurchaseStrategy;   // 采购策略：优先库存/直接供应商/混合

  // 产品状态
  status: ProductStatus;                // 产品状态
  isFeatured: boolean;                  // 是否推荐产品
  isTrial: boolean;                     // 是否为试单产品

  // 显示信息
  displayOrder: number;                 // 显示顺序
  imageUrl?: string;                    // 产品图片URL
  iconEmoji?: string;                   // 图标emoji

  // 限购信息
  maxQuantityPerOrder?: number;         // 单次订单最大购买数量
  maxQuantityPerUser?: number;          // 每用户最大购买数量
  purchaseLimitPeriod: PurchaseLimitPeriod; // 限购周期：daily/weekly/monthly

  // 有效期信息
  validityDays?: number;                // 产品有效期（天）
  expiryWarningDays: number;            // 过期提醒天数

  // 错误信息
  message?: string;                     // 报错信息

  // 时间戳
  createdAt: number;                    // 创建时间（毫秒时间戳）
  updatedAt: number;                    // 更新时间（毫秒时间戳）
  deletedAt?: number;                   // 软删除时间（毫秒时间戳）

  constructor(data: Partial<Product>) {
    this.id = data.id || 0;
    this.sku = data.sku!;
    this.name = data.name;
    this.description = data.description;
    this.category = data.category;
    this.type = data.type;
    this.issuerCode = data.issuerCode;
    this.issuerName = data.issuerName;
    this.region = data.region || 'TW';
    this.faceValue = data.faceValue;
    this.currency = data.currency || FiatCurrency.TWD;
    this.sellingPrice = data.sellingPrice;
    this.costPrice = data.costPrice;
    this.discountPrice = data.discountPrice;
    this.stockQuantity = data.stockQuantity || 0;
    this.reservedQuantity = data.reservedQuantity || 0;
    this.soldQuantity = data.soldQuantity || 0;
    this.primaryVendorId = data.primaryVendorId;
    this.primaryVendorName = data.primaryVendorName;
    this.primaryVendorProductSku = data.primaryVendorProductSku;
    this.secondaryVendorId = data.secondaryVendorId;
    this.secondaryVendorName = data.secondaryVendorName;
    this.secondaryVendorProductSku = data.secondaryVendorProductSku;
    this.purchaseStrategy = data.purchaseStrategy || PurchaseStrategy.SELF_INVENTORY_FIRST;
    this.status = data.status || ProductStatus.ACTIVE;
    this.isFeatured = data.isFeatured !== undefined ? data.isFeatured : false;
    this.isTrial = data.isTrial !== undefined ? data.isTrial : false;
    this.displayOrder = data.displayOrder || 0;
    this.imageUrl = data.imageUrl;
    this.iconEmoji = data.iconEmoji;
    this.maxQuantityPerOrder = data.maxQuantityPerOrder;
    this.maxQuantityPerUser = data.maxQuantityPerUser;
    this.purchaseLimitPeriod = data.purchaseLimitPeriod || PurchaseLimitPeriod.YEARLY;
    this.validityDays = data.validityDays;
    this.expiryWarningDays = data.expiryWarningDays || 7;
    this.message = data.message;
    this.createdAt = data.createdAt || Date.now();
    this.updatedAt = data.updatedAt || Date.now();
    this.deletedAt = data.deletedAt;
  }

  /**
   * 是否为卡密类型
   */
  isGiftCard(): boolean {
    return this.type === ProductType.GIFT_CARD;
  }

  /**
   * 是否为直充类型
   */
  isDirectTopup(): boolean {
    return this.type === ProductType.DIRECT_TOPUP;
  }

  /**
   * 是否上架
   */
  isActive(): boolean {
    return this.status === ProductStatus.ACTIVE && !this.deletedAt;
  }

  /**
   * 是否缺货
   */
  isOutOfStock(): boolean {
    return this.stockQuantity <= 0 || this.status === ProductStatus.OUT_OF_STOCK;
  }

  /**
   * 是否有折扣
   */
  hasDiscount(): boolean {
    return !!this.discountPrice && !!this.sellingPrice && this.discountPrice < this.sellingPrice;
  }

  /**
   * 获取实际售价
   */
  getEffectivePrice(): number {
    if (this.hasDiscount() && this.discountPrice !== undefined) {
      return this.discountPrice;
    }
    return this.sellingPrice || 0;
  }

  /**
   * 获取折扣率（百分比）
   */
  getDiscountRate(): number {
    if (!this.hasDiscount() || !this.discountPrice || !this.sellingPrice) return 0;
    return Math.round(((this.sellingPrice - this.discountPrice) / this.sellingPrice) * 100);
  }

  /**
   * 是否可购买
   */
  isPurchasable(quantity: number = 1): boolean {
    if (!this.isActive()) return false;
    if (this.isOutOfStock()) return false;
    if (this.maxQuantityPerOrder && quantity > this.maxQuantityPerOrder) return false;
    return this.stockQuantity >= quantity;
  }

  /**
   * 获取可用库存（总库存 - 预留库存）
   */
  getAvailableStock(): number {
    return Math.max(0, this.stockQuantity - this.reservedQuantity);
  }

  /**
   * 计算利润
   */
  getProfit(): number {
    if (!this.costPrice) return 0;
    return this.getEffectivePrice() - this.costPrice;
  }

  /**
   * 计算利润率（百分比）
   */
  getProfitMargin(): number {
    if (!this.costPrice || this.costPrice === 0) return 0;
    return ((this.getEffectivePrice() - this.costPrice) / this.costPrice) * 100;
  }

  /**
   * 更新库存数量
   */
  updateStock(quantity: number): void {
    this.stockQuantity = quantity;
    this.updatedAt = Date.now();
  }

  /**
   * 增加库存
   */
  addStock(quantity: number): void {
    this.stockQuantity += quantity;
    this.updatedAt = Date.now();
  }

  /**
   * 减少库存
   */
  reduceStock(quantity: number): void {
    this.stockQuantity = Math.max(0, this.stockQuantity - quantity);
    this.updatedAt = Date.now();
  }

  /**
   * 预留库存
   */
  reserveStock(quantity: number): void {
    this.reservedQuantity += quantity;
    this.updatedAt = Date.now();
  }

  /**
   * 释放预留库存
   */
  releaseReservedStock(quantity: number): void {
    this.reservedQuantity = Math.max(0, this.reservedQuantity - quantity);
    this.updatedAt = Date.now();
  }

  /**
   * 记录销售
   */
  recordSale(quantity: number): void {
    this.soldQuantity += quantity;
    this.reservedQuantity = Math.max(0, this.reservedQuantity - quantity);
    this.stockQuantity = Math.max(0, this.stockQuantity - quantity);
    this.updatedAt = Date.now();
  }

  /**
   * 激活产品
   */
  activate(): void {
    this.status = ProductStatus.ACTIVE;
    this.updatedAt = Date.now();
  }

  /**
   * 停用产品
   */
  deactivate(): void {
    this.status = ProductStatus.INACTIVE;
    this.updatedAt = Date.now();
  }

  /**
   * 标记为缺货
   */
  markOutOfStock(): void {
    this.status = ProductStatus.OUT_OF_STOCK;
    this.updatedAt = Date.now();
  }

  /**
   * 软删除
   */
  softDelete(): void {
    this.deletedAt = Date.now();
    this.status = ProductStatus.DISCONTINUED;
    this.updatedAt = Date.now();
  }

  /**
   * 转换为纯对象（用于存储到 Redis/Database）
   */
  toObject(): Record<string, any> {
    return {
      id: this.id,
      sku: this.sku,
      name: this.name,
      description: this.description,
      category: this.category,
      type: this.type,
      issuerCode: this.issuerCode,
      issuerName: this.issuerName,
      region: this.region,
      faceValue: this.faceValue,
      currency: this.currency,
      sellingPrice: this.sellingPrice,
      costPrice: this.costPrice,
      discountPrice: this.discountPrice,
      stockQuantity: this.stockQuantity,
      reservedQuantity: this.reservedQuantity,
      soldQuantity: this.soldQuantity,
      primaryVendorId: this.primaryVendorId,
      primaryVendorName: this.primaryVendorName,
      primaryVendorProductSku: this.primaryVendorProductSku,
      secondaryVendorId: this.secondaryVendorId,
      secondaryVendorName: this.secondaryVendorName,
      secondaryVendorProductSku: this.secondaryVendorProductSku,
      purchaseStrategy: this.purchaseStrategy,
      status: this.status,
      isFeatured: this.isFeatured,
      isTrial: this.isTrial,
      displayOrder: this.displayOrder,
      imageUrl: this.imageUrl,
      iconEmoji: this.iconEmoji,
      maxQuantityPerOrder: this.maxQuantityPerOrder,
      maxQuantityPerUser: this.maxQuantityPerUser,
      purchaseLimitPeriod: this.purchaseLimitPeriod,
      validityDays: this.validityDays,
      expiryWarningDays: this.expiryWarningDays,
      message: this.message,
      createdAt: this.createdAt,
      updatedAt: this.updatedAt,
      deletedAt: this.deletedAt
    };
  }

  /**
   * 从纯对象创建实例
   */
  static fromObject(obj: any): Product {
    return new Product(obj);
  }
}
