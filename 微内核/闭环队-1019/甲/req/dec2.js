const fs=require('fs');
const j=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const c=j.result.content;
for(const x of c){console.log(x.text!==undefined?x.text:JSON.stringify(x));}
