"""
UUID工具类

提供UUID生成、验证、转换等功能。
用于生成job_id、task_id等唯一标识符。
"""

import re
import uuid
from typing import Optional, Union
from datetime import datetime


# UUID格式的正则表达式
UUID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)

# 带前缀的UUID格式
PREFIXED_UUID_PATTERN = re.compile(
    r'^[a-z]+-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)


def generate_uuid() -> str:
    """生成标准的UUID4字符串"""
    return str(uuid.uuid4())


def generate_job_id() -> str:
    """生成Job ID
    
    格式: job-{uuid4}
    示例: job-d8b8a7e0-4f7f-4f7b-8f1e-8e6a1e8e6a1e
    """
    return f"job-{generate_uuid()}"


def generate_task_id() -> str:
    """生成Task ID
    
    格式: task-{uuid4}
    示例: task-e0e1f2f3-4f5f-4f6f-8f7f-8e9a1e8e6a1e
    """
    return f"task-{generate_uuid()}"


def generate_request_id() -> str:
    """生成请求ID
    
    格式: req-{uuid4}
    示例: req-f1f2f3f4-5f6f-4f7f-8f8f-9e0a1e8e6a1e
    """
    return f"req-{generate_uuid()}"


def generate_timestamped_id(prefix: str = "") -> str:
    """生成带时间戳的ID
    
    Args:
        prefix: 前缀字符串
        
    Returns:
        格式: {prefix}-{timestamp}-{short_uuid}
        示例: file-20240627093000-a1b2c3d4
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    short_uuid = generate_uuid()[:8]
    
    if prefix:
        return f"{prefix}-{timestamp}-{short_uuid}"
    else:
        return f"{timestamp}-{short_uuid}"


def is_valid_uuid(uuid_string: str) -> bool:
    """验证UUID格式是否有效
    
    Args:
        uuid_string: 要验证的UUID字符串
        
    Returns:
        bool: 是否为有效的UUID格式
    """
    if not uuid_string or not isinstance(uuid_string, str):
        return False
    
    try:
        # 尝试解析UUID
        uuid.UUID(uuid_string)
        return True
    except ValueError:
        return False


def is_valid_prefixed_uuid(uuid_string: str, expected_prefix: Optional[str] = None) -> bool:
    """验证带前缀的UUID格式
    
    Args:
        uuid_string: 要验证的UUID字符串
        expected_prefix: 期望的前缀，如果为None则只验证格式
        
    Returns:
        bool: 是否为有效的带前缀UUID格式
    """
    if not uuid_string or not isinstance(uuid_string, str):
        return False
    
    # 检查基本格式
    if not PREFIXED_UUID_PATTERN.match(uuid_string):
        return False
    
    # 如果指定了期望的前缀，则检查前缀
    if expected_prefix:
        return uuid_string.startswith(f"{expected_prefix}-")
    
    return True


def is_valid_job_id(job_id: str) -> bool:
    """验证Job ID格式
    
    Args:
        job_id: 要验证的Job ID
        
    Returns:
        bool: 是否为有效的Job ID格式
    """
    return is_valid_prefixed_uuid(job_id, "job")


def is_valid_task_id(task_id: str) -> bool:
    """验证Task ID格式
    
    Args:
        task_id: 要验证的Task ID
        
    Returns:
        bool: 是否为有效的Task ID格式
    """
    return is_valid_prefixed_uuid(task_id, "task")


def is_valid_request_id(request_id: str) -> bool:
    """验证Request ID格式
    
    Args:
        request_id: 要验证的Request ID
        
    Returns:
        bool: 是否为有效的Request ID格式
    """
    return is_valid_prefixed_uuid(request_id, "req")


def extract_uuid_from_prefixed_id(prefixed_id: str) -> Optional[str]:
    """从带前缀的ID中提取UUID部分
    
    Args:
        prefixed_id: 带前缀的ID字符串
        
    Returns:
        Optional[str]: 提取的UUID字符串，如果格式无效则返回None
    """
    if not is_valid_prefixed_uuid(prefixed_id):
        return None
    
    # 查找第一个'-'的位置，然后提取后面的UUID部分
    dash_index = prefixed_id.find('-')
    if dash_index == -1:
        return None
    
    uuid_part = prefixed_id[dash_index + 1:]
    
    # 验证提取的UUID部分
    if is_valid_uuid(uuid_part):
        return uuid_part
    
    return None


def get_prefix_from_prefixed_id(prefixed_id: str) -> Optional[str]:
    """从带前缀的ID中提取前缀部分
    
    Args:
        prefixed_id: 带前缀的ID字符串
        
    Returns:
        Optional[str]: 提取的前缀字符串，如果格式无效则返回None
    """
    if not is_valid_prefixed_uuid(prefixed_id):
        return None
    
    dash_index = prefixed_id.find('-')
    if dash_index == -1:
        return None
    
    return prefixed_id[:dash_index]


def convert_uuid_format(uuid_input: Union[str, uuid.UUID]) -> str:
    """转换UUID格式
    
    Args:
        uuid_input: UUID字符串或UUID对象
        
    Returns:
        str: 标准格式的UUID字符串
        
    Raises:
        ValueError: 如果输入不是有效的UUID
    """
    if isinstance(uuid_input, uuid.UUID):
        return str(uuid_input)
    
    if isinstance(uuid_input, str):
        # 尝试解析UUID
        try:
            uuid_obj = uuid.UUID(uuid_input)
            return str(uuid_obj)
        except ValueError:
            raise ValueError(f"无效的UUID格式: {uuid_input}")
    
    raise ValueError(f"不支持的UUID输入类型: {type(uuid_input)}")


def generate_short_uuid(length: int = 8) -> str:
    """生成短UUID
    
    Args:
        length: 短UUID的长度，默认8位
        
    Returns:
        str: 短UUID字符串
    """
    if length < 1 or length > 32:
        raise ValueError("短UUID长度必须在1-32之间")
    
    full_uuid = generate_uuid().replace('-', '')
    return full_uuid[:length]


def batch_generate_uuids(count: int, prefix: Optional[str] = None) -> list[str]:
    """批量生成UUID
    
    Args:
        count: 要生成的UUID数量
        prefix: 可选的前缀
        
    Returns:
        list[str]: UUID列表
    """
    if count < 1:
        raise ValueError("生成数量必须大于0")
    
    if count > 10000:
        raise ValueError("单次生成数量不能超过10000")
    
    uuids = []
    for _ in range(count):
        if prefix:
            uuids.append(f"{prefix}-{generate_uuid()}")
        else:
            uuids.append(generate_uuid())
    
    return uuids


def uuid_to_bytes(uuid_string: str) -> bytes:
    """将UUID字符串转换为字节
    
    Args:
        uuid_string: UUID字符串
        
    Returns:
        bytes: UUID的字节表示
    """
    try:
        return uuid.UUID(uuid_string).bytes
    except ValueError:
        raise ValueError(f"无效的UUID格式: {uuid_string}")


def bytes_to_uuid(uuid_bytes: bytes) -> str:
    """将字节转换为UUID字符串
    
    Args:
        uuid_bytes: UUID的字节表示
        
    Returns:
        str: UUID字符串
    """
    try:
        return str(uuid.UUID(bytes=uuid_bytes))
    except ValueError:
        raise ValueError("无效的UUID字节数据")


def normalize_uuid(uuid_input: Union[str, uuid.UUID]) -> str:
    """标准化UUID格式
    
    统一转换为小写格式的UUID字符串
    
    Args:
        uuid_input: UUID字符串或UUID对象
        
    Returns:
        str: 标准化的UUID字符串（小写）
    """
    return convert_uuid_format(uuid_input).lower()


# 预定义的UUID生成器函数（用于不同的业务场景）
def generate_file_id() -> str:
    """生成文件ID"""
    return generate_timestamped_id("file")


def generate_session_id() -> str:
    """生成会话ID"""
    return f"session-{generate_uuid()}"


def generate_batch_id() -> str:
    """生成批次ID"""
    return f"batch-{generate_uuid()}"


# 用于验证的便捷函数
def validate_and_extract_uuid(prefixed_id: str, expected_prefix: str) -> str:
    """验证并提取UUID
    
    Args:
        prefixed_id: 带前缀的ID
        expected_prefix: 期望的前缀
        
    Returns:
        str: 提取的UUID
        
    Raises:
        ValueError: 如果格式无效
    """
    if not is_valid_prefixed_uuid(prefixed_id, expected_prefix):
        raise ValueError(f"无效的{expected_prefix} ID格式: {prefixed_id}")
    
    uuid_part = extract_uuid_from_prefixed_id(prefixed_id)
    if not uuid_part:
        raise ValueError(f"无法从{prefixed_id}中提取UUID")
    
    return uuid_part 