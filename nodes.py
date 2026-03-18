import streamlit as st
from openai import OpenAI
import re
import time
from typing import List, Dict, Any

try:
    from main import get_search_plan
    from researcher import search_and_extract, APIError
except ImportError as e:
    print(f"警告: 导入失败 {e}")
    def get_search_plan(c, client=None): 
        return {"search_plans": [f"{c} CEO", f"{c} funding", f"{c} business model"]}
    def search_and_extract(kw, **kwargs): 
        return []

def get_ui_container(key):
    return st.session_state.get('ui_containers', {}).get(key)

def select_best_data(scraped_data: List[Dict], max_items: int = 5) -> List[Dict]:
    """
    质量优先的数据筛选策略。
    
    不同爬虫工具可靠性差异大：Trafilatura提取正文最干净，
    BS4可能带导航栏杂质，Snippet可能只有摘要。
    按来源质量加权，同类最多取3条避免单一来源垄断，
    同时放宽到3条确保能凑够5条（避免Reviewer死循环）。
    """
    if not scraped_data:
        return []
    
    priority = {
        "trafilatura": 3, 
        "bs4": 2, 
        "snippet_fallback": 1,
        "snippet_timeout": 1,
        "snippet_request_failed": 1,
        "snippet_skip_video": 0,
        "snippet_http_403": 0,
        "snippet_http_500": 0
    }
    
    sorted_data = sorted(
        scraped_data,
        key=lambda x: (priority.get(x.get('fallback_level', ''), 0), 
                      len(x.get('content', ''))),
        reverse=True
    )
    
    type_count = {"trafilatura": 0, "bs4": 0, "snippet": 0}
    selected = []
    
    for item in sorted_data:
        level = item.get('fallback_level', 'snippet_fallback')
        if level == "trafilatura":
            cat = "trafilatura"
        elif level == "bs4":
            cat = "bs4"
        else:
            cat = "snippet"
            
        if type_count[cat] < 3 and len(selected) < max_items:
            selected.append(item)
            type_count[cat] += 1
    
    print(f"数据筛选: 原始{len(scraped_data)}条 → 精选{len(selected)}条 "
          f"(🟢{type_count['trafilatura']} 🟡{type_count['bs4']} 🔴{type_count['snippet']})")
    return selected

def planner_node(state: Dict):
    """规划节点 - 限制4个关键词"""
    status = get_ui_container('status')
    progress = get_ui_container('progress')
    
    if status:
        status.markdown("""
            <div class="status-card">
                <div style="color:#38bdf8;font-weight:600;font-size:1.2rem;">🧠 PLANNER 节点</div>
                <div style="color:#e2e8f0;margin-top:0.5rem;">正在生成搜索策略...</div>
            </div>
        """, unsafe_allow_html=True)
    if progress:
        progress.progress(0.15)
    
    try:
        client = OpenAI(api_key=state['api_key'], base_url="https://api.siliconflow.cn/v1", timeout=10.0)
        plans = get_search_plan(state['company'], client=client)
        search_plans = plans.get("search_plans", [])
        
        if len(search_plans) > 4:
            search_plans = search_plans[:4]
        
        if not search_plans:
            search_plans = [f"{state['company']} CEO", f"{state['company']} funding", 
                          f"{state['company']} business", f"{state['company']} market"]
        
        return {
            "search_plans": search_plans,
            "current_step": f"🧠 Planner: 生成 {len(search_plans)} 个策略",
            "error": None
        }
    except Exception as e:
        return {
            "search_plans": [f"{state['company']} CEO", f"{state['company']} funding", 
                          f"{state['company']} business", f"{state['company']} market"],
            "current_step": f"规划失败，使用默认策略",
            "error": None
        }

def search_single_node(state: Dict, idx: int):
    """
    搜索第idx个关键词。
    
    拆成4个独立节点是为了让LangGraph每搜完一个就yield一次，
    避免15秒阻塞导致前端卡在Planner界面不动。
    """
    if state.get('error'):
        return {"scraped_data": state.get('scraped_data', []), "current_step": f"跳过搜索{idx+1}"}
    
    status = get_ui_container('status')
    details = get_ui_container('details')
    
    keywords = state.get('search_plans', [])
    
    if idx >= len(keywords):
        return {
            "current_step": f"搜索({idx+1}/4): 无关键词",
            "total_data_found": len(state.get('scraped_data', []))
        }
    
    kw = keywords[idx]
    # 累加之前的数据，重试时必须保留旧数据才能凑够5条
    existing_data = state.get('scraped_data', [])
    all_data = existing_data.copy()
    
    # 立即显示当前正在搜索哪个（完整关键词，用户体验要求无截断）
    if status:
        status.markdown(f"""
            <div class="status-card">
                <div style="color:#38bdf8;font-weight:600;font-size:1.2rem;">🔍 RESEARCHER 节点 ({idx+1}/4)</div>
                <div style="color:#fbbf24;font-size:1.1rem;margin-top:8px;font-family:monospace;">
                    ▶ {kw}
                </div>
                <div style="color:#94a3b8;font-size:0.85rem;margin-top:5px;">
                    历史数据: {len(existing_data)} 条 | 搜索中...
                </div>
            </div>
        """, unsafe_allow_html=True)
    
    print(f"  [{idx+1}/4] 搜索: {kw}")
    
    try:
        data = search_and_extract([kw], max_results_per_kw=2, api_key=state.get('tavily_key'))
        all_data.extend(data)
        
        if details:
            with details:
                st.markdown(f"<div class='agent-log'>✓ [{idx+1}/4] {kw}: {len(data)}条</div>", unsafe_allow_html=True)
        
        # Tavily免费版有RPM限制，0.5秒缓冲避免触发429限流
        time.sleep(0.5)
        
        return {
            "scraped_data": all_data,
            "current_step": f"搜索({idx+1}/4): {kw}... 找到{len(data)}条",
            "total_data_found": len(all_data)
        }
        
    except Exception as e:
        print(f"    ✗ {kw}: 失败")
        if details:
            with details:
                st.markdown(f"<div class='agent-log'>✗ [{idx+1}/4] {kw}: 失败</div>", unsafe_allow_html=True)
        
        return {
            "scraped_data": all_data,
            "current_step": f"搜索({idx+1}/4): {kw}... 失败",
            "total_data_found": len(all_data),
            "error": None
        }

def reviewer_node(state: Dict):
    """审核节点"""
    status = get_ui_container('status')
    progress = get_ui_container('progress')
    
    if progress:
        progress.progress(0.75)
    
    data = state.get('scraped_data', [])
    loop = state.get('loop_count', 0)
    
    print(f"  检查: {len(data)}条数据, 第{loop}次循环")
    
    if len(data) == 0:
        if loop >= 1:
            if status:
                status.markdown("""<div class="status-card" style="border-color:#f87171;">
                    <div style="color:#f87171;font-weight:600;">👀 Reviewer: ❌ 无可用数据</div>
                </div>""", unsafe_allow_html=True)
            return {"is_sufficient": False, "loop_count": loop, "current_step": "无数据，强制结束", 
                   "total_data_found": 0, "error": "未找到数据"}
        else:
            return {"is_sufficient": False, "loop_count": loop + 1, "current_step": "补充搜索",
                   "total_data_found": 0, "search_plans": [f"{state['company']} detailed info"]}
    
    if len(data) < 5 and loop < 2:
        if status:
            status.markdown(f"""<div class="status-card" style="border-color:#fbbf24;">
                <div style="color:#fbbf24;font-weight:600;">👀 Reviewer: 数据不足({len(data)}条<5条)，第{loop+1}次重试</div>
            </div>""", unsafe_allow_html=True)
        return {
            "is_sufficient": False,
            "loop_count": loop + 1,
            "current_step": f"数据不足({len(data)}条)，第{loop+1}次重试",
            "total_data_found": len(data),
            "search_plans": [f"{state['company']} financial report", f"{state['company']} SEC filing"]
        }
    
    if status:
        status.markdown("""<div class="status-card" style="border-color:#4ade80;">
            <div style="color:#4ade80;font-weight:600;">👀 Reviewer: ✅ 审核通过</div>
        </div>""", unsafe_allow_html=True)
    
    return {
        "is_sufficient": True,
        "loop_count": loop,
        "current_step": "审核通过 → Writer开始生成",
        "total_data_found": len(data)
    }

def writer_node(state: Dict):
    """写作节点"""
    status = get_ui_container('status')
    progress = get_ui_container('progress')
    report_container = get_ui_container('report')
    
    if progress:
        progress.progress(0.9)
    
    if state.get('error'):
        return {"report": f"## 错误\n{state['error']}", "current_step": "生成错误报告"}
    
    data = state.get('scraped_data', [])
    if not data:
        return {"report": "## 数据不足", "current_step": "Writer: 无数据"}
    
    data_summary = []
    for item in data[:3]:
        content = item.get('content', '')[:250]
        keyword = item.get('keyword', 'unknown')
        data_summary.append(f"[{keyword}]: {content}")
    
    prompt = f"""基于以下数据生成"{state['company']}"尽调报告：
{chr(10).join(data_summary)}

要求：1.Markdown格式 2.包含概况/团队/融资/商业模式/风险 3.简洁500字"""

    try:
        client = OpenAI(api_key=state['api_key'], base_url="https://api.siliconflow.cn/v1", timeout=180.0)
        
        if status:
            status.markdown("""<div class="status-card">
                <div style="color:#38bdf8;font-weight:600;">✍️ Writer: 正在生成报告...</div>
            </div>""", unsafe_allow_html=True)
        
        response = client.chat.completions.create(
            model="Pro/deepseek-ai/DeepSeek-V3",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1200,
            stream=False
        )
        
        full_report = response.choices[0].message.content
        # 清理可能的代码块标记，保证纯Markdown输出
        full_report = re.sub(r'^```markdown\s*', '', full_report)
        full_report = re.sub(r'^```\s*', '', full_report)
        full_report = re.sub(r'\s*```$', '', full_report)
        
        if report_container:
            report_container.markdown(f"<div class='report-card'>{full_report}</div>", unsafe_allow_html=True)
        
        return {"report": full_report, "current_step": "✍️ Writer: 完成"}
        
    except Exception as e:
        return {"report": f"生成失败: {e}", "current_step": f"Writer错误"}