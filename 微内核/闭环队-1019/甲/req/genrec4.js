const fs=require('fs');
const SID_SESSION="jia-audit-1019";
const ACTOR="调用方甲(闭环队-1019)";
function absent(why){return {N:0,Basis:0,Source:"",Absent:true,Refused:false,Why:why};}
const cb=23000;
const note="收尾落账+写报告阶段：写出 报告.md（五节全），Says.Bytes/SHA256 取 报告.md 实测字节与哈希（23973B / eb082abb…fd416）作模型原话代理——对话推理正文没落成文件，量不到。ContentBytes 仍是估算裸整数，结构上不能表达缺席。"+
" 本发 ToolCalls 计 18：写报告、算哈希、生成请求、check、record、tally/readers_report/verify 收尾核对等。";
const input={Call:4,Order:["system","user"],
 Parts:[{Kind:"system",Parts:1,Bytes:Math.round(cb*0.64)},{Kind:"user",Parts:1,Bytes:cb-Math.round(cb*0.64)}],
 ContentBytes:cb,
 Tokens:absent("分词器在对端；这一侧连 content_bytes 都只是估算，估 token 没有依据"),
 Budget:{CallBytesCeiling:200000,TransportSlackPct:15,ContentCeiling:170000,Shares:{system:20,user:20},LeftoverPct:60,FixedOverhead:absent("骨架字节要装配器数，模型这一侧数不到"),EffectiveCeiling:170000,ClampRounds:0},
 Cuts:[],Notice:{Sent:false,Trimmed:false,Why:note,Text:""}};
const output={Call:4,Streaming:false,Finish:{Reason:"",Said:false},Model:"",ModelSaid:false,WireFormat:"",WireFormatSaid:false,
 Says:{Bytes:23973,Kept:23973,SHA256:"eb082abb049b2b26f70510589b63fb2638a02953313b2103be9b1ebee98fd416"},
 UsageIn:absent("分词器在对端，外壳没把 usage 递到这一侧"),
 UsageOut:absent("分词器在对端，外壳没把 usage 递到这一侧"),
 WireBytesOut:absent("请求体字节由外壳编码后数，不在这一侧可见面上"),
 WireBytesIn:absent("通道字节是传输层数的，不在这一侧可见面上"),
 Chunks:absent("按非流式记，结构上没有分帧数"),
 FirstByteMs:absent("按非流式记，结构上没有首帧等待"),
 MaxGapMs:absent("按非流式记，结构上没有帧间静默"),
 ToolCalls:18,Malformed:0,MalformedStreak:0,
 Failure:{Kind:"",Detail:"",Status:absent("没故障，也没有对端响应可抄状态码"),RetryAfterMs:absent("没故障，对端也没说要等多久"),Downgrade:false}};
const req={jsonrpc:"2.0",id:104,method:"tools/call",params:{name:"kernel.record_call",arguments:{session:SID_SESSION,actor:ACTOR,input:input,output:output}}};
fs.writeFileSync("rec4.json",JSON.stringify(req));
const chk={jsonrpc:"2.0",id:105,method:"tools/call",params:{name:"kernel.check_call",arguments:{session:SID_SESSION,actor:ACTOR,input:input,output:output}}};
fs.writeFileSync("chk4.json",JSON.stringify(chk));
console.log("wrote rec4.json chk4.json");
