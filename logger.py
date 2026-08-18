"""
日誌配置模塊
"""
import logging
import sys
from config import LOG_FILE

def setup_logger(name="market_maker"):
    """
    設置並返回一個配置好的logger實例
    """
    logger = logging.getLogger(name)
    
    # 防止重複配置
    if logger.handlers:
        return logger
        
    logger.setLevel(logging.INFO)
    # Each project logger owns its handlers.  Prevent messages from being
    # emitted a second time when another library configures the root logger.
    logger.propagate = False
    
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # 文件處理器
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setFormatter(formatter)
    
    # 控制台處理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    # 添加處理器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger
