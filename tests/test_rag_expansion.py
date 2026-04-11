"""tests/test_rag_expansion.py — RAG 查询扩展测试"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.knowledge_base import _expand_query_synonyms


def test_expand_fed():
    result = _expand_query_synonyms("美联储降息对A股影响")
    assert "Federal" in result or "Fed" in result


def test_expand_pe():
    result = _expand_query_synonyms("市盈率估值分析")
    assert "PE" in result


def test_expand_roe():
    result = _expand_query_synonyms("净资产收益率排名")
    assert "ROE" in result


def test_no_expansion():
    original = "今天天气很好"
    result = _expand_query_synonyms(original)
    assert result == original


def test_multiple_terms():
    result = _expand_query_synonyms("美联储降息影响市盈率变化")
    assert "Fed" in result or "Federal" in result
    assert "PE" in result


def test_max_synonyms():
    result = _expand_query_synonyms("美联储")
    # Should only add first 3 synonyms, not all
    words = result.split()
    # Original "美联储" + max 3 synonyms
    assert len(words) <= 5
