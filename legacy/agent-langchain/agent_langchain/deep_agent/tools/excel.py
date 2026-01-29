from __future__ import annotations
import logging
import json
from typing import Any, Dict, Optional
from langchain_core.tools import tool

from ...utils.dataframe_store import store_dataframe

_LOGGER = logging.getLogger("agent_langchain.tools.excel")


@tool("data_excel_load")
def excel_load_tool(
    file_path: str, 
    sheet_name: Optional[str] = None,
    analysis_id: Optional[str] = None
) -> str:
    """加载 Excel 文件到工作区供分析。
    
    Args:
        file_path: Excel 文件路径
        sheet_name: 工作表名称
        analysis_id: 分析任务 ID
    """
    if not file_path or not file_path.strip():
        raise ValueError("文件路径不能为空。")

    _LOGGER.info("excel_load: file=%s sheet=%s analysis_id=%s", file_path, sheet_name, analysis_id)

    try:
        import pandas as pd
        if sheet_name:
            df = pd.read_excel(file_path, sheet_name=sheet_name)
        else:
            df = pd.read_excel(file_path)

        df_name = "excel_data"
        
        # 存储到工作区
        if analysis_id:
            store_dataframe(df_name, df, analysis_id)

        preview_rows = df.head(10).to_dict(orient="records")
        
        return json.dumps({
            "file_path": file_path,
            "sheet_name": sheet_name or "Sheet1",
            "shape": {"rows": len(df), "columns": len(df.columns)},
            "columns": list(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "preview": preview_rows,
            "df_name": df_name,
            "note": f"数据已加载为 '{df_name}' DataFrame，可用 python_execute 进一步分析。"
        }, default=str, ensure_ascii=False)
    except FileNotFoundError:
        raise ValueError(f"文件不存在：{file_path}")
    except Exception as e:
        raise RuntimeError(f"加载 Excel 失败：{e}")


@tool("data_excel_list_sheets")
def excel_list_sheets_tool(file_path: str) -> Dict[str, Any]:
    """列出 Excel 文件中的所有工作表。"""
    if not file_path or not file_path.strip():
        raise ValueError("文件路径不能为空。")

    try:
        import pandas as pd
        xl = pd.ExcelFile(file_path)
        sheets = xl.sheet_names
        _LOGGER.info("excel_list_sheets file=%s sheets=%s", file_path, sheets)
        return {"file_path": file_path, "sheets": sheets}
    except Exception as e:
        raise RuntimeError(f"读取 Excel 工作表失败：{e}")
