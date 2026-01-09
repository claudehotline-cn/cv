"""工作区 DataFrame 存储工具

提供基于文件的 DataFrame 存储，用于跨 SubAgent 共享数据。
使用 Parquet 格式以获得更好的压缩和读写性能。
"""
import logging
import os
from typing import Optional, List
import pandas as pd

_LOGGER = logging.getLogger("agent_langchain.utils.dataframe_store")

WORKSPACE_ROOT = os.environ.get("DATA_WORKSPACE_ROOT", "/data/workspace")


def _get_dataframe_dir(analysis_id: str) -> str:
    """获取 DataFrame 存储目录"""
    return os.path.join(WORKSPACE_ROOT, "artifacts", f"data_analysis_{analysis_id}", "dataframes")


def store_dataframe(name: str, df: pd.DataFrame, analysis_id: str) -> str:
    """存储 DataFrame 到 Parquet 文件
    
    Args:
        name: DataFrame 名称 (如 'sql_result', 'result')
        df: 要存储的 DataFrame
        analysis_id: 分析任务 ID
        
    Returns:
        存储的文件路径
    """
    if not analysis_id:
        _LOGGER.error("store_dataframe called without analysis_id, persistence failed!")
        return ""
        
    dir_path = _get_dataframe_dir(analysis_id)
    os.makedirs(dir_path, exist_ok=True)
    
    filepath = os.path.join(dir_path, f"{name}.parquet")
    df.to_parquet(filepath, index=False)
    _LOGGER.info("Stored DataFrame '%s': shape=%s -> %s", name, df.shape, filepath)
    return filepath


def get_dataframe(name: str, analysis_id: str) -> Optional[pd.DataFrame]:
    """从工作区加载 DataFrame
    
    Args:
        name: DataFrame 名称
        analysis_id: 分析任务 ID
        
    Returns:
        加载的 DataFrame，如果不存在返回 None
    """
    if not analysis_id:
        _LOGGER.warning("get_dataframe called without analysis_id")
        return None
        
    filepath = os.path.join(_get_dataframe_dir(analysis_id), f"{name}.parquet")
    if not os.path.exists(filepath):
        _LOGGER.debug("DataFrame '%s' not found at %s", name, filepath)
        return None
        
    df = pd.read_parquet(filepath)
    _LOGGER.info("Loaded DataFrame '%s': shape=%s", name, df.shape)
    return df


def list_dataframes(analysis_id: str) -> List[str]:
    """列出当前分析任务的所有 DataFrame
    
    Returns:
        DataFrame 名称列表
    """
    if not analysis_id:
        return []
        
    dir_path = _get_dataframe_dir(analysis_id)
    if not os.path.exists(dir_path):
        return []
        
    return [f.replace(".parquet", "") for f in os.listdir(dir_path) if f.endswith(".parquet")]


def get_all_dataframes(analysis_id: str) -> dict[str, pd.DataFrame]:
    """加载当前分析任务的所有 DataFrame
    
    Returns:
        名称 -> DataFrame 的字典
    """
    result = {}
    for name in list_dataframes(analysis_id):
        df = get_dataframe(name, analysis_id)
        if df is not None:
            result[name] = df
    return result


def clear_dataframes(analysis_id: str) -> None:
    """清空指定分析任务的所有 DataFrame 文件"""
    if not analysis_id:
        return
        
    dir_path = _get_dataframe_dir(analysis_id)
    if os.path.exists(dir_path):
        import shutil
        shutil.rmtree(dir_path)
        _LOGGER.info("Cleared all DataFrames for analysis_id=%s", analysis_id)
