# DECISIONS

- [MVP-1] 瓦片 64×64，TILE_SIZE=32px —— 足够大以容纳后续单位/建筑格子，又小到测试全网格便宜
- [MVP-1] 程序化生成默认地图，确定性 seed —— 测试可断言具体坐标内容，不依赖随机
- [MVP-1] 四个象限各放矿点 —— 让玩家和 AI 都有可采矿源，避免开局卡死
- [MVP-1] 边缘滚动触发范围 8px、最大速度 12px/帧 —— 红警式手感，太快会晕
- [MVP-1] 缩放范围 0.5~2.0，滚轮每格 ±0.1，鼠标锚点居中 —— 既能纵览也能聚焦
- [MVP-1] 逻辑层（tilemap/camera/world）零 pygame 依赖 —— 加快纯逻辑测试，无需 dummy SDL
- [MVP-1] 渲染层隔离在 engine/render.py —— 是唯一强制依赖 pygame 的模块
- [MVP-1] 主菜单放最小可工作版本（play/quit）占位 —— 留给 MVP-10 完善，避免阻塞主循环启动
- [MVP-2] 全部建筑统一 2×2 占地 —— 简化 placement/overlap/AI 寻路测试，后续可对大建筑扩 footprint
- [MVP-2] 电厂 net +80，其他建筑均 consume —— 单一电厂就能给整套初始经济供电，测试易断言 OK/LOW 切换
- [MVP-2] 建造成本入队时一次扣光（不退款）—— 最简单模型，避开 partial-state cancel 带来的边角
- [MVP-2] 建造厂初始建筑（5,5）开局由 World.new_default 直接 place，不进队列 —— 与「先有基地才能造东西」一致
- [MVP-2] 建造厂入队后用 spiral-scan 自动找最近可建点 —— MVP-2 不引入 drone-deploy，AI 让用户能直接看到成果
- [MVP-2] 战车工厂前置于矿场（prerequisite）—— 引入简单的产业链，后续 AI 可用同一规则
- [MVP-2] 建造队列上限 5 —— 防 runaway 测试 / 防止玩家 enqueue 整个战局
- [MVP-2] 电力不足时整个生产停顿（不区分 per-building） —— 经典红警简化；per-building 走 per-tile 网格是 future work
