"""
SQLAlchemy ORM 数据模型
对应数据库核心表结构
"""

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, JSON,
)
from sqlalchemy.orm import relationship

from app.core.database import Base, _is_sqlite

# pgvector 仅在 PostgreSQL 下启用
if not _is_sqlite:
    try:
        from pgvector.sqlalchemy import Vector as _Vector
        _EmbeddingCol = lambda: Column(_Vector(1536), comment="text-embedding-3-small 1536维向量")
    except ImportError:
        _EmbeddingCol = lambda: Column(Text, nullable=True, comment="embedding (pgvector not installed)")
else:
    _EmbeddingCol = lambda: Column(Text, nullable=True, comment="embedding (sqlite fallback)")


class User(Base):
    """用户表 - 存储企业客户信息"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_name = Column(String(255), nullable=False, comment="企业名称")
    contact_email = Column(String(255), unique=True, nullable=False, comment="联系邮箱")
    hashed_password = Column(String(255), nullable=False, comment="加密密码")
    subscription_plan = Column(String(50), default="free", comment="订阅计划: free/basic/pro")
    monthly_budget = Column(Float, default=100.0, comment="月度预算(元)")
    monthly_token_used = Column(Float, default=0.0, comment="本月已用token费用(元)")
    is_active = Column(Boolean, default=True, comment="是否激活")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    tasks = relationship("MonitoringTask", back_populates="user", cascade="all, delete-orphan")
    reports = relationship("Report", back_populates="user", cascade="all, delete-orphan")
    documents = relationship("RAGDocument", back_populates="user", cascade="all, delete-orphan")


class MonitoringTask(Base):
    """监测任务表 - 定义用户的监测需求"""
    __tablename__ = "monitoring_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    brand_name = Column(String(255), nullable=False, comment="品牌名称")
    platform = Column(String(100), nullable=False, comment="平台名称，用户自由输入")
    task_type = Column(String(50), nullable=False, comment="任务类型，用户自由输入")
    frequency = Column(String(20), default="daily", comment="频率: hourly/daily/weekly")
    status = Column(String(20), default="active", comment="状态: active/paused/stopped")
    keywords = Column(JSON, default=list, comment="搜索关键词列表")
    product_url = Column(String(500), nullable=True, comment="指定商品链接")
    last_run_at = Column(DateTime, nullable=True, comment="上次执行时间")
    next_run_at = Column(DateTime, nullable=True, comment="下次执行时间")
    config = Column(JSON, default=dict, comment="任务配置(JSON)")
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关联
    user = relationship("User", back_populates="tasks")
    results = relationship("MonitoringResult", back_populates="task", cascade="all, delete-orphan")


class MonitoringResult(Base):
    """监测结果表 - 存储每次抓取的数据"""
    __tablename__ = "monitoring_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("monitoring_tasks.id"), nullable=False)
    data = Column(JSON, default=dict, comment="抓取的原始数据")
    change_detected = Column(Boolean, default=False, comment="是否检测到变化")
    change_type = Column(String(50), nullable=True, comment="变化类型: price_up/price_down/new_product/sentiment_spike")
    change_summary = Column(Text, nullable=True, comment="变化摘要")
    severity = Column(String(20), default="info", comment="严重程度: info/warning/critical")
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关联
    task = relationship("MonitoringTask", back_populates="results")


class Report(Base):
    """报告表 - 存储生成的分析报告"""
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    report_type = Column(String(50), nullable=False, comment="报告类型: daily/weekly/custom")
    title = Column(String(255), nullable=False, comment="报告标题")
    content = Column(Text, nullable=False, comment="报告内容(Markdown)")
    model_used = Column(String(50), comment="使用的LLM模型")
    token_cost = Column(Float, default=0.0, comment="Token消耗费用(元)")
    generated_at = Column(DateTime, default=datetime.utcnow)

    # 关联
    user = relationship("User", back_populates="reports")


class RAGDocument(Base):
    """RAG知识库表 - 使用 pgvector 存储向量"""
    __tablename__ = "rag_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    doc_type = Column(String(50), nullable=False, comment="文档类型: report/sop/persona/industry_data")
    title = Column(String(255), nullable=False, comment="文档标题")
    content = Column(Text, nullable=False, comment="文档内容")
    embedding = _EmbeddingCol()
    metadata_ = Column("metadata", JSON, default=dict, comment="元信息")
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关联
    user = relationship("User", back_populates="documents")


class TokenUsageLog(Base):
    """Token 消耗日志 - 记录每次 LLM 调用"""
    __tablename__ = "token_usage_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    model = Column(String(50), nullable=False, comment="模型名称")
    prompt_tokens = Column(Integer, default=0, comment="输入Token数")
    completion_tokens = Column(Integer, default=0, comment="输出Token数")
    cost_cny = Column(Float, default=0.0, comment="本次费用(元)")
    task_type = Column(String(50), comment="任务类型: format/report/analysis/persona")
    created_at = Column(DateTime, default=datetime.utcnow)


class UserProduct(Base):
    """用户产品表 - 竞品自动发现的起点"""
    __tablename__ = "user_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_name = Column(String(255), nullable=False, comment="产品名称")
    industry = Column(String(100), nullable=False, comment="所属行业")
    category = Column(String(100), nullable=False, comment="细分品类")
    keywords = Column(JSON, default=list, comment="搜索关键词列表")
    price_range = Column(JSON, default=dict, comment="目标价格带 {min, max}")
    platforms = Column(JSON, default=list, comment="监测平台列表")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    discoveries = relationship("CompetitorDiscovery", back_populates="user_product", cascade="all, delete-orphan")
    competitors = relationship("CompetitorProduct", back_populates="user_product", cascade="all, delete-orphan")
    scan_jobs = relationship("ScanJob", back_populates="product", cascade="all, delete-orphan")


class CompetitorDiscovery(Base):
    """竞品发现记录 - Agent 自动搜索的候选竞品"""
    __tablename__ = "competitor_discoveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_product_id = Column(Integer, ForeignKey("user_products.id"), nullable=False)
    brand = Column(String(100), nullable=False, comment="品牌名")
    product_name = Column(String(255), nullable=False, comment="产品名")
    platform = Column(String(50), comment="发现来源平台")
    price = Column(Float, nullable=True, comment="发现时价格")
    monthly_sales = Column(Integer, nullable=True, comment="月销量估算")
    product_url = Column(String(500), nullable=True, comment="商品链接")
    discovery_reason = Column(String(500), comment="推荐理由")
    relevance_score = Column(Float, default=0.0, comment="竞争相关度 0-1")
    status = Column(String(20), default="pending", comment="pending/confirmed/rejected")
    discovered_at = Column(DateTime, default=datetime.utcnow)

    # 关联
    user_product = relationship("UserProduct", back_populates="discoveries")


class CompetitorProduct(Base):
    """竞品产品表 - 已确认的竞品，持续监测"""
    __tablename__ = "competitor_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_product_id = Column(Integer, ForeignKey("user_products.id"), nullable=False)
    discovery_id = Column(Integer, ForeignKey("competitor_discoveries.id"), nullable=True)
    brand = Column(String(100), nullable=False, comment="品牌名")
    product_name = Column(String(255), nullable=False, comment="产品名")
    platform = Column(String(50), comment="平台")
    price = Column(Float, nullable=True, comment="当前价格")
    promo_price = Column(Float, nullable=True, comment="促销价")
    specs = Column(JSON, default=dict, comment="规格参数")
    features = Column(JSON, default=list, comment="功能特点")
    product_url = Column(String(500), nullable=True, comment="商品链接")
    last_checked = Column(DateTime, nullable=True, comment="上次检查时间")
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关联
    user_product = relationship("UserProduct", back_populates="competitors")
