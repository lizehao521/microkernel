const fs = require('fs');
const raw = fs.readFileSync('tools_list.json','utf8');
const j = JSON.parse(raw);
for (const t of j.result.tools) {
  console.log('=== ' + t.name + ' ===');
  console.log('desc: ' + t.description);
  console.log('schema: ' + JSON.stringify(t.inputSchema));
  console.log('');
}
