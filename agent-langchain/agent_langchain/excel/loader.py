from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple
import logging
import pandas as pd

from ..config import get_settings
from .df_store import get_df_store
from .schema import ExcelAnalysisRequest


_LOGGER = logging.getLogger("agent_langchain.excel")


def _resolve_file_path(file_id: str) -> str:
    """根据 file_id 解析本地 Excel 文件路径。"""

    settings = get_settings()
    base_dir = getattr(settings, "excel_file_base_dir", "") or ""
    candidates = []

    if base_dir:
        candidates.append(os.path.join(base_dir, file_id))

    if os.path.isabs(file_id):
        candidates.append(file_id)
    else:
        candidates.append(os.path.abspath(file_id))

    for path in candidates:
        if path and os.path.exists(path) and os.path.isfile(path):
            return path

    raise FileNotFoundError(f"Excel 文件不存在或无法访问：file_id={file_id}")


def _select_sheet_name(
    excel_file: pd.ExcelFile,
    requested_sheet: Optional[str],
) -> str:
    """从 Excel 中选择用于分析的 Sheet 名称。"""

    sheet_names = list(excel_file.sheet_names)
    if not sheet_names:
        raise ValueError("Excel 文件中不包含任何 Sheet")

    if requested_sheet:
        if requested_sheet not in sheet_names:
            raise ValueError(f"指定的 Sheet 不存在：{requested_sheet}")
        return requested_sheet

    if len(sheet_names) == 1:
        return sheet_names[0]

    for name in sheet_names:
        try:
            preview_df = excel_file.parse(sheet_name=name, nrows=8)
        except Exception:
            continue
        if preview_df.shape[0] > 0 and preview_df.shape[1] > 0:
            return name

    return sheet_names[0]


def load_excel_for_session(
    request: ExcelAnalysisRequest,
    max_preview_rows: int = 10,
) -> Tuple[str, str, Dict[str, Any]]:
    """加载 Excel/CSV 为 DataFrame，并写入 DataFrameStore。"""

    df_store = get_df_store()
    _LOGGER.info(
        "excel.load_excel_for_session.start session_id=%s file_id=%s sheet_name=%s",
        request.session_id,
        request.file_id,
        request.sheet_name,
    )

    cached_df_id = df_store.get_df_id(
        session_id=request.session_id,
        file_id=request.file_id,
        sheet_name=request.sheet_name,
    )
    if cached_df_id is not None:
        df = df_store.get_df(cached_df_id)
        if df is not None:
            preview_rows = max_preview_rows if max_preview_rows > 0 else 0
            preview_data: Dict[str, Any] = {
                "columns": list(df.columns),
                "rows": df.head(preview_rows).to_dict(orient="records") if preview_rows else [],
            }
            used_sheet_name = request.sheet_name or ""
            _LOGGER.info(
                "excel.load_excel_for_session.cache_hit df_id=%s used_sheet_name=%s columns=%s rows=%d",
                cached_df_id,
                used_sheet_name,
                list(df.columns),
                len(df),
            )
            return cached_df_id, used_sheet_name, preview_data

    file_path = _resolve_file_path(request.file_id)
    lower_path = file_path.lower()

    if lower_path.endswith(".csv") or lower_path.endswith(".txt"):
        _LOGGER.info("excel.load_excel_for_session.read_csv path=%s", file_path)
        df = pd.read_csv(file_path)
        _LOGGER.info(
            "excel.load_excel_for_session.after_read_csv path=%s rows=%d cols=%s",
            file_path,
            len(df),
            list(df.columns),
        )
        used_sheet_name = request.sheet_name or ""
    else:
        _LOGGER.info("excel.load_excel_for_session.read_excel path=%s", file_path)
        excel = pd.ExcelFile(file_path)
        used_sheet_name = _select_sheet_name(excel, request.sheet_name)
        df = pd.read_excel(excel, sheet_name=used_sheet_name)
        _LOGGER.info(
            "excel.load_excel_for_session.after_read_excel path=%s sheet=%s rows=%d cols=%s",
            file_path,
            used_sheet_name,
            len(df),
            list(df.columns),
        )
    _LOGGER.info("excel.load_excel_for_session.before_put_df rows=%d", len(df))
    df_id = df_store.put_df(
        session_id=request.session_id,
        file_id=request.file_id,
        sheet_name=used_sheet_name,
        df=df,
    )
    _LOGGER.info("excel.load_excel_for_session.after_put_df df_id=%s", df_id)

    preview_rows = max_preview_rows if max_preview_rows > 0 else 0
    preview_data: Dict[str, Any] = {
        "columns": list(df.columns),
        "rows": df.head(preview_rows).to_dict(orient="records") if preview_rows else [],
    }

    _LOGGER.info(
        "excel.load_excel_for_session.done df_id=%s used_sheet_name=%s columns=%s rows=%d",
        df_id,
        used_sheet_name,
        list(df.columns),
        len(df),
    )

    return df_id, used_sheet_name, preview_data

