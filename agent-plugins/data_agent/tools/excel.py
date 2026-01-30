from __future__ import annotations
import logging
import json
from typing import Optional
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from data_agent.utils.artifacts import store_dataframe

_LOGGER = logging.getLogger("agent_langchain.tools.excel")


@tool("data_excel_load")
def excel_load_tool(
    file_path: Optional[str] = None,
    file_id: Optional[str] = None,
    sheet_name: Optional[str] = None,
    analysis_id: Optional[str] = None,
    config: RunnableConfig = None,
) -> str:
    """加载 Excel 文件到工作区供分析。
    
    Args:
        file_path: Excel 文件路径
        sheet_name: 工作表名称
        analysis_id: 分析任务 ID
    """
    resolved_path = (file_path or file_id or "").strip()
    if not resolved_path:
        raise ValueError("文件路径不能为空。")

    _LOGGER.info("excel_load: file=%s sheet=%s analysis_id=%s", resolved_path, sheet_name, analysis_id)

    try:
        import pandas as pd
        if resolved_path.lower().endswith(".csv"):
            df = pd.read_csv(resolved_path)
            sheet_name = None
        else:
            if sheet_name:
                df = pd.read_excel(resolved_path, sheet_name=sheet_name)
            else:
                df = pd.read_excel(resolved_path)

        df_name = "excel_data"
        
        # 存储到工作区
        if analysis_id:
            user_id = "anonymous"
            session_id = "default"
            task_id = None
            if config:
                configurable = config.get("configurable", {})
                user_id = configurable.get("user_id", "anonymous")
                session_id = configurable.get("session_id", "default")
                task_id = configurable.get("task_id") or None

            store_dataframe(
                df_name,
                df,
                analysis_id,
                user_id=user_id,
                session_id=session_id,
                task_id=task_id,
            )

        preview_rows = df.head(10).to_dict(orient="records")
        
        return json.dumps({
            "file_path": resolved_path,
            "sheet_name": sheet_name or ("CSV" if resolved_path.lower().endswith(".csv") else "Sheet1"),
            "shape": {"rows": len(df), "columns": len(df.columns)},
            "columns": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "preview": preview_rows,
            "df_name": df_name,
            "note": f"数据已加载为 '{df_name}' DataFrame，可用 python_execute 进一步分析。"
        }, default=str, ensure_ascii=False)
    except FileNotFoundError:
        raise ValueError(f"文件不存在：{resolved_path}")
    except Exception as e:
        raise RuntimeError(f"加载 Excel 失败：{e}")


@tool("data_excel_list_sheets")
def excel_list_sheets_tool(file_path: Optional[str] = None, file_id: Optional[str] = None) -> str:
    """列出 Excel 文件中的所有工作表。"""
    resolved_path = (file_path or file_id or "").strip()
    if not resolved_path:
        raise ValueError("文件路径不能为空。")

    if resolved_path.lower().endswith(".csv"):
        return json.dumps({"file_path": resolved_path, "sheets": [], "note": "CSV 文件不包含工作表"}, ensure_ascii=False)

    try:
        import pandas as pd
        xl = pd.ExcelFile(resolved_path)
        sheets = xl.sheet_names
        _LOGGER.info("excel_list_sheets file=%s sheets=%s", resolved_path, sheets)
        return json.dumps({"file_path": resolved_path, "sheets": sheets}, ensure_ascii=False)
    except Exception as e:
        raise RuntimeError(f"读取 Excel 工作表失败：{e}")
