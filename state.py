from typing import TypedDict, List, Optional

class ResearchState(TypedDict):
    company: str
    api_key: str
    tavily_key: str
    
    search_plans: List[str]
    scraped_data: List[dict]
    failed_keywords: List[str]      # 记录失败关键词用于重搜策略优化
    
    report: str
    review_comment: str             # Reviewer反馈的具体缺失项，指导Planner重搜
    loop_count: int                 # 防死循环上限控制（最多2次重试）
    is_sufficient: bool
    
    current_step: str               # Streamlit实时状态追踪，避免重复渲染