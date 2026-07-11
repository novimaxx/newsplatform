import json
from config import CHANNELS_FILE

with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
    channels = json.load(f)

channels.sort(key=lambda c: (c.get("title") or "").lower())

rows = ""
for i, c in enumerate(channels, 1):
    title    = c.get("title") or ""
    cid      = c.get("id", "")
    username = c.get("username") or ""
    link     = f'<a href="https://t.me/{username}" target="_blank">@{username}</a>' if username else "—"
    rows += f"<tr><td>{i}</td><td>{title}</td><td>{link}</td><td>{cid}</td></tr>\n"

html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Каналы ({len(channels)})</title>
<style>
  body {{ font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5; }}
  h2 {{ color: #333; }}
  input {{ width: 100%; padding: 10px; font-size: 16px; margin-bottom: 16px;
           border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; }}
  table {{ width: 100%; border-collapse: collapse; background: white;
           border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  th {{ background: #2c3e50; color: white; padding: 12px; text-align: left; cursor: pointer; }}
  th:hover {{ background: #3d5166; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #eee; }}
  tr:hover td {{ background: #f0f7ff; }}
  a {{ color: #2980b9; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .count {{ color: #888; font-size: 14px; margin-bottom: 8px; }}
</style>
</head>
<body>
<h2>📡 Список каналов</h2>
<p class="count">Всего: <b>{len(channels)}</b></p>
<input type="text" id="search" placeholder="🔍 Поиск по названию или @username..." onkeyup="filterTable()">
<table id="table">
  <thead>
    <tr>
      <th onclick="sortTable(0)">#</th>
      <th onclick="sortTable(1)">Название ↕</th>
      <th onclick="sortTable(2)">Username</th>
      <th onclick="sortTable(3)">ID</th>
    </tr>
  </thead>
  <tbody>
{rows}  </tbody>
</table>
<p class="count" id="shown"></p>

<script>
function filterTable() {{
  const q = document.getElementById("search").value.toLowerCase();
  const rows = document.querySelectorAll("#table tbody tr");
  let visible = 0;
  rows.forEach(r => {{
    const match = r.innerText.toLowerCase().includes(q);
    r.style.display = match ? "" : "none";
    if (match) visible++;
  }});
  document.getElementById("shown").textContent = q ? `Показано: ${{visible}}` : "";
}}

let sortDir = {{}};
function sortTable(col) {{
  const tbody = document.querySelector("#table tbody");
  const rows = Array.from(tbody.querySelectorAll("tr"));
  sortDir[col] = !sortDir[col];
  rows.sort((a, b) => {{
    const av = a.cells[col].innerText.toLowerCase();
    const bv = b.cells[col].innerText.toLowerCase();
    return sortDir[col] ? av.localeCompare(bv) : bv.localeCompare(av);
  }});
  rows.forEach(r => tbody.appendChild(r));
}}
</script>
</body>
</html>"""

out = "channels.html"
with open(out, "w", encoding="utf-8") as f:
    f.write(html)

print(f"✅ Сохранено: {out} ({len(channels)} каналов)")
