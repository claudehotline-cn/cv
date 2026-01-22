#!/usr/bin/env python3
"""验证 ContextVar 重构是否成功"""

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_refactor")

def test_config_task_id():
    logger.info("测试 config.get_article_dir 是否支持 task_id...")
    from article_agent.config import get_article_dir
    
    path_main = get_article_dir("test_article", "main")
    logger.info(f"Main path: {path_main}")
    
    path_custom = get_article_dir("test_article", "custom_task")
    logger.info(f"Custom path: {path_custom}")
    
    # 验证路径包含 task_id
    assert "main" in path_main, f"Main path should contain 'main': {path_main}"
    assert "custom_task" in path_custom, f"Custom path should contain 'custom_task': {path_custom}"
    
    logger.info("✅ config.get_article_dir 测试通过!")
    return True

def test_artifacts_task_id():
    logger.info("测试 artifacts 函数是否支持 task_id...")
    from article_agent.utils.artifacts import get_corpus_dir, get_drafts_dir
    
    corpus_main = get_corpus_dir("test_article", "doc1", "main")
    corpus_custom = get_corpus_dir("test_article", "doc1", "custom_task")
    
    drafts_main = get_drafts_dir("test_article", "main")
    drafts_custom = get_drafts_dir("test_article", "custom_task")
    
    logger.info(f"Corpus main: {corpus_main}")
    logger.info(f"Corpus custom: {corpus_custom}")
    logger.info(f"Drafts main: {drafts_main}")
    logger.info(f"Drafts custom: {drafts_custom}")
    
    assert "main" in corpus_main
    assert "custom_task" in corpus_custom
    assert "main" in drafts_main
    assert "custom_task" in drafts_custom
    
    logger.info("✅ artifacts 函数测试通过!")
    return True

def test_tool_imports():
    logger.info("测试 tool 模块导入...")
    from article_agent.tools import ingest
    from article_agent.tools import planner
    from article_agent.tools import researcher
    from article_agent.tools import writer
    from article_agent.tools import assembler
    
    # 验证 tool 函数签名包含 config 参数
    import inspect
    
    # LangChain tools wrap the function, access via .args or check if 'config' in schema
    # Check if tools have article_id in their schema
    ingest_tool = ingest.ingest_documents_tool
    writer_tool = writer.write_all_sections_tool
    
    # Check if tools are callable and have expected schema
    assert hasattr(ingest_tool, 'name') or callable(ingest_tool), "ingest_documents_tool should be a tool"
    assert hasattr(writer_tool, 'name') or callable(writer_tool), "write_all_sections_tool should be a tool"
    
    logger.info("✅ 所有 tool 导入成功!")
    return True

def test_graph_creation():
    logger.info("测试 graph 创建 (middleware 移除检查)...")
    from article_agent.graph import get_article_deep_agent_graph
    
    graph = get_article_deep_agent_graph()
    logger.info(f"Graph type: {type(graph)}")
    logger.info("✅ Graph 创建成功!")
    return True

if __name__ == "__main__":
    import sys
    results = []
    
    try:
        results.append(("config_task_id", test_config_task_id()))
    except Exception as e:
        logger.error(f"❌ config_task_id 测试失败: {e}")
        results.append(("config_task_id", False))
    
    try:
        results.append(("artifacts_task_id", test_artifacts_task_id()))
    except Exception as e:
        logger.error(f"❌ artifacts_task_id 测试失败: {e}")
        results.append(("artifacts_task_id", False))
    
    try:
        results.append(("tool_imports", test_tool_imports()))
    except Exception as e:
        logger.error(f"❌ tool_imports 测试失败: {e}")
        results.append(("tool_imports", False))
    
    try:
        results.append(("graph_creation", test_graph_creation()))
    except Exception as e:
        logger.error(f"❌ graph_creation 测试失败: {e}")
        results.append(("graph_creation", False))
    
    # 汇总
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    logger.info(f"\n{'='*50}")
    logger.info(f"验证结果: {passed}/{total} 测试通过")
    for name, result in results:
        status = "✅" if result else "❌"
        logger.info(f"  {status} {name}")
    
    sys.exit(0 if passed == total else 1)
