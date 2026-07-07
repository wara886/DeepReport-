import subprocess

from src.app.workbench_frontend import render_workbench_html


def test_workbench_inline_script_is_valid_javascript(tmp_path):
    html = render_workbench_html()
    start = html.index("<script>") + len("<script>")
    end = html.index("</script>", start)
    script_path = tmp_path / "workbench.js"
    script_path.write_text(html[start:end], encoding="utf-8")

    result = subprocess.run(["node", "--check", str(script_path)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
