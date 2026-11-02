const fs=require('fs');
const SID_SESSION="jia-audit-1019";
const ACTOR="调用方甲(闭环队-1019)";
function absent(why){return {N:0,Basis:0,Source:"",Absent:true,Refused:false,Why:why};}
function mkInput(call,contentBytes,noticeWhy){
  return {
    Call:call,
    Order:["system","user"],
    Parts:[{Kind:"system",Parts:1,Bytes:Math.round(contentBytes*0.64)},{Kind:"user",Parts:1,Bytes:contentBytes-Math.round(contentBytes*0.64)}],
    ContentBytes:contentBytes,
    Tokens:absent("分词器在对端；这一侧连 content_bytes 都只是估算，估 token 没有依据"),
    Budget:{CallBytesCeiling:200000,TransportSlackPct:15,ContentCeiling:170000,Shares:{system:20,user:20},LeftoverPct:60,FixedOverhead:absent("骨架字节要装配器数，模型这一侧数不到"),EffectiveCeiling:170000,ClampRounds:0},
    Cuts:[],
    Notice:{Sent:false,Trimmed:false,Why:noticeWhy,Text:""}
  };
}
function mkOutput(call,saysBytes,saysSha,toolCalls,malformed,streak){
  return {
    Call:call,Streaming:false,Finish:{Reason:"",Said:false},Model:"",ModelSaid:false,WireFormat:"",WireFormatSaid:false,
    Says:{Bytes:saysBytes,Kept:saysBytes,SHA256:saysSha},
    UsageIn:absent("分词器在对端，外壳没把 usage 递到这一侧"),
    UsageOut:absent("分词器在对端，外壳没把 usage 递到这一侧"),
    WireBytesOut:absent("请求体字节由外壳编码后数，不在这一侧可见面上"),
    WireBytesIn:absent("通道字节是传输层数的，不在这一侧可见面上"),
    Chunks:absent("按非流式记，结构上没有分帧数"),
    FirstByteMs:absent("按非流式记，结构上没有首帧等待"),
    MaxGapMs:absent("按非流式记，结构上没有帧间静默"),
    ToolCalls:toolCalls,Malformed:malformed,MalformedStreak:streak,
    Failure:{Kind:"",Detail:"",Status:absent("没故障，也没有对端响应可抄状态码"),RetryAfterMs:absent("没故障，对端也没说要等多久"),Downgrade:false}
  };
}
const base=" ContentBytes/Parts.Bytes 是裸整数、结构上不能表达缺席；账上这个数是我对提示词字节的估算，不是实测。Says.Bytes 取本阶段我写出的主产物文件字节（实测），作模型原话的代理——我的对话推理正文没有落成文件，量不到。";
const calls=[
  {id:101,call:1,cb:18800,says:304,sha:"34217ba95153ce29e18a0d558d059898badc400c109f1f051a948233292f7265",tc:6,mf:0,st:0,note:"接入探明阶段：GET 探针、initialize、tools/list、解码工具面。"+base},
  {id:102,call:2,cb:20500,says:4390,sha:"5a7697f7ee492472d8640109c874e0bd377de143b3b9a58e663803d8ad044738",tc:9,mf:0,st:0,note:"49 格清点阶段：读判据表、扫两本账本、逐格分类 absent/empty/filled、复算 filledBoth。"+base},
  {id:103,call:3,cb:22000,says:1360,sha:"e6e78a62e4f9b0edd712d8fd00c97f4d5ca786914fafa0129e22f0161d46ebfd",tc:25,mf:1,st:1,note:"读判据/源码与综合归因阶段：读 contract 与 input/output/measure/mcpsrv 源、claim 普查、构造自报落账。ToolCalls 含 1 次读源码路径写错的失败(malformed)。"+base}
];
for(const c of calls){
  const req={jsonrpc:"2.0",id:c.id,method:"tools/call",params:{name:"kernel.record_call",arguments:{session:SID_SESSION,actor:ACTOR,input:mkInput(c.call,c.cb,c.note),output:mkOutput(c.call,c.says,c.sha,c.tc,c.mf,c.st)}}};
  fs.writeFileSync("rec"+c.call+".json",JSON.stringify(req));
  console.log("wrote rec"+c.call+".json  inputContentBytes="+c.cb+" partsBytes="+Math.round(c.cb*0.64)+"/"+(c.cb-Math.round(c.cb*0.64)));
}
