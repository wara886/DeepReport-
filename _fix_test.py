"""Fix test file - second body block gets async_report_run"""
path = r'g:\cord\DeepReport_plus\tests\test_web_ui_confirmation_queue.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old_body_start = '"session_id": "local",\n            "memory_enabled": False,\n            "allow_report_run": True,\n            "enable_remote_data": False,'
new_body_start = '"session_id": "dev_session",\n            "memory_enabled": False,\n            "allow_report_run": True,\n            "enable_remote_data": False,\n            "async_report_run": True,'

# Find first occurrence
idx = content.find(old_body_start)
if idx >= 0:
    idx2 = content.find(old_body_start, idx + len(old_body_start))
    if idx2 >= 0:
        content = content[:idx2] + new_body_start + content[idx2 + len(old_body_start):]

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed second occurrence')
