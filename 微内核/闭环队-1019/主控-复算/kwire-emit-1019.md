<!-- kwire:params -->
| 侧 | 调用方要写的键 | JSON 类型 | 整块必填 | 少写这一处会怎样 |
|---|---|---|---|---|
| input | Call | number | 否 | 落账拒 |
| input | Order | array<string(PartKind)> | 否 | 落账拒 |
| input | Parts | array<unit PartCount> | 否 | 落账拒 |
| input | ContentBytes | number | 否 | 落账拒 |
| input | Tokens | unit Measure | 否 | 落账拒 |
| input | Budget | unit Budget | 否 | 落账拒 |
| input | Cuts | array<unit Cut> | 否 | 静默落账 |
| input | Notice | unit Notice | 是 | 门口拒 |
| output | Call | number | 否 | 落账拒 |
| output | Streaming | boolean | 否 | 正常发=落账拒 故障发=落账不变 参数被拒发=落账拒 |
| output | Finish | unit Finish | 是 | 门口拒 |
| output | Model | string | 否 | 落账拒 |
| output | ModelSaid | boolean | 否 | 落账拒 |
| output | WireFormat | string | 否 | 正常发=落账拒 故障发=落账不变 参数被拒发=落账拒 |
| output | WireFormatSaid | boolean | 否 | 正常发=落账拒 故障发=落账不变 参数被拒发=落账拒 |
| output | Says | unit Says | 否 | 落账拒 |
| output | UsageIn | unit Measure | 否 | 落账拒 |
| output | UsageOut | unit Measure | 否 | 落账拒 |
| output | WireBytesOut | unit Measure | 否 | 落账拒 |
| output | WireBytesIn | unit Measure | 否 | 落账拒 |
| output | Chunks | unit Measure | 否 | 落账拒 |
| output | FirstByteMs | unit Measure | 否 | 落账拒 |
| output | MaxGapMs | unit Measure | 否 | 落账拒 |
| output | ToolCalls | number | 否 | 正常发=静默落账 故障发=落账不变 参数被拒发=落账拒 |
| output | Malformed | number | 否 | 正常发=落账不变 故障发=落账不变 参数被拒发=落账拒 |
| output | MalformedStreak | number | 否 | 正常发=落账不变 故障发=落账不变 参数被拒发=落账拒 |
| output | Failure | unit Failure | 是 | 门口拒 |

<!-- kwire:units -->
| 单位 | 成员 | JSON 类型 |
|---|---|---|
| Budget | CallBytesCeiling | number |
| Budget | ClampRounds | number |
| Budget | ContentCeiling | number |
| Budget | EffectiveCeiling | number |
| Budget | FixedOverhead | unit Measure |
| Budget | LeftoverPct | number |
| Budget | Shares | object<键 string(PartKind) 到 number> |
| Budget | TransportSlackPct | number |
| Cut | FromBytes | number |
| Cut | Kind | string(PartKind) |
| Cut | Ref | string |
| Cut | RefCall | number |
| Cut | Role | string(Role) |
| Cut | SHA256 | string |
| Cut | Squeeze | string(Squeeze) |
| Cut | ToBytes | number |
| Failure | Detail | string |
| Failure | Downgrade | boolean |
| Failure | Kind | string(FailKind) |
| Failure | RetryAfterMs | unit Measure |
| Failure | Status | unit Measure |
| Finish | Reason | string |
| Finish | Said | boolean |
| Measure | Absent | boolean |
| Measure | Basis | number(Basis) |
| Measure | N | number |
| Measure | Refused | boolean |
| Measure | Source | string |
| Measure | Why | string |
| Notice | Sent | boolean |
| Notice | Text | string |
| Notice | Trimmed | boolean |
| Notice | Why | string |
| PartCount | Bytes | number |
| PartCount | Kind | string(PartKind) |
| PartCount | Parts | number |
| Says | Bytes | number |
| Says | Kept | number |
| Says | SHA256 | string |

<!-- kwire:holes -->
| 侧 | 少写的那一处 | 落账后被改署成实测的格 | 两份夹具各撞到哪儿 |
|---|---|---|---|
| input | Cuts | input Cuts#folded | 正常发=静默落账 故障发=静默落账 参数被拒发=静默落账 |
| input | Notice.Trimmed | input Notice.Trimmed | 正常发=静默落账 故障发=静默落账 参数被拒发=静默落账 |
| input | Notice.Why | input Notice.Why | 正常发=静默落账 故障发=静默落账 参数被拒发=静默落账 |
| output | Chunks.N | output Chunks | 正常发=静默落账 故障发=落账不变 参数被拒发=静默落账 |
| output | Failure.Downgrade | output Failure.Downgrade | 正常发=落账不变 故障发=落账不变 参数被拒发=静默落账 |
| output | FirstByteMs.N | output FirstByteMs | 正常发=静默落账 故障发=落账不变 参数被拒发=静默落账 |
| output | MaxGapMs.N | output MaxGapMs | 正常发=静默落账 故障发=落账不变 参数被拒发=静默落账 |
| output | Says.Kept | output Says.Clipped()、output Says.Kept | 正常发=静默落账 故障发=落账不变 参数被拒发=静默落账 |
| output | ToolCalls | output ToolCalls | 正常发=静默落账 故障发=落账不变 参数被拒发=落账拒 |
| output | WireBytesIn.N | output WireBytesIn | 正常发=静默落账 故障发=静默落账 参数被拒发=静默落账 |
| output | WireBytesOut.N | output CostCountable()、output Sent()、output WireBytesOut | 正常发=静默落账 故障发=静默落账 参数被拒发=静默落账 |
