"""Fix smart quotes in _confirmation_prompt function."""
with open("src/app/web_ui.py", encoding="utf-8") as f:
    source = f.read()

start_marker = "def _confirmation_prompt(symbol: str, period: str, engines: List[str], mode: str = "

# Find all smart quote positions
smart_left = chr(0x201c)
smart_right = chr(0x201d)

# Find the function range by looking for "def _confirmation_prompt"
start_idx = source.find(start_marker)
if start_idx == -1:
    # Try with smart quotes
    smart_start = "def _confirmation_prompt(symbol: str, period: str, engines: List[str], mode: str = " + smart_left
    start_idx = source.find(smart_start)
    if start_idx == -1:
        print("ERROR: cannot find function start")
        exit(1)

# Find the end: look for the next function definition or the end of this one
# The function body ends before the next blank-line-separated function or EOF
search_from = start_idx + len("def _confirmation_prompt")
# Find end of this function: next "def " at column 0 that's not inside a string
# Simpler: find the closing paren of the user-mode return statement
# Look for pattern: after "数据来源：公司公开披露、SEC 文件、行情数据和公开资料"
# The last line of user-mode return has: "数据来源：...")\n
# Actually simpler: just find all smart quotes and replace them in the file

count = source.count(smart_left) + source.count(smart_right)
if count > 0:
    source = source.replace(smart_left, '"').replace(smart_right, '"')
    with open("src/app/web_ui.py", "w", encoding="utf-8") as f:
        f.write(source)
    print(f"Fixed {count} smart quotes globally")
else:
    print("No smart quotes found")

# Verify
import ast
try:
    ast.parse(source)
    print("SYNTAX OK")
except SyntaxError as e:
    lines = source.split("\n")
    for lineno in range(max(0, e.lineno - 3), min(len(lines), e.lineno + 2)):
        marker = ">>>" if lineno + 1 == e.lineno else "   "
        print(f"{marker} {lineno+1}: {repr(lines[lineno])}")
    print(f"Error: {e}")
