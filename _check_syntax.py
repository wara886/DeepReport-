import ast
with open("src/app/web_ui.py", encoding="utf-8") as f:
    source = f.read()
try:
    ast.parse(source)
    print("SYNTAX OK")
except SyntaxError as e:
    # Show the problematic line with context
    lines = source.split("\n")
    for lineno in range(max(0, e.lineno - 3), min(len(lines), e.lineno + 2)):
        marker = ">>>" if lineno + 1 == e.lineno else "   "
        print(f"{marker} {lineno+1}: {lines[lineno]}")
    print(f"Error: {e}")
