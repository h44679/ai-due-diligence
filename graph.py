from langgraph.graph import StateGraph, END
from typing import TypedDict, List

class ResearchState(TypedDict):
    company: str
    api_key: str
    tavily_key: str
    search_plans: List[str]
    scraped_data: List[dict]
    failed_keywords: List[str]
    report: str
    review_comment: str
    loop_count: int
    is_sufficient: bool
    current_step: str
    total_data_found: int
    error: str

from nodes import planner_node, researcher_node, reviewer_node, writer_node

def create_workflow():
    workflow = StateGraph(ResearchState)
    
    workflow.add_node("planner", planner_node)
    workflow.add_node("researcher", researcher_node)
    workflow.add_node("reviewer", reviewer_node)
    workflow.add_node("writer", writer_node)
    
    workflow.set_entry_point("planner")
    
    def check_error(state: ResearchState):
        # API认证失败等致命错误直接进入writer生成错误报告，避免无意义的搜索重试浪费Token
        if state.get('error'):
            return "writer"
        return "researcher"
    
    workflow.add_conditional_edges("planner", check_error, {"researcher": "researcher", "writer": "writer"})
    workflow.add_edge("researcher", "reviewer")
    
    def decide_next(state: ResearchState):
        if state.get('error'):
            return "writer"
        if state.get('is_sufficient'):
            return "writer"
        # 最多2次重试防止无限循环消耗API额度，优先保证有结果而非完美结果
        if state.get('loop_count', 0) >= 2:
            return "writer"
        # 数据不足时回到planner生成补充搜索策略（如从general改为specific数据源）
        return "planner"
    
    workflow.add_conditional_edges("reviewer", decide_next, {"writer": "writer", "planner": "planner"})
    workflow.add_edge("writer", END)
    
    return workflow.compile()

app = create_workflow()

if __name__ == "__main__":
    print("Graph 创建成功")