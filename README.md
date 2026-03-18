# AI 公司尽调系统

基于 LangGraph 的多 Agent 协作尽调报告生成器。

## 功能
- 🤖 4个AI Agent协同工作：Planner → Researcher → Reviewer → Writer
- 🔍 细粒度搜索进度：4个关键词分步执行，实时展示当前搜索项（避免长时间无响应）
- 🔄 自动审核重试：数据不足(&lt;5条)时自动补充搜索，最多重试2次
- 📊 实时进度追踪：Streamlit 可视化界面，节点级进度显示
- 💰 成本控制：智能筛选高质量数据源（Trafilatura全文优先）

## 技术栈
- **框架**: LangGraph (Agent编排) + Streamlit (前端)
- **模型**: DeepSeek-V3 (通过SiliconFlow API)
- **数据源**: Tavily Search API + 网页提取(Trafilatura/BS4)
- **部署**: Streamlit Community Cloud

## 演示
🔗 **在线体验**: https://ai-due-diligence-8bybyhfcubb9easfrjyjut.streamlit.app/

## 本地运行
```bash
pip install -r requirements.txt
streamlit run app.py
```

## 架构流程图

```mermaid
graph TD
    A[用户输入公司名] --> B[Planner<br/>生成4个搜索策略]
    B --> C1[Search_1<br/>搜索关键词1]
    C1 --> C2[Search_2<br/>搜索关键词2]
    C2 --> C3[Search_3<br/>搜索关键词3]
    C3 --> C4[Search_4<br/>搜索关键词4]
    C4 --> D{Reviewer<br/>审核数据质量<br/>累计>=5条?}
    D -- 数据<5条且未重试 --> E[补充搜索策略<br/>loop_count+1]
    E --> B
    D -- 数据>=5条或已重试 --> F[Writer<br/>生成尽调报告]
    F --> G[输出Markdown报告]