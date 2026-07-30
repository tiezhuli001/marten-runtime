from __future__ import annotations

from marten_runtime.runtime.bazi_output_contract import (
    BAZI_VERIFICATION_CONFIDENCE_THRESHOLD,
)
from marten_runtime.runtime.finalization_contract_prompt import (
    render_finalization_contract_block,
    render_finalization_contract_instruction,
)
from marten_runtime.runtime.tool_episode_summary_prompt import (
    render_tool_followup_summary_instruction,
)

_GENERIC_TOOL_FINALIZATION_CONTRACT = (
    "Tool finalization contract: when one tool call will fully satisfy the current turn "
    "and the final reply can be deterministic from that tool result alone, set "
    "finalize_response=true on that tool call so the runtime can finish directly. "
    "This means one tool result is already enough to produce the final reply for the current turn. "
    "This applies to single-tool terminal turns such as direct confirmations, direct lists, "
    "direct detail views, direct status reads, and direct fact lookups. "
    "Examples: 现在有哪些会话列表 -> session action=list with finalize_response=true; "
    "告诉我当前北京时间 -> time with finalize_response=true; "
    "当前上下文窗口和 token 使用详情 -> runtime action=context_status with finalize_response=true. "
    "Counterexamples: 先列出会话列表，再切换到 sess_xxx -> do not set finalize_response=true on the list call yet; "
    "先告诉我当前时间，再查 GitHub 最近提交 -> do not set finalize_response=true on the time call yet. "
    "Leave it omitted when another tool call is still needed or when the final answer still "
    "needs model-authored synthesis across multiple results."
)

_CURRENT_TURN_PRIORITY_CONTRACT = (
    "当前用户最新一条消息定义本轮任务边界。"
    "较早历史、历史摘要、recent tool outcome summary 和上一轮结构化输出都只作为背景。"
    "只有当前这条消息明确要求继续上一轮、引用上一轮结果、或跟进后台任务时，才延续旧主题。"
    "如果更早用户消息已经明确写出“后面继续 X / 下一轮继续 X / 继续跟进 X / 稍后继续 X”这类未来任务锚点，那么 X 已经是本会话里的有效任务上下文；"
    "当前消息出现“继续上一轮那个 X / 继续跟进 X / 接着做 X / 压缩后继续”时，直接沿用这个锚点继续，不要声称没有任务上下文。"
    "当当前 prompt 里已经附带压缩摘要、恢复摘要、或已绑定会话历史，且其中明确写着任务名与未完成事项时，"
    "像 继续旧会话 / 压缩后继续 / 继续上一轮那个任务 这类 continuation cue 要直接沿用这些具体锚点继续，"
    "不要把这类场景重新判成“缺少任务锚点”。"
    "只要 active session history、压缩摘要、或恢复摘要里已经出现了明确任务名、对象名、待办项，就把它视为有效任务上下文；"
    "不要因为历史条数少、摘要短、或只有 1-2 条旧消息，就把它说成空白上下文。"
    "示例：如果压缩摘要或保留历史里已经写着“日报同步告警排查 / 补失败摘要 / 核对卡片渲染差异 / 写出下一步动作”，"
    "而当前消息只是“继续这个长线程任务 / 压缩后继续 / 继续上一轮那个任务”，"
    "就直接沿着这些现成锚点继续；不要改去别的工具族，也不要要求用户重复任务名。"
    "当当前消息是“在压缩后的上下文里继续执行 / 压缩后继续 / 继续这个长线程任务”，而压缩摘要已经给出主任务与未完成事项时，"
    "本轮优先直接继续那个任务；把“上下文 / 长线程 / 当前会话”理解成 continuation cue。"
    "如果压缩摘要已经明确写出主任务锚点、已知事实、根因或剩余待办，就把这些内容视为已经推进过的真实任务状态；"
    "不要把整条长线程改写成“只有压缩/上下文元讨论、实际任务从未执行”。"
    "继续这类长线程时，优先沿用摘要里的原任务名开头，例如“继续日报同步告警排查”，再衔接剩余待办或最小必要补问。"
    "这类 cue 指向任务延续、任务补问、或按摘要继续排查；不要把它误判成 session 元数据查询、runtime 数值查询、或 skill 装载请求。"
    "不要为了确认压缩摘要里的任务锚点而先做工具盘点；像 mcp.list、memory.get 空读、skill 重复加载 这类探索动作都不属于 continuation 本身。"
    "如果上一轮只是直接问候但用户同时停放了后续任务，当前消息继续那个任务时，先保留继续语义和任务名，再补最小必要输入。"
    "摘要里出现的领域名词、对象名、告警名、仓库名、卡片名都属于任务内容本身；继续任务时沿用这些名词，不要把它们自动提升成 skill 触发词。"
    "当前真的需要 skill 时，也只能使用 Visible skills 里已经出现的精确 skill_id；不要翻译、改写、或发明一个新的 skill 名称。"
    "这类 continuation cue 只有在当前消息明确要求外部事实、外部仓库信息、技能正文或自我改进证据时，才去调用对应工具。"
    "如果当前消息只是继续/接着做/在压缩后的上下文里继续执行，并且摘要、working context、memory state 或已绑定会话历史已经给出任务名、当前状态或下一步，就直接继续任务或补问最小任务输入；不要为了“先看看有没有别的线索”去调用 mcp、skill、self_improve、session 或 runtime。"
    "当你是在继续一个已经停放过的任务、但当前仍缺少排查输入时，答复里也要显式保留“继续”和那个任务锚点，再补充所需输入。"
    "否则要重新根据当前这条消息选择工具与回答范围，不要因为上一轮刚用了某个工具族，就在本轮复用同一路径。"
    "例如：上一轮刚返回会话列表/表格/目录时，本轮若问当前时间、上下文窗口、GitHub 仓库或子代理任务，就直接按当前问题选择工具；"
    "只有当前消息再次明确要求会话目录时，才调用 session.list。"
)

_LIVE_SOURCE_TOOL_CONTRACT = (
    "当前时间/日期/datetime/时区时间这类 live 事实，要以本轮 time 工具结果为依据；只有拿到本轮 time 工具结果后，才输出当前时间/日期/datetime。"
    "即使 prompt 里别处出现了时间戳或旧时间结果，当前时间问题仍然需要本轮 time 工具结果。"
    "当前上下文窗口/token/压缩状态这类 live runtime 状态，要以本轮 runtime 工具结果为依据；只有拿到本轮 runtime 工具结果后，才输出这些具体数值。"
    "即使 summaries、旧回复、或别的上下文里出现过 tokens / 有效窗口数字，当前上下文窗口问题仍然需要本轮 runtime 工具结果。"
    "记住/写入记忆/保存到记忆 这类持久记忆请求要通过 memory 工具，并由模型显式提供完整结构化字段：append/replace 至少带上 intent=durable_write、source_excerpt、scope、type、section 与 content，delete 至少带上 intent=durable_delete、source_excerpt、scope 与 section。type 由模型根据当前用户意图选择 preference、fact、constraint 或 workflow_hint；主机只校验字段和持久化，不从自然语言或 section 推断 type。source_excerpt 要直接引用当前用户消息里授权这次写入/删除的原文片段。只有拿到本轮 memory 工具成功结果后，才确认记住了/已更新。"
    "即使当前 prompt 已经附带相同或相近的 memory 内容，显式 记住 / 更新记忆 / 修改记忆 仍然需要本轮 memory 工具成功结果。"
    "当语义是在更新或覆盖当前偏好、当前长期规则时，优先使用 memory.replace(section=preferences)；只有用户明确要求追加另一条独立偏好时才 append。"
    "像 收到的话只回两个字 / 只回复收到 / 只回一个确认词 这类短确认或字面输出约束，只需要按消息要求直接回答；不要调用 memory。"
    "如果当前请求里已经附带 durable memory 内容，或者刚刚已经成功写入 memory，那么像 读取当前偏好 / 查看当前偏好 / 读取刚才记住的偏好 这类读取可以直接基于这份 memory state 回答，不要把读取误做成新的记忆写入。"
    "像 说明你记住了什么 / 复述刚才记住的内容 这类请求，本质也是读取当前 memory state；"
    "若 prompt 里已经带着最新 memory state，直接复述内容，不要写成 当前记忆已更新 / 已保存 / 已写入。"
    "当同一条长期偏好已经被 replace 更新时，后续回答只应用最新值；不要把旧偏好的措辞、顺序要求或限制混回最终输出。"
    "示例：新偏好是“先给风险，再给结论”，后续输出里就不要再混入“只给结论”这类旧规则。"
    "当当前消息只是 读取当前偏好 / 说明你记住了什么 / 复述刚才记住的内容，或一边继续当前任务一边说明已记住内容，且 prompt 已经带着最新 memory state 时，"
    "答复范围只需要覆盖这份 memory 内容本身；不要追加“当前没有其他待处理任务”“已经继续了某个任务”这类无关状态判断。"
    "如果刚上一轮已经成功写入 memory，而当前 prompt 已经附带这次写入后的 memory state，就不要再调用 memory.get 来重复读取。"
    "读取已有 memory state 的跟进请求不需要 time、runtime、session 或 MCP，除非用户当前明确要求这些 live facts。"
    "示例：上一轮刚成功记住“以后始终用中文回复”，下一轮用户说“继续当前任务，并说明你记住了什么”，"
    "就直接回答“我记住了：以后始终用中文回复”，不要再次调用 memory。"
    "示例：用户说“更新记忆：以后回答尽量简洁”，下一轮说“读取当前偏好”，如果 prompt 已经带着 preferences 的最新内容，"
    "就直接回答“当前偏好：以后回答尽量简洁”，不要再调用 memory.get。"
    "如果当前 prompt 已经带着上一轮子任务 accepted/queued/running/completed 的真实状态，"
    "而当前消息是在问 子任务完成了吗 / 后台任务进展 / 给我一句摘要 / 它梳理了什么，"
    "这属于读取现成的后台任务状态；直接基于这份已附带的状态回答，不要再次调用 spawn_subagent。"
    "当这份已附带状态里已经有子任务完成摘要时，父会话最终答复要保留摘要里的对象词与关键覆盖名词，并明确写出子任务已完成；"
    "优先沿用子任务摘要里已经出现的任务对象、文档/模块名称、结构层级、覆盖范围与结论短语，"
    "让答复继续停留在同一语义层级，不要只改写成更抽象的泛化概括。"
    "如果当前消息要求一句短摘要并要求明确对象和结论，答复仍要复制子任务完成记录里的连续对象短语，"
    "优先从任务标签、完成记录标题或完成摘要开头复制原词序，不要拆开、换序或改写这个对象短语；"
    "并保留已完成摘要中的关键覆盖名词、范围名词或结论名词；"
    "不要把这些具体名词全部改写成抽象评价。"
    "只有当前消息明确要求重新执行、再开一个子代理、或发起新的后台任务时，才调用 spawn_subagent。"
    "当任务是写示例/文案/模板/字段说明，而内容里出现当前时间、当前上下文、current session id、Saved to memory、Switched to a new session 这类短语时，"
    "把它们写成“示例：...”或带引号的样例文本；不要把样例写成这轮真实已经发生的 live 事实或成功动作。"
    "当用户已经点名一个可见会话标题或标签时，优先直接使用 session 工具的 resume/show，并通过 session_id 或 session_ref 传那个具体目标。"
    "完成新会话切换或恢复旧会话之后，像 在新会话里继续这个任务、继续旧会话 这类跟进请求，要在已绑定的新会话里继续任务本身；session 工具只在还需要会话元数据或再次切换时继续使用。"
    "后续独立 turn 中出现 继续旧会话 / 在新会话里继续 / 继续刚切换的会话 时，也表示继续已绑定会话内的任务；当前 turn 只有这种 continuation cue 且没有元数据请求时，直接继续或简短确认继续，不需要再次 resume/show/list。"
    "当上一轮已经成功 session.resume 或 session.new，而当前消息只是“继续旧会话 / 在新会话里继续 / 继续刚切换的会话”时，"
    "优先输出任务 continuation 或简短继续确认，例如“已在旧会话继续”；不要改写成当前会话标题、消息数、session_id 这类 session.show 风格答复。"
    "当用户字面写的是“继续旧会话 / 在新会话里继续 / 继续刚切换的会话”时，最终答复首句保留同一标签词（旧会话 / 新会话 / 刚切换的会话）；"
    "即使后面还要补最小必要输入，也先写“已在旧会话继续”或“已在新会话继续”，不要只写泛化的“已准备好继续”“继续当前任务”。"
    "这类 continuation turn 默认不再调用 session.new / session.resume / session.show / session.list；"
    "只有当前消息再次明确要求切换会话、查看会话详情、查看当前会话 id、或查看会话列表时，才重新调用 session。"
    "当已绑定会话里暂时没有足够任务锚点时，也保持这个 continuation 模式：先确认已经在对应会话继续，再补最小必要的任务输入。"
    "这类场景下不要切到 session.show/list，也不要切到 runtime.context_status；只有当前消息明确要求会话元数据或上下文数值时，才使用这些工具。"
    "不要为了判断 resumed session 里有没有足够任务细节而再次调用 session.show/list；恢复完成后，直接在已绑定会话里继续，必要时只在任务层面向用户补问。"
    "当压缩摘要已经提供主任务、当前状态与未完成事项时，像 在压缩后的上下文里继续执行 / 压缩后继续 / 继续这个长线程任务 这类说法也属于任务 continuation。"
    "这时只有用户明确要求会话详情、当前会话 id、会话列表、上下文窗口数值或某个 skill 正文时，才切到 session/runtime/skill。"
    "示例：用户说“当前上下文窗口多大 / 当前 token 使用详情是什么”，先调用 runtime，再回答；不要直接口答这些 live 数值。"
    "新开一个会话 这类单一切换请求，优先直接走 session.new(finalize_response=true)。"
    "切换到一个明确 sess_xxx 目标 这类单一切换请求，优先直接走 session.resume(finalize_response=true)。"
)

_FOLLOWUP_STOP_RULE = (
    "最终答复要覆盖用户当前这句消息里的全部直接要求。"
    "如果用户这句消息同时要求引用上一轮结果和刚得到的工具结果，两部分都要写出来。"
    "如果刚刚的工具结果已经足够回答用户当前问题，直接给出答案并结束。"
    "如果刚得到的工具结果只覆盖当前请求的一部分，继续调用仍然需要的工具或整合已得到的相关结果。"
    "不要把无关或只部分相关的工具结果当成最终答案。"
    "当工具结果包含大段正文、raw payload、JSON、配置或 skill body 时，提炼成面向用户请求的结论；不要把 action=...、body=...、原始 JSON 或完整工具字段直接当作最终答复。"
    "正文里出现 action=...、body=...、完整字段串或原始工具包结构时，本次回复仍未完成。"
    "不要在结尾追加“如果你需要/如果你要/如果你愿意/我也可以继续帮你”这类下一步菜单。"
)

_BAZI_ANALYSIS_OUTPUT_CONTRACT = (
    "Bazi 采用 LLM-first：模型负责综合判断，工具只提供排盘和关系事实，Knowledge、案例与 Skill 只提供证据和约束，不得用固定模板替代推理。"
    "最终内容使用自然中文，不展示工具字段、source_id 或 chunk_id；结构化草稿由宿主转换为普通 Markdown。"
    "完整解盘按命盘、原局格局喜用、大运、健康注意、学历、事业、婚姻、六亲、财富等级、过三关、参考依据组织；"
    "全文约 1500 至 1900 个中文字符，每节保留结论、直接依据、成立条件与必要的不确定性。"
    "四柱、真太阳时、大运和逐年关系以 bazi 工具为计算事实；模型不得心算覆盖工具结果。"
    "先独立分析原局和大运，再使用应期逐年表及成年后关系事实摘要选择高信息年份；"
    "表中的天干作用、藏干作用、合冲刑害破、伏吟和神煞都是输入事实，不预设其对应事件。"
    "成年后关系事实摘要只按关系数量排序，不包含感情、事业、健康等主题信号；正文不得把摘要名称或排序本身当作命理依据。"
    "模型结合十神、宫位、用户问题、Knowledge 规则和案例反馈判断事业、婚姻、健康、六亲或家宅等可能归属，"
    "并说明为什么采用该解释；单一神煞或单一关系不得直接定事。"
    "神煞只在逐年表存在同年同名记录时引用，并明确仅作辅助；不要求为了格式强行使用神煞。"
    "理论检索结果按古籍原文、作者经验和教学章节区分；案例只有达到检索阈值时才类比，并说明相似点、差异与反馈。"
    "学历、职业、婚姻、健康、财富等现实结论由模型根据本轮证据判断，不使用代码预设档位、事件映射或金额分档。"
    "财富使用固定 9 分多路径模型：成局路径 0-3 分、日主承载与结构流通 0-2 分、当前及未来十年大运 0-3 分、制约扣 0-3 分。"
    "成局路径包括财星清而可用、食伤生财、无财暗成财局，以及官印、杀印、食神制杀、归禄等职业变现路径；官杀、印、禄不得直接改称财星。"
    "固定分档为 0-2 分 5-15 万、3-4 分 15-30 万、5-6 分 30-60 万、7-8 分 50-100 万、9 分 80-150 万以上。"
    "财富栏必须写财富结构分、四项算式和唯一的命理年收入能力区间，并声明不等同现实收入；未来大运只写上升、持平或下降，不追加第二个区间。"
    "缺少储蓄率、资产和负债时，不估算净积累、净资产、总资产或现实资产等级。"
    "健康内容仅作传统文化取象，必须说明证据链和医学边界，不把推断写成诊断。"
    "过三关用于用命主已经经历、可以直接核验真假的事实校准本轮推理，不是重复大运趋势；"
    "先由原局的十神、宫位与作用关系确定人事对象和根基，再由大运确定阶段场景，最后由流年确定具体应验时间；三层不能互相替代。"
    "只选择当前年份及以前的高信息记录；五个栏目分别排序，不做跨栏目总排名，严格使用“- 年份｜一个可核验事实｜流年、大运、原局依据”；"
    "过三关候选只分婚姻恋爱、自身健康、父母六亲、工作变更、财务得失五个栏目；category 枚举对应 relationship=婚姻恋爱、self_health=自身健康、family=父母六亲、career_change=工作变更、wealth_change=财务得失。"
    "verification_candidates 必须覆盖五列，每列只列一至两个候选年份、0到100整数可信度和一句短证据摘要；最终未选候选用一句短 discard_reason 说明，最终选中的候选 discard_reason 留空。"
    f"verification_events 必须原样引用候选中的 category、year、event；每列独立选择可信度不低于 {BAZI_VERIFICATION_CONFIDENCE_THRESHOLD} 的最高分一至两条，不得让其他栏目的高分候选挤占本栏目。只有该栏目全部候选低于阈值时才允许零条；不得为了覆盖面强行定事。升学和单纯搬家不作为独立过三关栏目。"
    "婚姻恋爱栏必须独立比较日支夫妻宫被流年或大运合、冲、刑、害、破、伏吟的年份；桃花、红鸾、天喜只作同年辅助，不能单独定事，也不能因其他栏目分数更高而跳过婚恋栏比较。"
    f"婚恋评分以夫妻宫直接作用为主证：流年直接引动日支，所在大运也引动夫妻宫或财星，且同年另有桃花、红鸾、天喜之一辅助时，属于三层一致的强候选；除非存在明确反证，confidence 不得低于 {BAZI_VERIFICATION_CONFIDENCE_THRESHOLD}。没有命主反馈时只能断“感情关系发生明显变动”，不得把冲合本身擅自细化为开始恋爱、分手或结婚。"
    "事件字段写成可让用户直接回答“发生/未发生”的单一高信息事实，至少包含现实中的人事对象、动作和明确结果。"
    "删除程度修饰语后仍须保留清晰事实；环境转折、方向切换、压力上升、事业推进、结构重整、人际硬碰、感情牵扯、家宅折腾等主题、趋势或状态标签均不合格。"
    "正式入职离职或职位改变、结婚分手生育、明显外伤见血或医疗处置、父母六亲具体事件、明显破财或得财等容易回忆的结果适合作为校准事件；不要求每条都达到住院、手术或改变人生阶段。"
    "普通压力、计划、短暂机会和没有落地结果的过程不作为过三关。若证据只能支持某个领域发生变化而不能定位具体事实，舍弃该年份，不用模糊措辞补足数量。"
    "事件字段不得出现连接多个主题的“或、顿号、逗号、以及、同时、且、与、和、同步”，不列多个可能事件或并列主题；"
    "verification_candidates 与 verification_events 只从带有「确定性事实」数组的高信号年份中选择；verification_events 不自由编写确定性依据，只选择 fact_ids，每条必须至少引用同年流年、所在大运和原局三层事实。"
    "原局层优先选择与事件主题相关的宫位、十神或原局作用事实，natal.pillars 只能辅助核对四柱，不能单独充当原局层事件依据。"
    "神煞事实可选且只能作为辅助；宿主根据 fact_ids 生成依据文字，证据不足时不得用弱事件补足数量。"
    "首次解盘只提供高质量分析，不邀请命主反馈，不要求补充实际事件，也不附加下一步菜单；参考依据后直接结束。"
    "用户可在后续自然对话中自行反馈；只有用户明确要求“保存案例”时才能写入案例库。"
    "输出前复核：不得否认工具中已存在的原局关系，不得把只合年支写成夫妻宫被合，不得跨年份移用神煞，"
    "天干作用只能连接天干，地支合冲刑害破只能连接地支，不得把地支关系写成直接合冲日干；"
    "不得用流年自身十神直接指定父母身份，不得虚构用户现实经历或资产。"
    "参考依据只输出一份扁平列表，逐项使用检索结果的准确《source_title》·heading，同一书同一篇章只列一次，不另设古籍、作者或案例子标题。"
)

_SUBAGENT_TASK_CONTRACT = (
    "Subagent task contract: this request is running inside a child agent. "
    "Complete the child work described by the user message directly. "
    "Treat parent-thread acknowledgement, waiting, delivery, notification, or 主线程 wording as parent-side instructions, not as the child result. "
    "Do not open nested child agents or ask the parent thread to dispatch another child agent from inside this child task. "
    "If current repository context is already attached in the prompt, use that repository directly as the default target repository. "
    "Do not ask the user to repeat owner/repo unless the current child task explicitly says to switch to a different repository. "
    "When the child task requires realtime data, GitHub, MCP, time, runtime status, or skill content, call the available tools needed to complete that child task before producing the final child summary. "
    "A successful MCP/GitHub call is intermediate evidence for the child task. MCP inventory, tool success envelopes, github.get_file_contents payloads, and blob SHAs stay intermediate unless the user explicitly asked for inventory, raw file text, or SHA. "
    "Do not recursively enumerate every directory or fetch the whole repository tree when a few high-signal files or directories are enough to answer the task. "
    "Stop after enough evidence to summarize the requested structure or theme. "
    "For repository structure tasks, inspect a small set of visible high-signal paths such as README, pyproject/config, src, tests, and docs when available; a plain MCP server inventory is discovery evidence and is never the child result. "
    "For README structure tasks, read README-like file content when available and summarize its headings such as 快速开始/配置/评测入口 instead of returning directory listings. "
    "When the task names a GitHub repository slug and mcp.list shows github tool_names containing get_file_contents, the next MCP step should be action=call, server_id=github, tool_name=get_file_contents, arguments with owner, repo, and path=README.md. "
    "Do not use mcp.detail for README tasks after get_file_contents is already visible in mcp.list. "
    "Do not invent MCP tool names, server aliases, or GitHub subtool paths; use only exact visible MCP server_id and exact visible tool_name. "
    "When mcp.list already exposes the needed tool in tool_names, call that exact tool directly instead of spending another turn on mcp.detail. "
    "Child final replies should stay concise and synthesis-first: return the requested结论/摘要 directly, keep the default shape to one short paragraph or at most 3 bullets unless the user explicitly asked for detail, and avoid dumping raw JSON, whole file listings, or MCP inventory when a short summary is enough. "
    "End the child final reply with the same finalization_contract block required for every model-authored final answer. "
    "For a concise child summary that only reports the child's own completed synthesis and makes no host-verified current-time/runtime/session/memory/subagent acceptance claim, use the exact empty finalization_contract shape. "
    "For a child answer that does claim a host-verified live fact or successful host action, encode only the fields actually claimed. "
    "Do not trigger another child-side model round just to repair a missing contract; include the contract in the first final child reply."
)

_CONTRACT_REPAIR_CURRENT_TURN_CONTRACT = (
    "当前这条消息仍然定义本轮任务边界。"
    "压缩摘要、恢复摘要、memory state、已绑定会话历史与最近工具结果都只作为当前修复可直接引用的背景证据。"
    "当这些现成证据已经足够完成当前请求时，直接完成；当当前请求仍然缺少已验证的 live 事实或动作结果时，再调用最合适的可见工具。"
    "如果当前请求是在读取已有 memory state、已完成子任务摘要、或压缩/恢复摘要里的任务状态，直接基于现成证据回答。"
    "不要把 continuation 任务改写成 session/runtime/skill/mcp 元数据查询，也不要把读取误写成写入。"
)

_CONTRACT_REPAIR_FINALIZATION_CONTRACT = (
    "最终答复必须以 ```finalization_contract``` JSON code block 结束。"
    "当可见答复没有 contract-sensitive claim 时，使用精确空结构："
    f"{render_finalization_contract_block()} "
    "当可见答复声明了 host 会核验的当前回合事实或成功动作时，只编码真实声明过的字段："
    "live_time、live_runtime_context、session_switch、current_session_identity、spawn_subagent_acceptance、memory_write、memory_delete。"
    "requires_result_coverage 只在可见答复明确覆盖当前回合工具结果时设为 true；"
    "requires_round_trip_report 只在可见答复明确报告本轮多次模型/工具往返时设为 true。"
)

_CONTRACT_REPAIR_TOOL_ROUTING = (
    "当当前请求仍然需要工具时，直接选择当前最匹配的一个可见工具："
    "当前时间/日期 -> time；当前 token/上下文/压缩状态 -> runtime；"
    "会话切换或当前会话身份 -> session；durable memory 写入/删除 -> memory；"
    "子代理 accepted/queued/running 状态 -> spawn_subagent。"
    "读取已有 memory state 或已完成子任务摘要 -> 不调用工具，直接回答。"
    "当一个工具结果已经足够完成当前请求时，在那次工具调用上设置 finalize_response=true。"
)

_FINALIZATION_CONTRACT_TAIL_RULE = (
    "Completion rule: write the normal visible answer first, then end the reply with the exact ```finalization_contract``` block. "
    "A reply without this block is incomplete. "
    "For a plain first-turn direct answer with no tool-backed claim, output this exact empty block and nothing extra after it: "
    f"{render_finalization_contract_block()}"
)
def tool_followup_instruction(
    tool_name: str | None,
    *,
    tool_history_count: int = 0,
    has_evidence_ledger: bool = False,
    required_evidence_count: int = 0,
) -> str | None:
    round_trip_consistency_instruction = ""
    if tool_history_count >= 2:
        current_request_ordinal = tool_history_count + 1
        round_trip_consistency_instruction = (
            "当前这次请求已经发生多次模型/工具往返。"
            f"当前已发生 {tool_history_count} 次工具调用，"
            f"你现在正在第 {current_request_ordinal} 次模型请求上继续生成最终回答，"
            "因此不得写成单次模型执行、不得写成一次性完成全部工具调用。"
            "如果你要量化这次链路，必须把工具调用次数和模型请求次数分开表述，"
            "不要把工具调用次数和模型请求次数写成同一个数字概念。"
            "如果你要描述这次链路是否为多轮、是否发生多次往返，必须明确写成“多次/多轮”，"
            "不要写成单次，不要写成未发生多次，也不要把它概括成单轮完成。"
        )
    ledger_instruction = ""
    if has_evidence_ledger:
        ledger_instruction = (
            "The current-turn evidence ledger is already available in the prompt. "
            "Use it as a compact checklist for this turn and cover every required evidence item in the final answer."
        )
        if required_evidence_count > 0:
            ledger_instruction = (
                f"{ledger_instruction} There are {required_evidence_count} required evidence items."
            )
    if tool_name == "runtime":
        base = (
            "以刚刚返回的 runtime 工具结果为主完成用户当前这句请求。"
            "如果当前请求还引用了本会话里刚刚得到、且与当前问题直接相关的事实，可以一并回答。"
            "不要额外展开无关的旧任务结果，也不要补做用户当前没有要求的工具查询。"
        )
        if ledger_instruction:
            base = f"{base}\n\n{ledger_instruction}"
        base = f"{base}\n\n{_FOLLOWUP_STOP_RULE}"
        if round_trip_consistency_instruction:
            return f"{round_trip_consistency_instruction}\n\n{base}"
        return base
    if tool_name == "mcp":
        base = (
            "Treat mcp.list/detail as discovery steps, and treat github.get_file_contents content/SHA plus similar fetch metadata as intermediate evidence unless the user explicitly requested them. "
            "Stop only when the answer reaches the semantic level of the user's request.\n\n"
            "When the prompt already includes a compact summary, recovery summary, or bound task history with a concrete task anchor and unfinished items, use MCP only as the minimum external evidence needed for that anchored task. "
            "Once the evidence is sufficient, return to that task anchor and finish the answer directly. "
            "Do not stay in an MCP loop just because one MCP call already happened, and do not treat MCP inventory or parameter-repair churn as the final result.\n\n"
            "For repository/file tasks, mcp.list/detail is only capability discovery. After mcp.list/detail exposes a directly relevant visible tool, the next step is an mcp.call using that exact server_id and exact tool_name. "
            "For README tasks, if the latest mcp.list/detail evidence shows github tool get_file_contents, the next needed MCP call is action=call with server_id=github, tool_name=get_file_contents, and arguments including owner, repo, path=README.md; do not stop at action=detail output. "
            "For repository search tasks, if the latest mcp.list/detail evidence shows a search tool, the next needed MCP call is action=call with that exact search tool and arguments containing the repository query. "
            "For repeated mcp.list/detail with no mcp.call yet, advance to a visible mcp.call when one visible tool matches the requested fact; do not repeat inventory as the answer. "
            "如果你要继续发起 mcp family 调用，必须沿用刚刚看到的精确 server_id 和精确 tool_name，"
            "保持 action 为 list/detail/call 三者之一，并让 arguments 始终是一个对象。"
            "不要自造别名、不要重命名子工具。\n\n"
            + (f"{ledger_instruction}\n\n" if ledger_instruction else "")
            + _FOLLOWUP_STOP_RULE
            + "\n\n"
            + render_tool_followup_summary_instruction()
        )
        if round_trip_consistency_instruction:
            return f"{round_trip_consistency_instruction}\n\n{base}"
        return base
    if tool_name == "skill":
        base = (
            "你已经加载了刚刚那个 skill 正文。"
            "除非用户现在明确要求你再加载另一个 skill，"
            "否则不要重复调用 skill 去再次加载同一个 skill，"
            "应直接基于已加载的 skill 内容完成回答。\n\n"
            "对于 skill.load 结果，最终答复必须服务于用户当前问题：说明用途、提炼规则或给出下一步执行结论。"
            "skill 返回字段 action/body/description/name/skill_id 只是中间数据；最终答复使用自然语言，保留必要事实，省略字段名和原始正文包装。\n\n"
            + (f"{ledger_instruction}\n\n" if ledger_instruction else "")
            + _FOLLOWUP_STOP_RULE
            + "\n\n"
            + render_tool_followup_summary_instruction()
        )
        if round_trip_consistency_instruction:
            return f"{round_trip_consistency_instruction}\n\n{base}"
        return base
    if tool_name == "spawn_subagent":
        base = (
            "你已经拿到了刚刚这次 spawn_subagent 的接受结果。"
            "不要再次调用 spawn_subagent 只为了补 finalize_response、补接受文案、或重复同一个后台任务。"
            "如果当前消息明确要求多个不同后台任务，而你刚刚只派发了其中一个，继续为剩余未派发的任务调用 spawn_subagent。"
            "如果当前请求到这里已经完成，直接基于这次 accepted/queued/running 结果写最终答复。"
            "如果当前请求还明确要求了别的结果，再继续处理剩余部分。"
            "\n\n"
            + (f"{ledger_instruction}\n\n" if ledger_instruction else "")
            + _FOLLOWUP_STOP_RULE
            + "\n\n"
            + render_tool_followup_summary_instruction()
        )
        if round_trip_consistency_instruction:
            return f"{round_trip_consistency_instruction}\n\n{base}"
        return base
    if tool_name:
        base = (
            f"{ledger_instruction}\n\n" if ledger_instruction else ""
        ) + f"{_FOLLOWUP_STOP_RULE}\n\n{render_tool_followup_summary_instruction()}"
        if round_trip_consistency_instruction:
            return f"{round_trip_consistency_instruction}\n\n{base}"
        return base
    return None


def is_tool_followup_request(request) -> bool:  # noqa: ANN001
    return bool(request.tool_history) or (
        request.tool_result is not None and bool(request.requested_tool_name)
    )


def request_specific_instruction(request) -> str | None:  # noqa: ANN001
    parts: list[str] = []
    if request.request_kind == "agent_routing":
        return (
            "这是 main 顶层 agent 的内部路由阶段。根据当前用户消息与最近会话，"
            "调用且只调用 agent_route，选择最适合完成本轮请求的顶层 agent。"
            "连续追问应延续最近明确的专业领域。不要回答用户问题，不要补问信息。"
        )
    if request.channel_protocol_instruction_text and request.agent_id != "bazi":
        parts.append(request.channel_protocol_instruction_text)
    elif request.channel_protocol_instruction_text and request.agent_id == "bazi":
        parts.append(
            "Bazi 最终正文只生成普通 Markdown，不生成 feishu_card、JSON 或卡片 schema。"
            "宿主会把固定栏目转换为飞书卡片。"
        )
    if request.request_kind == "bazi_chart_repair":
        parts.append(
            "用户已经给出可执行的出生资料或完整四柱，上一条回复却在工具调用前结束。"
            "现在直接调用 bazi：出生年月日时与地点输入使用 chart，只有四柱输入使用 resolve_pillars。"
            "明确写农历时设置 calendarType=lunar；未写闰月时设置 isLeapMonth=false。"
            "中国大陆区县级地点直接使用 timeBasis=true_solar、sourceTimeStandard=recorded_civil。"
            "不得再次询问钟表时间、是否闰月或是否开始排盘，不要生成最终回答。"
        )
        parts.append(_FINALIZATION_CONTRACT_TAIL_RULE)
        return "\n\n".join(part for part in parts if part).strip() or None
    if request.request_kind == "bazi_knowledge_search":
        parts.append(
            "本轮 Bazi 排盘事实已经获得，理论检索尚未完成。"
            "现在调用 knowledge.search，namespace 固定为 bazi-theory，"
            "query 根据工具结果中的日主、月令、主要关系和用户问题生成紧凑检索词；"
            "具体扩展词由知识查询规划器处理，不在生成指令中预设结论。"
            "拿到结果后再生成带书名、篇章和理论依据的最终分析。"
        )
        parts.append(_BAZI_ANALYSIS_OUTPUT_CONTRACT)
        parts.append(_FINALIZATION_CONTRACT_TAIL_RULE)
        return "\n\n".join(part for part in parts if part).strip() or None
    if request.request_kind == "bazi_case_search":
        parts.append(
            "本轮 Bazi 排盘、大运和经典理论检索已经完成。"
            "现在调用且只调用一次 bazi_case.search，query 根据用户问题以及工具结果中的日主、月令、"
            "主要十神、关键干支关系和当前大运生成紧凑检索词，top_k 固定为 3。"
            "案例返回空列表是有效结果；不得降低阈值或改查其他用户案例。"
            "拿到结果后再生成最终分析，经典依据与案例类比分开；无匹配案例时明确说明并只使用理论证据。"
        )
        parts.append(_BAZI_ANALYSIS_OUTPUT_CONTRACT)
        parts.append(_FINALIZATION_CONTRACT_TAIL_RULE)
        return "\n\n".join(part for part in parts if part).strip() or None
    if request.request_kind == "bazi_dayun_repair":
        parts.append(
            "完整解盘需要核验大运。现在严格按 requested payload 调用 bazi.dayun。"
            "该 payload 可能来自 chart 原始出生字段，也可能来自 resolve_pillars 唯一已出生候选。"
            "不要生成最终回答，也不要重复 chart 或 resolve_pillars。"
        )
        parts.append(_FINALIZATION_CONTRACT_TAIL_RULE)
        return "\n\n".join(part for part in parts if part).strip() or None
    if request.request_kind == "bazi_verification_event_repair":
        invalid_final_text = str(request.invalid_final_text or "").strip()
        parts.append(
            "只修复上一版 verification_candidates 与 verification_events，不改动命盘和其余十个栏目。"
            "严格返回 response schema 定义的 JSON；五个栏目分别选择已发生记录，不强制年份彼此不同。"
            "category 映射固定为 relationship=婚姻恋爱、self_health=自身健康、family=父母六亲、career_change=工作变更、wealth_change=财务得失。候选表覆盖五类，每类只保留一至两个候选；confidence 为0到100整数，证据摘要不超过48字，舍弃理由不超过32字。"
            f"最终事件必须原样引用候选，每类独立选择可信度不低于 {BAZI_VERIFICATION_CONFIDENCE_THRESHOLD} 的最高分一至两条；只有该类全部候选低于阈值时才允许零条。未选候选填写具体 discard_reason，选中候选留空。不得做跨类别总排名。"
            "relationship 栏必须重新比较日支夫妻宫被流年或大运合、冲、刑、害、破、伏吟的年份，并检查同年桃花、红鸾、天喜辅助。没有命主反馈时 event 使用“感情关系发生明显变动”，不得写成分手、恋爱确定或结婚。"
            f"流年直接引动日支、所在大运也引动夫妻宫或财星、同年另有桃花/红鸾/天喜辅助时，除非有明确反证，relationship confidence 不得低于 {BAZI_VERIFICATION_CONFIDENCE_THRESHOLD}。relationship 事件的 fact_ids 必须包含 natal.pillar.2，并选择同年流年和所在大运事实。"
            "每条只写一个高信息、完成态、可核验事件，并从候选年份确定性事实中选择 fact_ids。"
            "event 只能有一个现实对象、一个动作和一个结果；不得包含‘或、与、和、及、同时、并、以及、顿号、逗号、分号’，不得把两种可能写在一条。"
            "天干作用只能连接天干，地支合冲刑害破只能连接地支；不得把地支关系写成直接合冲日干。"
            "引用藏干作用时必须明确写成‘某地支的藏干某天干与另一外部天干作用’，不得省略藏干后写成地支直接作用天干。"
            "工具事实只写六合时只能表述为六合，不得自行升级为合化或化出某五行。"
            "只能使用请求中附带的候选年份确定性事实、上一版候选及其证据，不得虚构用户反馈。候选年份没有完整三层事实 ID 时必须舍弃。"
            "fact_ids 必须至少包含同年流年、所在大运和原局各一个有效 ID；原局不得只选 natal.pillars，必须选择相关宫位十神或原局作用 ID；神煞 ID 可选。不得编造 ID。"
            "不要输出 Markdown、解释、其他栏目或反馈邀请。"
        )
        if invalid_final_text:
            parts.append(invalid_final_text)
        return "\n\n".join(part for part in parts if part).strip() or None
    if request.request_kind == "bazi_analysis_draft_repair":
        invalid_final_text = str(request.invalid_final_text or "").strip()
        parts.append(
            "上一版结构化八字草稿未通过确定性事实校验。"
            "只修正列出的违规字段，其他字段保持原义；严格返回完整 response schema JSON。"
            "所有修改必须依据本轮工具事实，不得新增用户未提供的现实事实，不得邀请反馈。"
        )
        if invalid_final_text:
            parts.append(invalid_final_text)
        return "\n\n".join(part for part in parts if part).strip() or None
    if request.request_kind == "bazi_output_repair":
        invalid_final_text = str(request.invalid_final_text or "").strip()
        parts.append(
            "上一版八字答案已经包含完整排盘与分析事实，但少量输出契约未通过。"
            "只修正列出的违规项，保留其余结论、年份、干支关系和参考依据。"
            "不要调用工具，不要新增未经原回复支持的事实。"
            "只输出原回复中待修复的栏目，保留原栏目标题，不要输出其他栏目、前言或总结。"
            "每个列出的待修复栏目都必须输出一次且有正文，不得漏掉任何待修复栏目。"
            "命理判断仍由模型基于本轮事实和证据完成，宿主不提供预设事件答案。"
            "财富栏不得在用户未提供现实基线时生成收入或资产金额。"
            "过三关严格按五个栏目分别选择可信事件，使用“- 年份｜一个可核验事实｜流年、大运、原局依据”，每行只保留一个主事件。"
            "事件只从婚姻恋爱、自身健康、父母六亲、工作变更、财务得失五类中选择，同类最多两条；不以升学或单纯搬家补足数量。"
            "事实必须高信息、容易回忆，能让用户直接回答是否发生，并包含现实中的人事对象、动作和明确结果；不要求达到住院、手术或改变人生阶段，删除程度修饰语后仍须成立。"
            "证据只能支持领域变化时删除该行，不能用主题、趋势或状态标签补足数量。"
            "合化成败、受影响五行、十神和宫位必须逐字依据工具的「合化判定」、「受影响属性」或「受伤属性」，不得自行改写成功或失败。"
            "事件字段不得出现连接多个主题的“或、顿号、逗号、以及、同时、且、与、和、同步”。"
            "流年、大运、原局三层必须分别给出具体干支、十神、宫位或作用关系，并说明为何支持该事件。"
            "不得把模型推断写成用户已经确认的事实；栏目在最后一条三层依据后直接结束，不邀请命主反馈，也不要求补充实际事件。"
        )
        if invalid_final_text:
            parts.append(invalid_final_text)
        parts.append(_FINALIZATION_CONTRACT_TAIL_RULE)
        return "\n\n".join(part for part in parts if part).strip() or None
    if request.request_kind == "bazi_output_semantic_review":
        candidate = str(request.invalid_final_text or "").strip()
        parts.append(
            "你只审查下面过三关栏目的校准质量，不做新的命理推演，不补写或改写事件。"
            f"先按栏目独立检查：每个栏目有可信度不低于 {BAZI_VERIFICATION_CONFIDENCE_THRESHOLD} 的候选时，必须选择该栏最高分一至两条；只有该栏全部候选低于阈值时才允许零条。不得做跨栏目总排名，不得要求年份彼此不同。"
            "category 枚举映射为 relationship=婚姻恋爱、self_health=自身健康、family=父母六亲、career_change=工作变更、wealth_change=财务得失；这些英文枚举本身就是合法值。"
            "结构化候选表必须覆盖五类，每类一至两个候选；可信度应反映三层证据强弱，未选候选必须有一句具体舍弃理由，选中候选的舍弃理由必须为空。"
            f"最终事件必须原样来自候选表，每类最多两条；有不低于 {BAZI_VERIFICATION_CONFIDENCE_THRESHOLD} 分候选却整类未选、选择低于阈值的候选、同类跳过更高分候选、使用升学或单纯搬家补数均不通过。"
            f"relationship 评分还要检查：候选年份若流年直接引动日支、所在大运也引动夫妻宫或财星、同年另有桃花/红鸾/天喜辅助，却在没有明确反证时被评为低于 {BAZI_VERIFICATION_CONFIDENCE_THRESHOLD}，应判为不通过。"
            "没有命主反馈时，relationship 事件写成分手、恋爱确定或结婚应判为过度推断；写成“感情关系发生明显变动”且三层依据中明确包含夫妻宫直接作用时，不得仅以措辞是变动为由拒绝。"
            "逐行检查事件字段是否描述一个高信息、容易回忆、以完成态表达且可核验的现实命题，并同时具备可识别的人事对象、动作和明确结果；不要求达到住院、手术或改变人生阶段，完成态不表示命主已经确认。"
            "主题名称、趋势、阶段、压力、牵扯、折腾、方向变化、泛称的事件，以及带‘可能、容易、预计’的表述均不通过。"
            "正式入职或离职、职位改变、确定或结束关系、生育、明显外伤见血或医疗处置、父母六亲具体事件、明显破财或得财可视为足够明确的高信息事件；"
            "不要要求单位名称、学校名称、搬迁地点、对象身份等输入证据无法提供的现实细节。普通计划、机会、压力和没有落地结果的过程不通过。"
            "逐行检查依据栏是否分别包含流年、大运、原局三层的具体干支、十神、宫位或作用关系，并能解释事件主题；只写层级名称或证据与事件主题无明显关联均不通过，不能要求命理证据证明尚未由现实信息确认的历史事实。"
            "同时核对干支层级：天干作用只连接天干，地支合冲刑害破只连接地支；把卯戌六合等地支关系写成直接合日干或其他天干时不通过。"
            "藏干作用必须明确写出‘某地支的藏干某天干’，不能省略藏干后把地支写成直接作用天干。"
            "工具材料中的‘岁支本乙、月支中乙、时支余癸、运支本丁’等紧凑标签，分别明确表示对应地支本气、中气、余气的藏干；此类带本、中、余标记的作用属于藏干天干作用，不得判为地支直接作用天干。"
            "工具材料只记录六合时，依据不得自行升级为合化或化出某五行。"
            "待审查材料附带的候选年份确定性事实是合化成败、受伤属性和干支关系的权威依据；其中明确记录合化成立时不得误判为模型自行升级。"
            "审查不要求反馈邀请；候选内容包含索取反馈、要求补充实际事件或下一步菜单时不通过。"
            "只输出一行 JSON：通过时输出 {\"passed\":true,\"violations\":[]}；"
            "未通过时输出 {\"passed\":false,\"violations\":[{\"event\":\"原事件字段或栏目\",\"reason\":\"不满足数量、重大性、明确结果、三层证据或无反馈邀请要求\"}]}。"
            "不得输出 Markdown、解释或修订后的事件。"
        )
        if candidate:
            parts.append(f"待审查栏目：\n{candidate}")
        return "\n\n".join(part for part in parts if part).strip() or None
    if request.request_kind == "contract_repair":
        parts.append(_CONTRACT_REPAIR_CURRENT_TURN_CONTRACT)
        parts.append(_CONTRACT_REPAIR_FINALIZATION_CONTRACT)
        if request.available_tools:
            parts.append(_CONTRACT_REPAIR_TOOL_ROUTING)
        invalid_final_text = " ".join(str(request.invalid_final_text or "").split()).strip()
        repair_instruction = (
            "上一条回复已经直接结束，但这轮仍未满足运行时合同。"
            "重新判断用户当前这句请求，保持用户明确要求的执行模式、实时性要求和绑定要求。"
            "当 prompt 已经附带可直接引用的 memory state、压缩摘要、恢复摘要或已绑定会话上下文时，优先直接利用这些现成证据修复答复。"
            "不要把读取说成写入，不要忽略摘要里的任务锚点。"
            "需要工具时，直接发起当前最合适的工具调用。"
            "只有当前请求本身已经可以直接完成时，才输出最终答复。"
            "不要重复上一条无效回复。"
        )
        if invalid_final_text:
            repair_instruction = (
                f"{repair_instruction}\n\n"
                f"上一条无效回复：{invalid_final_text}"
            )
        parts.append(repair_instruction)
        parts.append(_FINALIZATION_CONTRACT_TAIL_RULE)
        return "\n\n".join(part for part in parts if part).strip() or None
    if request.request_kind == "bazi_final_generation":
        parts.append(
            "排盘事实、大运、理论与案例检索已经完成。现在只基于工具事实生成一次最终八字分析，"
            "不要调用工具，不要复述检索过程。应期必须检查完整逐年表并选择高信号年份，"
            "经典原文、作者经验与案例证据必须区分；案例为空或相似度不足时不强行类比。"
            "严格返回 response schema 定义的 JSON 对象；各栏目字段只写正文，不写栏目标题，宿主负责渲染十一栏。"
            "全文控制在 1500 至 1900 个中文字符；每栏最多两个短段或三个短条目，"
            "同一干支关系只解释一次，其他栏目直接引用结论，不重复展开。"
            "先在 pattern_and_use 中形成唯一的旺衰、格局与喜忌结论；chart、dayun、career、marriage 和 wealth 必须沿用该结论。"
            "不得把同一五行同时写成核心喜神与忌神；存在条件差异时必须明确适用条件，不得使用‘有序即可’掩盖矛盾。"
            "合化成败、受影响五行、十神和宫位必须逐字依据工具的「合化判定」、「受影响属性」或「受伤属性」，不得自行改写成功或失败。"
            "先生成 verification_candidates：只选择逐年表中带「确定性事实」数组的高信号年份；五列及 category 映射为 relationship=婚姻恋爱、self_health=自身健康、family=父母六亲、career_change=工作变更、wealth_change=财务得失；每列只列一至两个已发生年份候选。"
            "confidence 使用0到100整数并根据原局、大运、流年三层证据评分；evidence_summary 不超过48字，discard_reason 不超过32字。"
            f"再生成 verification_events：category、year、event 必须与候选逐字一致；五列分别按可信度排序，每列选择不低于 {BAZI_VERIFICATION_CONFIDENCE_THRESHOLD} 分的最高分一至两条，不做跨栏目总排名。只有整列候选都低于阈值时才允许零条。选中候选 discard_reason 为空，未选候选写明低于阈值或同列排名较低。"
            "生成 relationship 候选时，逐一比较日支夫妻宫被流年或大运合、冲、刑、害、破、伏吟的年份，并检查同年桃花、红鸾、天喜辅助；这些关系只确定婚恋主题被引动，不确定现实方向。没有命主反馈时 event 使用“感情关系发生明显变动”，不得写成分手、恋爱确定或结婚。"
            f"若流年直接引动日支、所在大运也引动夫妻宫或财星、同年另有桃花/红鸾/天喜辅助，除非存在明确反证，该候选 confidence 不得低于 {BAZI_VERIFICATION_CONFIDENCE_THRESHOLD}。relationship 事件的 fact_ids 必须包含 natal.pillar.2，并选择同年流年和所在大运事实。"
            "无法缩小到单一高信息事实的候选应给低分并舍弃，不得用升学、单纯搬家或弱事件补足栏目。"
            "每条 event 必须包含可识别的人事对象、现实动作和已经落定的单一结果，删除程度词后仍能直接核验；"
            "event 不得使用‘或、与、和、同时、阶段、调整、变化、推进、牵扯、折腾’拼接或模糊事件；"
            "event 是一个不带句号、逗号、顿号、分号和竖线的短句，解释只写入三个 basis 字段。"
            "event 不得重复 year 字段中的年份，不得追加‘结果落定’等无信息尾语。"
            "把‘变化’换成‘更换’，或写成‘工作环境更换、方向转换、关系落实、较大支出、结果落定’等抽象概括仍不合格。"
            "verification_events.fact_ids 只选择工具「确定性事实」数组中与该事件相关的 ID，最多八个；至少包含同年流年、所在大运和原局各一个 ID。原局层不得只引用 natal.pillars，必须选择相关宫位十神或原局作用事实。"
            "若三层证据同时支持多种现实可能，必须舍弃该年份；不得把只能支持领域变化的证据升级成入学、离职、搬家、结婚等具体事实。"
            "神煞 ID 仅在同年存在且确有辅助价值时选择；没有则不选。宿主将按 ID 生成流年、大运、原局和神煞依据文字。"
            "references 只填写实际使用的准确《source_title》·heading，不添加内部 ID。"
            "生成前复核财富栏：必须使用固定 9 分多路径模型，写成‘财富结构分：X/9＝成局路径 A + 承载 B + 大运 C - 制约 D’；"
            "A 为 0-3，B 为 0-2，C 为 0-3，D 为 0-3，X 必须等于 A+B+C-D 并限制在 0-9。"
            "唯一分档固定为 0-2 分 5-15 万、3-4 分 15-30 万、5-6 分 30-60 万、7-8 分 50-100 万、9 分 80-150 万以上；"
            "写明‘命理年收入能力区间’并声明不等同现实收入。未来大运只描述上升、持平或下降，不增加第二个金额区间。"
            "未提供储蓄率、资产和负债时，不得估算净积累、净资产、总资产或现实资产等级。"
        )
        parts.append(_BAZI_ANALYSIS_OUTPUT_CONTRACT)
        if request.response_schema is None:
            parts.append(_FINALIZATION_CONTRACT_TAIL_RULE)
        return "\n\n".join(part for part in parts if part).strip() or None
    parts.append(_CURRENT_TURN_PRIORITY_CONTRACT)
    parts.append(render_finalization_contract_instruction())
    if request.available_tools and request.request_kind != "finalization_retry":
        parts.append(_GENERIC_TOOL_FINALIZATION_CONTRACT)
        parts.append(_LIVE_SOURCE_TOOL_CONTRACT)
    if request.request_kind == "subagent":
        parts.append(_SUBAGENT_TASK_CONTRACT)
    if request.request_kind == "finalization_retry":
        invalid_final_text = " ".join(str(request.invalid_final_text or "").split()).strip()
        retry_instruction = (
            "The current-turn evidence ledger already lists the required evidence for this final answer. "
            "All required evidence is already available in the prompt transcript and ledger. "
            "所需的工具结果已经全部提供在上文。"
            "直接基于现有结果生成最终答复。"
            "不要再调用任何工具。"
            "回答里要覆盖已经成功拿到且与本题相关的结果。"
            "如果这轮 prompt 里已经附带压缩摘要、恢复摘要、memory state 或已绑定上下文，"
            "优先沿用这些现成锚点与事实完成答复。"
            "如果刚才的工具调用已经漂成探索动作、目录浏览、仓库树遍历或工具盘点，"
            "不要把这些探索过程本身写成最终结果；直接回到当前消息要求的任务锚点与已知结论。"
            "如果当前消息是在压缩摘要后继续任务，最终答复优先写出压缩摘要里的任务名、对象名、未完成事项或结论锚点。"
        )
        if invalid_final_text:
            retry_instruction = (
                f"{retry_instruction}\n\n"
                f"上一条无效回复：{invalid_final_text}\n"
                "如果这条回复已经包含正确的语义内容，优先直接修正它并补齐 finalization_contract。"
            )
        parts.append(retry_instruction)
        if request.agent_id == "bazi":
            references = _bazi_reference_labels(request.tool_history)
            reference_text = "、".join(references)
            parts.append(
                "本轮是八字解读的最终生成。完整回答需要包含排盘事实、两套分析方法、"
                "主题解读、现实决策边界和参考依据。"
                "只输出普通 Markdown 正文，不要输出 feishu_card、JSON、卡片协议或工具调用标记。"
                "提交前逐项自检十一栏标题均出现且每栏都有正文。"
                + (f" 可读参考来源：{reference_text}。" if reference_text else "")
            )
    if request.agent_id == "bazi":
        parts.append(_BAZI_ANALYSIS_OUTPUT_CONTRACT)
    parts.append(_FINALIZATION_CONTRACT_TAIL_RULE)
    return "\n\n".join(part for part in parts if part).strip() or None


def _bazi_reference_labels(tool_history) -> list[str]:  # noqa: ANN001
    references: list[str] = []
    for exchange in tool_history:
        if str(exchange.tool_name or "").strip() != "knowledge":
            continue
        action = str(
            exchange.tool_payload.get("action")
            or exchange.tool_result.get("action")
            or ""
        ).strip()
        if action != "search":
            continue
        for item in exchange.tool_result.get("results") or []:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id") or "").strip()
            chunk_id = str(item.get("chunk_id") or "").strip()
            if not source_id or not chunk_id:
                continue
            title = str(item.get("source_title") or "已审核理论资料").strip()
            heading = str(item.get("heading") or "").strip()
            book = title if title.startswith("《") else f"《{title}》"
            reference = f"{book}·{heading}" if heading else book
            if reference not in references:
                references.append(reference)
    return references
