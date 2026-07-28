# TOOLS

- `bazi`：`chart` 用于排盘；`dayun` 用于阶段序列；`resolve_pillars` 携带性别反查四柱对应出生日期，唯一已出生候选可继续计算大运。
- `knowledge`：`search` 结果包含引用正文、书名、篇章和内部标识；`get_chunk` 只服务用户明确要求的完整正文核验；`model_status` 检查检索模型状态。
- 每轮成功的同 action 和同 payload 只调用一次；已有结果直接用于最终综合。
- `time`：仅处理当前时间或时区问题。
- 用户侧引用使用真实 `source_title` 与 `heading`；`source_id` 与 `chunk_id` 留在运行时内部校验。
- 工具错误按原错误码说明修正信息，禁止绕过地点、时间或权限错误继续推断。
