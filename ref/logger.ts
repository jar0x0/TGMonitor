import log4js from 'log4js';
import path from 'path';
import { fileURLToPath } from 'url';

// 获取环境变量
const env = process.env.NODE_ENV || 'development';
const isProduction = env === 'production';
const logLevel = process.env.LOG_LEVEL || (isProduction ? 'info' : 'debug');

// 日志文件目录 - 使用项目根目录的 logs 文件夹
const logDir = path.join(process.cwd(), 'logs');

// Log4js 配置
log4js.configure({
    appenders: {
        // 控制台输出（开发环境）
        console: {
            type: 'console',
            layout: {
                type: 'pattern',
                pattern: '%[[%d{yyyy-MM-dd hh:mm:ss.SSS}] [%p] [%c]%] %m'
            }
        },

        // Bot 日志文件
        file: {
            type: 'file',
            filename: path.join(logDir, 'app.log'),
            maxLogSize: 10485760, // 10MB
            backups: 5,
            compress: true,
            layout: {
                type: 'pattern',
                pattern: '%d{yyyy-MM-dd hh:mm:ss.SSS} [%p] [%c] %m'
            }
        },

        // API 日志文件
        apiFile: {
            type: 'file',
            filename: path.join(logDir, 'api.log'),
            maxLogSize: 10485760, // 10MB
            backups: 5,
            compress: true,
            layout: {
                type: 'pattern',
                pattern: '%d{yyyy-MM-dd hh:mm:ss.SSS} [%p] [%c] %m'
            }
        },

        // Bot 错误日志文件
        errors: {
            type: 'file',
            filename: path.join(logDir, 'errors.log'),
            maxLogSize: 10485760, // 10MB
            backups: 5,
            compress: true
        },

        // API 错误日志文件
        apiErrors: {
            type: 'file',
            filename: path.join(logDir, 'api_errors.log'),
            maxLogSize: 10485760, // 10MB
            backups: 5,
            compress: true
        },

        // Bot 错误过滤
        errorFilter: {
            type: 'logLevelFilter',
            appender: 'errors',
            level: 'error'
        },

        // API 错误过滤
        apiErrorFilter: {
            type: 'logLevelFilter',
            appender: 'apiErrors',
            level: 'error'
        },

        // 按类别过滤
        httpAppender: {
            type: 'logLevelFilter',
            appender: 'file',
            level: 'info'
        }
    },

    categories: {
        default: {
            appenders: isProduction ? ['file', 'errorFilter'] : ['console', 'file', 'errorFilter'],
            level: logLevel
        },

        // API 日志（输出到 api.log 和 api_errors.log）
        api: {
            appenders: isProduction ? ['apiFile', 'apiErrorFilter'] : ['console', 'apiFile', 'apiErrorFilter'],
            level: logLevel
        },

        // HTTP 请求日志
        http: {
            appenders: ['httpAppender'],
            level: 'info'
        },

        // 数据库日志
        database: {
            appenders: isProduction ? ['file'] : ['console', 'file'],
            level: 'info'
        },

        // 安全日志
        security: {
            appenders: isProduction ? ['file', 'errorFilter'] : ['console', 'file', 'errorFilter'],
            level: 'warn'
        }
    }
});

// 创建日志记录器
export const logger = log4js.getLogger();
export const apiLogger = log4js.getLogger('api');
export const httpLogger = log4js.getLogger('http');
export const dbLogger = log4js.getLogger('database');
export const securityLogger = log4js.getLogger('security');

// 添加请求日志中间件
export function requestLoggerMiddleware(req: any, res: any, next: any) {
    const start = Date.now();

    res.on('finish', () => {
        const duration = Date.now() - start;
        const logData = {
            method: req.method,
            url: req.originalUrl,
            status: res.statusCode,
            duration: `${duration}ms`,
            ip: req.ip,
            userAgent: req.get('user-agent')
        };

        if (res.statusCode >= 400) {
            httpLogger.error(logData);
        } else {
            httpLogger.info(logData);
        }
    });

    next();
}

// 错误处理中间件
export function errorHandlerMiddleware(err: any, req: any, res: any, next: any) {
    logger.error({
        message: err.message,
        stack: err.stack,
        url: req.originalUrl,
        method: req.method,
        ip: req.ip
    });

    res.status(err.status || 500).json({
        error: isProduction ? 'Internal Server Error' : err.message
    });
}

// 关闭日志记录器（用于优雅关闭）
export function shutdownLogger() {
    return new Promise<void>((resolve) => {
        log4js.shutdown(() => {
            console.log('Logger has been shutdown');
            resolve();
        });
    });
}