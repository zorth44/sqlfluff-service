import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from app.core.database import Base, get_db
from app.web_main import app
import tempfile
import os
import redis
from unittest.mock import patch, MagicMock

# 测试数据库
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="session")
def test_db():
    """创建测试数据库"""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db_session(test_db):
    """数据库会话fixture"""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def client(db_session):
    """测试客户端"""
    def override_get_db():
        try:
            yield db_session
        finally:
            db_session.close()
    
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client

@pytest.fixture
def mock_redis():
    """Mock Redis客户端"""
    with patch('app.celery_app.tasks.redis_client') as mock_redis:
        mock_redis.lock.return_value.__enter__ = MagicMock()
        mock_redis.lock.return_value.__exit__ = MagicMock()
        yield mock_redis

@pytest.fixture
def temp_nfs_dir():
    """临时NFS目录"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # 清理临时目录
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)

@pytest.fixture
def sample_sql_content():
    """示例SQL内容"""
    return """
    SELECT 
        user_id,
        username,
        email
    FROM users 
    WHERE status = 'active'
    ORDER BY created_at DESC;
    """

@pytest.fixture
def sample_zip_file():
    """创建示例ZIP文件"""
    import zipfile
    import tempfile
    
    # 创建临时ZIP文件
    temp_zip = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
    
    with zipfile.ZipFile(temp_zip.name, 'w') as zipf:
        # 添加SQL文件
        sql_content = "SELECT * FROM users;"
        zipf.writestr('query1.sql', sql_content)
        zipf.writestr('query2.sql', "SELECT * FROM orders;")
        zipf.writestr('query3.sql', "SELECT * FROM products;")
    
    yield temp_zip.name
    
    # 清理
    os.unlink(temp_zip.name) 