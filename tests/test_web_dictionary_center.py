from src.app.workbench_frontend import render_workbench_html


def test_workbench_dictionary_center_exposes_alias_resolution_workflow():
    html = render_workbench_html()

    assert "金融词典" in html
    assert 'id="createDictionaryTerm"' in html
    assert "解析测试" in html
    assert 'id="dictionaryResolveQuery"' in html
    assert 'id="testDictionaryResolve"' in html
    assert "/api/dictionary/resolve?" in html
    assert "命中别名" in html
    assert "data-dictionary-create" in html
    assert "词典记录本身不替代证据" in html
