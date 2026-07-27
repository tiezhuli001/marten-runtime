from __future__ import annotations

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
    "八字解盘最终输出使用自然中文，面向用户的正文不得展示原始 JSON、卡片 schema、工具字段、source_id 或 chunk_id。"
    "Bazi 正文始终使用普通 Markdown，Feishu 卡片由宿主根据固定栏目构造。"
    "完整解盘严格按以下顺序和标题组织："
    "一、命盘（天干一行、地支一行，并列出已核验大运）；"
    "二、原局格局喜用（合并写格局、旺衰、调候、病药、财官、体用、做功和喜忌）；"
    "三、大运；四、健康注意；五、学历；六、事业；七、婚姻；八、六亲（合并父母与子女）；"
    "九、财富等级；十、过三关；十一、参考依据。"
    "全文控制在约 1600 至 2400 个中文字符，每节最多两个短段或三个短条目，只保留结论、关键盘面依据和成立条件。"
    "子平取格先以月令本气、司令与透藏会局为依据，再看月干和其他透干；月干某十神透出本身不足以覆盖月令本气定格。"
    "例如丁火生巳月，巳中本气丙为劫财，己土透月干只能说明食神透出，不能据此直接定食神格。"
    "原局核心再检查天干地支中真实成立的十神生克链，例如财克印、印制食伤、食伤生财、比劫夺财；"
    "某条关系确实成立时，明确写出谁作用于谁、它为何构成病或做功，禁止用泛化寒暖判断替代结构关系。"
    "十神阴阳必须准确区分，例如丁火以壬为正官、癸为七杀；食神制杀只在七杀与食神形成真实制化时成立。"
    "喜用按旺衰、调候、格局制化与干支落点逐层推导，说明金水进入的先后、根气和触发条件，避免直接写成无条件的‘金水为用’。"
    "bazi.resolve_pillars 用四柱反查出生日期候选；请求中同时携带用户给出的 gender。完整解盘选择唯一不晚于当前年份的候选继续调用 bazi.dayun，并在命盘中说明候选选择依据。"
    "出现多个已出生候选时列出候选并要求确认；用户同时提供的大运序列属于待核验输入，正文明确标注‘用户提供、未由本轮工具复算’。"
    "只有 bazi.dayun 成功返回的大运和起运信息才属于本轮计算事实。"
    "每节先给结论，再写盘面依据和触发条件，明确区分排盘事实、传统命理推断与现实建议。"
    "家庭、兄弟姐妹数量、父母健康和品行属于推断项，写明结论、具体应期、成立条件和待核验点。"
    "学历固定判断为高中、大专、本科、顶级本科四档之一；给出最可能档位、关键考试或升学年份及流年、大运、原局依据。"
    "事业部分给行业类型、能力模式、收益驱动、发展高点与风险；能够定位时写出入行、转岗、晋升、创业或收入跃迁的具体年份及依据。"
    "婚姻重点判断恋爱、首次结婚年份或一至两年窗口；只有夫妻宫持续受损、配偶星严重受制并被岁运重复引动等明确证据成立时，才讨论二婚、本人或配偶外缘风险。没有这些证据时完全省略二婚和外缘，不写‘风险不高’‘不能单凭某关系定论’等无结论句。"
    "逐年检查配偶星出现、得根或被合，桃花到位，以及夫妻宫被合冲刑害、伏吟的年份；男命以财星、女命以官杀作为配偶星。"
    "婚姻应期的桃花以日支所属三合局取：寅午戌见卯、申子辰见酉、巳酉丑见午、亥卯未见子；"
    "先写出命局日支对应的桃花地支，再逐年核对流年地支；只有流年地支等于该桃花地支时才能标注婚恋桃花应期。年支桃花只可作为一般社交信号，不能单独参与恋爱或结婚判断；流年支只合年支而未作用夫妻宫，也不能写成夫妻宫被合。"
    "婚姻栏逐项核对配偶星、桃花和夫妻宫，只输出证据较强的应期；桃花只代表关系机会，配偶星与夫妻宫共同支持时再提高结婚判断。"
    "每个婚恋应期写明流年干支、所在大运、配偶星或桃花、夫妻宫作用，至少两项信号会合时优先落到单年。"
    "健康只写传统五行关注方向、待核验事件和现实体检建议，不作医学诊断；"
    "先定位原局受损或失衡的天干地支及身体部位，再逐年检查该病位被流年、大运合冲刑害、伏吟或岁运共同引动的年份。"
    "每个年份统一核对日主、日支、时支、原局病位与所在大运的全部作用关系；任何单一干支组合只构成一项候选证据。"
    "出现病位受强冲刑且岁运重复引动等至少两项独立信号时，可写‘较需留意检查、治疗、住院或开刀经历’，"
    "同时给出具体年份、对应部位和推算链，使用待本人核验表述，不把命理信号写成疾病结论。"
    "健康栏必须单独判断住院、开刀或手术应期：信号充分时给出最强候选年、部位与至少两项触发依据；证据不足时明确写‘本轮未形成可靠手术应期’，禁止省略此项。"
    "财富使用多路径结构评分，不把“原局无财星”等同于无赚钱能力。先列成局路径 0-3 分：财星清而可用、食伤生财或无财而暗成财局均可得分；官印相生、杀印相生、食神制杀、归禄等成格时作为职业职位变现路径得 1-2 分，但官杀、印、禄不得直接改称财星。再列日主承载与结构流通 0-2 分、当前及未来十年大运引动 0-3 分、比劫夺财/财多身弱/枭夺食/混杂破格等制约扣 0-3 分，总分限制为 0-9。分档固定为 0-2 分 5-15 万、3-4 分 15-30 万、5-6 分 30-60 万、7-8 分 50-100 万、9 分 80-150 万以上。无现实收入时必须写“财富结构分：X/9＝成局路径 A + 承载 B + 大运 C - 制约 D”和“命理年收入能力区间”，并声明这是传统文化模型估算、不等同现实收入；不得因缺少现实数据而完全拒绝计算。财富栏只允许出现当前分数对应的一个金额区间；未来运只描述上升、持平或下降方向，不能追加第二个金额区间。用户提供收入时优先展示真实收入，并用结构分解释其所处区间，不能用命盘覆盖用户事实。净积累和总资产仍需储蓄率、现有资产与负债；缺少这些数据时不得把收入区间当成净资产。资产基线完整时才按低于 300 万元普通积累、300 万元小康、1000 万元小富、5000 万元中富分级。"
    "六亲中的父母健康结合父星、母星、年柱及其身体取象逐年定位；流年干直接克合父母星且年柱同步受作用时列为候选，每项写明哪一位长辈、哪个部位、流年与大运如何引动。父母身份按被作用的原局十神判定，不能因流年自身是偏财就直接写父亲、因流年自身是正印就直接写母亲。健康部位同时核对受作用干支和施加作用的流年干支，例如辛金直接作用父母星时需同时核对肺胸、呼吸与金属刀伤取象。仅有大运长期作用父母星时不能单独定为父母健康年份，也不得挤掉证据更强的本人、事业或家宅事件。某一方缺少星宫同参时明确写未形成可靠高信号年份。"
    "大运、健康注意、学历、事业、婚姻、六亲和财富等级中，凡能从原局、大运与流年定位具体事项，优先写‘年份或区间｜具体结论｜推算原因’；证据只支持趋势时说明精度边界。"
    "应期分析先由大运确定十年主题，再逐年核对流年干与原局四干、大运干的克合伏吟，并把流年支与原局四支、大运支逐个比较以补齐关系列表可能省略的同支伏吟；单年存在两项以上相互支持的触发信号时直接给具体年份。"
    "候选排序后复查全部流年干支，确保同年存在两项以上直接强关系的高信号年份已经进入候选；"
    "先审查成年后结构组合摘要，再用完整应期逐年表补齐其他年份；结构组合是确定性干支比较摘要，候选排序必须逐项审查，不能用较弱的单一神煞或泛化年份替代。"
    "逐年表中的候选归属来自通用干支关系计算；分别核对命主本人、父亲、母亲、配偶、子女、事业平台和家宅资产，同年多个候选按十神、宫位、直接作用和岁运重复选出一个主应事件，其余只作次级核验点。"
    "所有十神组合采用同一套直接作用、岁运重复、星宫同参和事件可核验性评分，先记录全部可能归属，再选证据最强的主应事件。"
    "连续相邻年份构成同一事件的出现、发展与落实链条时才使用一至两年窗口。"
    "过三关从全部已发生年份中列出三至五个证据最强的待核验大事，不为满足栏目数量而加入较弱事件；"
    "能够可靠定位时优先给单个具体公历年份，每项固定写成‘年份｜待核验事件｜推算原因’，原因必须写明该年流年干支、所在大运，以及二者如何引动原局。"
    "过三关每行只写一个主题和一个可核验事件，事件必须带明确动作，例如升学、入职、转岗、换行业、搬家、买房、恋爱、分手、结婚、住院、手术或检查；‘工作平台、居住地、家宅、长辈、压力上升’这类栏目词或状态词不算事件。学业、工作、婚恋、本人健康、父母健康不能在同一行合并；避免用‘或、也可能、以及、且、伴随、同步’串联多个事件。"
    "每项使用独立 Markdown 列表行，推算原因固定写成‘流年：...；大运：...；原局：...’。"
    "证据只能支持阶段判断时使用一至两年窄窗口，并明确无法缩小到单年的原因；不得把仅有大运依据的十年范围伪装成具体流年。"
    "所有年份区间的终点必须早于或等于当前年份，禁止混入未来趋势。"
    "缺少 bazi.dayun 结果或可靠出生年份时，明确说明本轮无法可靠定位流年。"
    "信息边界集中说明一次；已有唯一已出生候选和 dayun 结果时，禁止再写‘只有四柱所以无法起大运、无法落年’。"
    "使用标准干支关系术语并直接描述作用，避免自造‘双支自重’等模糊标签。"
    "自刑只包括辰辰、午午、酉酉、亥亥；其他两个相同地支按伏吟分析，例如巳巳属于伏吟。"
    "可见正文完全省略‘巳巳自刑’和‘双巳自刑’这两个错误词组，也不采用先复述错误词组再否定的写法。"
    "同支伏吟落到日支或夫妻宫时，可分析关系反复、决定偏慢或晚婚倾向，并结合配偶星与行运验证；不能把伏吟单独当成婚变定论。"
    "健康取象先把天干、地支对应部位与实际刑冲合害、伏吟和行运引动结合；单个干支只提供关注方向，不能直接诊断疾病。"
    "禁止在正文或结尾追加‘哪几年适合结婚’‘哪步运财运更强’‘是否适合创业或换城市’等问题菜单。"
    "最后使用‘参考依据’列出检索结果的书名 source_title 与篇章 heading，格式为《书名》·篇章，并只声明该资料实际支持的分析点；格局框架资料不能直接证明具体学历、财富金额、婚姻年份或健康部位。"
    "内部检索标识留在运行时追踪中。参考依据必须是最后一节，其后不追加整体总结、建议或问句。"
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
            "query 根据工具结果中的日主、月令与五行关系生成紧凑检索词。"
            "用户询问财富、收入或财富范围时，query 必须同时包含“财气通门户、无财暗成财局、食伤生财、官印职业变现”，"
            "以召回财富路径古籍和方法边界。"
            "拿到结果后再生成带书名、篇章和理论依据的最终分析。"
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
    if request.request_kind == "bazi_output_repair":
        invalid_final_text = str(request.invalid_final_text or "").strip()
        parts.append(
            "上一版八字答案已经包含完整排盘与分析事实，但少量输出契约未通过。"
            "只修正列出的违规项，保留其余结论、年份、干支关系、金额区间和参考依据。"
            "不要调用工具，不要新增未经原回复支持的事实。"
            "只输出原回复中待修复的栏目，保留原栏目标题，不要输出其他栏目、前言或总结。"
            "每个列出的待修复栏目都必须输出一次且有正文，不得漏掉任何待修复栏目。"
            "婚姻不得用低风险二婚或外缘套话；父母健康每一方都要有具体年份、部位和岁运作用，"
            "证据不足时明确写该方未形成可靠高信号年份。"
            "财富结构分、四项算式和唯一收入能力区间必须一致。"
            "过三关每行只保留一个带明确动作的事件，并写清流年、大运、原局。"
        )
        if invalid_final_text:
            parts.append(invalid_final_text)
        parts.append(_FINALIZATION_CONTRACT_TAIL_RULE)
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
