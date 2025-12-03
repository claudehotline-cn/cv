from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple
import logging
import pandas as pd

from ..config import get_settings
from .df_store import get_df_store
from .schema import ExcelAnalysisRequest


_LOGGER = logging.getLogger("cv_agent.excel")


def _resolve_file_path(file_id: str) -> str:
    """根据 file_id 解析本地 Excel 文件路径。

    当前实现遵循以下策略（可根据实际文件服务调整）：
    1. 若环境变量/配置 `excel_file_base_dir` 非空，则优先在该目录下查找；
    2. 若 file_id 本身是绝对路径且存在，直接使用；
    3. 若当前工作目录下存在同名文件，也允许使用。
    """

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
    """从 Excel 中选择用于分析的 Sheet 名称。

    - 若指定了 sheet_name 且存在，则直接使用；
    - 若仅有一个 sheet，则使用该 sheet；
    - 否则依次尝试按行列数过滤空表，返回第一个非空表；
    - 若所有 sheet 均为空，则回退到第一个表。
    """

    sheet_names = list(excel_file.sheet_names)
    if not sheet_names:
        raise ValueError("Excel 文件中不包含任何 Sheet")

    if requested_sheet:
        if requested_sheet not in sheet_names:
            raise ValueError(f"指定的 Sheet 不存在：{requested_sheet}")
        return requested_sheet

    if len(sheet_names) == 1:
        return sheet_names[0]

    # 多 Sheet 场景：简单按“是否为空表”过滤
    for name in sheet_names:
        try:
            preview_df = excel_file.parse(sheet_name=name, nrows=8)
        except Exception:
            continue
        if preview_df.shape[0] > 0 and preview_df.shape[1] > 0:
            return name

    # 所有 Sheet 看起来都为空时，回退到第一个
    return sheet_names[0]


def load_excel_for_session(
    request: ExcelAnalysisRequest,
    max_preview_rows: int = 10,
) -> Tuple[str, str, Dict[str, Any]]:
    """加载 Excel/CSV 为 DataFrame，并写入 DataFrameStore。

    返回值：
    - df_id: DataFrame 在缓存中的标识；
    - used_sheet_name: 实际使用的 Sheet 名称；
    - table_preview: 列名与前几行数据预览，用于后续 LLM 生成 ChartSpec。
    """

    df_store = get_df_store()
    _LOGGER.info(
        "excel.load_excel_for_session.start session_id=%s file_id=%s sheet_name=%s",
        request.session_id,
        request.file_id,
        request.sheet_name,
    )

    # 若缓存中已存在相同 (session_id, file_id, sheet_name) 的 DataFrame，则直接复用。
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

    # 缓存未命中：从文件系统加载
    file_path = _resolve_file_path(request.file_id)
    lower_path = file_path.lower()

    if lower_path.endswith(".csv") or lower_path.endswith(".txt"):
        # 对于 CSV/TXT，直接按表格读取，不涉及 Sheet 概念。
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
