# AI 公司尽调系统

基于 LangGraph 的多 Agent 协作尽调报告生成器。

## 功能
- 🤖 4个AI Agent协同工作：Planner → Researcher → Reviewer → Writer
- 🔄 自动审核重试：数据不足时自动补充搜索
- 📊 实时进度追踪：Streamlit 可视化界面
- 💰 成本控制：智能筛选高质量数据源

## 技术栈
- **框架**: LangGraph (Agent编排) + Streamlit (前端)
- **模型**: DeepSeek-V3
- **数据源**: Tavily Search API
- **部署**: Streamlit Community Cloud

## 演示
[部署后的公网链接会在这里]

## 本地运行
```bash
pip install -r requirements.txt
streamlit run app.py
```
## 架构流程图

```mermaid
graph TD
    A[用户输入公司名] --> B[Planner<br/>生成4个搜索策略]
    B --> C[Researcher<br/>并发搜索+筛选数据]
    C --> D{Reviewer<br/>审核数据质量}
    D -- 数据<3条且未重试 --> E[补充搜索策略<br/>loop_count+1]
    E --> C
    D -- 数据充足或已重试 --> F[Writer<br/>生成尽调报告]
    F --> G[输出Markdown报告]