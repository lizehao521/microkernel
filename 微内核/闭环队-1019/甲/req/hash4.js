const fs=require('fs');
const b=fs.readFileSync('../报告.md');
const c=require('crypto');
console.log(b.length, c.createHash('sha256').update(b).digest('hex'));
