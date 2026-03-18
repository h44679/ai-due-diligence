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

from nodes import (
    planner_node, 
    search_single_node,
    reviewer_node, 
    writer_node
)

def create_workflow():
    workflow = StateGraph(ResearchState)
    
    workflow.add_node("planner", planner_node)
    
    # 拆成4个独立搜索节点，每搜完一个就yield一次，避免15秒阻塞导致UI卡死
    workflow.add_node("search_1", lambda state: search_single_node(state, 0))
    workflow.add_node("search_2", lambda state: search_single_node(state, 1))
    workflow.add_node("search_3", lambda state: search_single_node(state, 2))
    workflow.add_node("search_4", lambda state: search_single_node(state, 3))
    
    workflow.add_node("reviewer", reviewer_node)
    workflow.add_node("writer", writer_node)
    
    workflow.set_entry_point("planner")
    
    def check_error(state: ResearchState):
        if state.get('error'):
            return "writer"
        return "search_1"
    
    workflow.add_conditional_edges("planner", check_error, {"search_1": "search_1", "writer": "writer"})
    
    # 串联搜索节点：搜完一个立即显示，再搜下一个，保证用户能看到进度递进
    workflow.add_edge("search_1", "search_2")
    workflow.add_edge("search_2", "search_3")
    workflow.add_edge("search_3", "search_4")
    workflow.add_edge("search_4", "reviewer")
    
    def decide_next(state: ResearchState):
        if state.get('error'):
            return "writer"
        if state.get('is_sufficient'):
            return "writer"
        # 最多2次重试防止无限循环消耗API额度，优先保证有结果而非完美结果
        if state.get('loop_count', 0) >= 2:
            return "writer"
        return "planner"
    
    workflow.add_conditional_edges("reviewer", decide_next, {"writer": "writer", "planner": "planner"})
    workflow.add_edge("writer", END)
    
    return workflow.compile()

app = create_workflow()