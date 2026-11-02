module pgagent

go 1.27

require agentkernel v0.0.0

// 内核树是只读的：这里只 require，不复制判据、不改它一个文件。
// 复核姿势：改完之后 diff -rq 对 TEMP 备份，差异只许是内核树里的 cmd/agentd 那一条。
replace agentkernel => ../../../微内核/微内核
