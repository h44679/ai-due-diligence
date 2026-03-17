import streamlit as st
from openai import OpenAI
import re
import time
import concurrent.futures
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
    按来源质量加权，同类最多取2条避免单一来源垄断。
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
            
        if type_count[cat] < 2 and len(selected) < max_items:
            selected.append(item)
            type_count[cat] += 1
    
    print(f"数据筛选: 原始{len(scraped_data)}条 → 精选{len(selected)}条 "
          f"(🟢{type_count['trafilatura']} 🟡{type_count['bs4']} 🔴{type_count['snippet']})")
    return selected

def planner_node(state: Dict):
    """生成4个搜索关键词，超限时截断以控制成本。"""
    status = get_ui_container('status')
    progress = get_ui_container('progress')
    
    if status:
        status.markdown("""
            <div class="status-card">
                <div style="color:#38bdf8;font-weight:600;">🧠 Planner: 正在规划...</div>
            </div>
        """, unsafe_allow_html=True)
    if progress:
        progress.progress(0.15)
    
    try:
        # SiliconFlow代理需要显式timeout避免默认30秒卡死
        client = OpenAI(
            api_key=state['api_key'], 
            base_url="https://api.siliconflow.cn/v1", 
            timeout=10.0
        )
        plans = get_search_plan(state['company'], client=client)
        search_plans = plans.get("search_plans", [])
        
        # 模型可能返回超过4个，截断以控制API调用成本
        if len(search_plans) > 4:
            search_plans = search_plans[:4]
        
        if not search_plans:
            search_plans = [
                f"{state['company']} CEO founder",
                f"{state['company']} funding history", 
                f"{state['company']} business model",
                f"{state['company']} competitors"
            ]
        
        return {
            "search_plans": search_plans,
            "current_step": f"🧠 Planner: 生成 {len(search_plans)} 个策略",
            "error": None
        }
    except Exception as e:
        return {
            "search_plans": [
                f"{state['company']} CEO", 
                f"{state['company']} funding", 
                f"{state['company']} business", 
                f"{state['company']} market"
            ],
            "current_step": f"规划失败，使用默认策略",
            "error": None
        }

def researcher_node(state: Dict):
    """并发搜索，控制速率避免触发Tavily限流。"""
    if state.get('error'):
        return {"scraped_data": [], "current_step": "跳过 Researcher"}
    
    status = get_ui_container('status')
    progress = get_ui_container('progress')
    details = get_ui_container('details')
    
    keywords = state.get('search_plans', [])
    if not keywords:
        return {"scraped_data": [], "current_step": "无关键词"}
    
    # Tavily免费版有 RPM (Requests Per Minute) 限制，超过4个关键词可能触发429
    if len(keywords) > 4:
        keywords = keywords[:4]
        print(f"  限制关键词数量: 4个")
    
    print(f"  搜索 {len(keywords)} 个关键词")
    all_data = []
    completed = 0
    
    def search_single(kw):
        try:
            # max_results_per_kw=2平衡覆盖率与成本（每个关键词1-2条足够尽调概要）
            data = search_and_extract([kw], max_results_per_kw=2, api_key=state.get('tavily_key'))
            # Tavily API有速率限制，0.5秒缓冲避免触发限流
            time.sleep(0.5)
            return {"kw": kw, "data": data, "error": None}
        except Exception as e:
            return {"kw": kw, "data": [], "error": str(e)}
    
    # max_workers=2平衡并发速度与API限流阈值
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(search_single, kw): kw for kw in keywords}
        
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            completed += 1
            
            if progress:
                progress.progress(0.15 + completed / len(keywords) * 0.45)
            
            if result["error"]:
                print(f"    ✗ {result['kw'][:20]}: 失败")
            else:
                all_data.extend(result["data"])
                print(f"    ✓ {result['kw'][:20]}: {len(result['data'])}条")
                
                if details and result["data"]:
                    with details:
                        st.markdown(f"<div class='agent-log'>✓ {result['kw'][:30]}: {len(result['data'])}条</div>", 
                                  unsafe_allow_html=True)
            
            if status:
                status.markdown(f"""
                    <div class="status-card">
                        <div style="color:#38bdf8;font-weight:600;">🔍 Researcher: {completed}/{len(keywords)}完成</div>
                        <div style="color:#94a3b8;font-size:0.85rem;">已收集 {len(all_data)} 条数据</div>
                    </div>
                """, unsafe_allow_html=True)
    
    selected_data = select_best_data(all_data, max_items=5)
    
    if progress:
        progress.progress(0.6)
    
    return {
        "scraped_data": selected_data,
        "current_step": f"🔍 Researcher: 找到 {len(all_data)} 条，精选 {len(selected_data)} 条",
        "total_data_found": len(selected_data),
        "error": None
    }

def reviewer_node(state: Dict):
    """
    审核数据质量，决定进入Writer或重试。
    
    重试策略优先级：
    1. 完全无数据且已重试过 -> 终止（避免无限循环）
    2. 数据不足(<5条)且未超2次重试 -> 补充专业数据源（如SEC filing）
    3. 数据充足或已尽力 -> 通过
    """
    print("👀 Reviewer 节点开始...")
    
    if state.get('error'):
        return {"is_sufficient": True, "current_step": "跳过审核"}
    
    status = get_ui_container('status')
    progress = get_ui_container('progress')
    
    if progress:
        progress.progress(0.7)
    
    data = state.get('scraped_data', [])
    loop = state.get('loop_count', 0)
    
    print(f"  检查: {len(data)}条数据, 第{loop}次循环")
    
    # 终止条件：完全无数据且已重试过一次，避免死循环浪费Token
    if len(data) == 0:
        if loop >= 1:
            if status:
                status.markdown("""
                    <div class="status-card" style="border-color:#f87171;">
                        <div style="color:#f87171;font-weight:600;">👀 Reviewer: ❌ 无可用数据</div>
                    </div>
                """, unsafe_allow_html=True)
            return {
                "is_sufficient": False,
                "loop_count": loop,
                "current_step": "👀 Reviewer: 无数据，强制结束",
                "error": "未找到数据"
            }
        else:
            if status:
                status.markdown("""
                    <div class="status-card" style="border-color:#fbbf24;">
                        <div style="color:#fbbf24;font-weight:600;">👀 Reviewer: 未找到数据，补充搜索...</div>
                    </div>
                """, unsafe_allow_html=True)
            return {
                "is_sufficient": False,
                "loop_count": loop + 1,
                "current_step": "👀 Reviewer: 补充搜索",
                "search_plans": [f"{state['company']} detailed information", 
                               f"{state['company']} company profile"]
            }
    
    # 质量门槛：少于5条视为不足以生成可靠尽调报告，触发深度搜索
    if len(data) < 5 and loop < 2:
        print(f"  触发重试: {len(data)}条 < 5条, 第{loop}次循环")
        if status:
            status.markdown(f"""
                <div class="status-card" style="border-color:#fbbf24;">
                    <div style="color:#fbbf24;font-weight:600;">👀 Reviewer: 数据不足({len(data)}条<5条)，第{loop+1}次重试</div>
                </div>
            """, unsafe_allow_html=True)
        # 补充专业数据源提高信息密度
        return {
            "is_sufficient": False,
            "loop_count": loop + 1,
            "current_step": f"👀 Reviewer: 数据不足({len(data)}条)，第{loop+1}次重试",
            "search_plans": [f"{state['company']} financial report detailed", 
                           f"{state['company']} annual report SEC filing"]
        }
    
    # 通过条件：数据充足或已重试2次达到尽力而为标准
    if status:
        status.markdown("""
            <div class="status-card" style="border-color:#4ade80;">
                <div style="color:#4ade80;font-weight:600;">👀 Reviewer: ✅ 审核通过</div>
                <div style="color:#38bdf8;font-size:0.9rem;margin-top:5px;">✍️ Writer 节点开始...</div>
            </div>
        """, unsafe_allow_html=True)
    
    return {
        "is_sufficient": True,
        "loop_count": loop,
        "current_step": "👀 Reviewer: 审核通过 → ✍️ Writer 开始生成"
    }

def writer_node(state: Dict):
    """生成尽调报告，使用非流式避免Streamlit长连接超时。"""
    print("✍️ Writer 节点开始...")
    
    status = get_ui_container('status')
    progress = get_ui_container('progress')
    report_container = get_ui_container('report')
    
    if progress:
        progress.progress(0.85)
    
    if state.get('error'):
        error_report = f"## 生成失败\n\n**错误**: {state['error']}"
        if report_container:
            report_container.markdown(f"<div class='report-card'>{error_report}</div>", unsafe_allow_html=True)
        return {"report": error_report, "current_step": "生成错误报告"}
    
    data = state.get('scraped_data', [])
    if not data:
        no_data_report = "## 数据不足\n\n未能找到有效信息。"
        if report_container:
            report_container.markdown(f"<div class='report-card'>{no_data_report}</div>", unsafe_allow_html=True)
        return {"report": no_data_report, "current_step": "Writer: 无数据"}
    
    # 截取前3条高质量数据，每条250字符，控制Prompt长度在模型上下文限制内
    data_summary = []
    for item in data[:3]:
        content = item.get('content', '')[:250]
        keyword = item.get('keyword', 'unknown')
        data_summary.append(f"[{keyword}]: {content}")
    
    prompt = f"""基于以下数据生成"{state['company']}"尽调报告：
{chr(10).join(data_summary)}

要求：1.Markdown格式 2.包含概况/团队/融资/商业模式/风险 3.简洁500字以内"""

    try:
        # 180秒超时匹配SiliconFlow网关限制，防止云函数504错误
        client = OpenAI(
            api_key=state['api_key'], 
            base_url="https://api.siliconflow.cn/v1",
            timeout=180.0
        )
        
        if status:
            status.markdown("""
                <div class="status-card">
                    <div style="color:#38bdf8;font-weight:600;">✍️ Writer: 正在生成报告...</div>
                    <div class="time-estimate">约需10-20秒</div>
                </div>
            """, unsafe_allow_html=True)
        
        response = client.chat.completions.create(
            model="Pro/deepseek-ai/DeepSeek-V3",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            # 1200 tokens足够生成500字中文报告，同时控制API成本
            max_tokens=1200,
            # 非流式避免Streamlit在长生成中断开SSE连接导致前端卡死
            stream=False
        )
        
        full_report = response.choices[0].message.content
        
        # 清理可能的代码块标记，保证纯Markdown输出
        full_report = re.sub(r'^```markdown\s*', '', full_report)
        full_report = re.sub(r'^```\s*', '', full_report)
        full_report = re.sub(r'\s*```$', '', full_report)
        
        if report_container:
            report_container.markdown(f"<div class='report-card'>{full_report}</div>", unsafe_allow_html=True)
        
        if status:
            status.markdown("""
                <div class="status-card" style="border-color:#4ade80;">
                    <div style="color:#4ade80;font-weight:600;">✍️ Writer: 报告生成完成</div>
                </div>
            """, unsafe_allow_html=True)
        if progress:
            progress.progress(1.0)
        
        return {"report": full_report, "current_step": "✍️ Writer: 完成"}
        
    except Exception as e:
        error_msg = f"生成失败: {str(e)}"
        print(f"  ❌ {error_msg}")
        if report_container:
            report_container.markdown(f"<div class='report-card'>{error_msg}</div>", unsafe_allow_html=True)
        return {"report": error_msg, "current_step": f"Writer错误: {e}"}