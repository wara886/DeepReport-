"""Fix test mode assertions for new routing."""
with open("tests/test_web_ui.py", "r", encoding="utf-8") as f:
    source = f.read()

source = source.replace('body["mode"] == "chat"', 'body["mode"] == "general_chat"')
source = source.replace('second_body["mode"] == "report_run"', 'second_body["mode"] == "report_generation_completed"')
source = source.replace('body["mode"] == "report_run"', 'body["mode"] == "report_generation_completed"')

with open("tests/test_web_ui.py", "w", encoding="utf-8") as f:
    f.write(source)
print("Done")
