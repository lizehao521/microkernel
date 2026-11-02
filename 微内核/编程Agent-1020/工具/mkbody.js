const fs = require('fs');
const code = 'package main\n\nimport "fmt"\n\nfunc main() {\n\tx := 1\n\tx := 2\n\tfmt.Println("a")\n\tif err != nil {\n\t}\n\t_ = x\n}\n';
fs.writeFileSync(process.argv[2], JSON.stringify({ session: 'curl-timing', code, question: 'see', lang: 'go' }));
console.log('body bytes', fs.statSync(process.argv[2]).size);
