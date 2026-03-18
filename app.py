import streamlit as st
import sys
import os
import time
from typing import Dict, Any

# 仅在本地开发时添加当前目录到path，避免Streamlit Cloud部署时的路径污染
if os.path.exists(os.path.dirname(os.path.abspath(__file__))):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from graph import app as workflow_app, ResearchState
    from researcher import APIError
    graph_available = True
except ImportError as e:
    st.error(f"图模块导入失败: {e}")
    graph_available = False

st.set_page_config(
    page_title="AI 公司尽调系统", 
    page_icon="🏔️", 
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
[data-testid="stAppViewContainer"] {
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
}
.status-card {
    background: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(125, 211, 252, 0.2);
    border-radius: 16px;
    padding: 20px;
    margin: 10px 0;
}
.report-card {
    background: rgba(15, 23, 42, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 20px;
    padding: 32px;
    margin-top: 24px;
}
.agent-log {
    font-family: 'Courier New', monospace;
    font-size: 0.85rem;
    color: #94a3b8;
    background: rgba(0,0,0,0.3);
    padding: 8px 12px;
    border-radius: 6px;
    margin: 4px 0;
    border-left: 3px solid #38bdf8;
}
</style>
""", unsafe_allow_html=True)

# Session state持久化跨rerun的数据，避免Streamlit脚本重跑时的状态丢失
if "report" not in st.session_state:
    st.session_state.report = None
if "logs" not in st.session_state:
    st.session_state.logs = []
if "is_running" not in st.session_state:
    st.session_state.is_running = False
# LangGraph conditional edge会导致同一节点重复触发，用于去重跟踪
if "last_node" not in st.session_state:
    st.session_state.last_node = None

with st.sidebar:
    st.header("⚙️ 配置中心")
    
    try:
        api_key = st.secrets.get("DEEPSEEK_API_KEY", "")
        tavily_key = st.secrets.get("TAVILY_API_KEY", "")
    except Exception:
        api_key = ""
        tavily_key = ""
    
    if not api_key:
        api_key = st.text_input("DeepSeek API Key", type="password", key="api_key_input")
    else:
        st.success("✓ DeepSeek Key 已配置")
    
    if not tavily_key:
        tavily_key = st.text_input("Tavily API Key", type="password", key="tavily_key_input")
    else:
        st.success("✓ Tavily Key 已配置")
    
    # 运行时禁用按钮防止重复提交（防抖动）
    company_name = st.text_input("🏢 目标公司", value="Tesla", disabled=st.session_state.is_running)
    
    start_button = st.button(
        "🚀 开始尽调分析", 
        type="primary", 
        use_container_width=True,
        disabled=st.session_state.is_running or not graph_available
    )

st.markdown("""
<div style="text-align: center; margin-bottom: 2rem;">
    <h1 style="color: #e0f2fe;">🏔️ AI 公司尽调系统</h1>
    <p style="color: #94a3b8;">LangGraph 驱动 • 多 Agent 协作</p>
</div>
""", unsafe_allow_html=True)

def reset_session():
    st.session_state.report = None
    st.session_state.logs = []
    st.session_state.is_running = False
    st.session_state.last_node = None

def run_workflow():
    st.session_state.is_running = True
    st.session_state.report = None
    st.session_state.logs = []
    st.session_state.last_node = None
    
    progress_bar = st.progress(0)
    status_card = st.empty()
    log_container = st.empty()
    report_container = st.empty()
    
    # 存储UI容器引用到session_state，供nodes.py使用（避免global变量污染）
    st.session_state.ui_containers = {
        'status': status_card,
        'progress': progress_bar,
        'details': log_container,
        'report': report_container
    }
    
    initial_input = {
        "company": company_name,
        "api_key": api_key,
        "tavily_key": tavily_key,
        "search_plans": [],
        "scraped_data": [],
        "failed_keywords": [],
        "report": "",
        "review_comment": "",
        "loop_count": 0,
        "is_sufficient": False,
        "current_step": "初始化工作流",
        "total_data_found": 0,
        "error": ""
    }
    
    try:
        for event in workflow_app.stream(initial_input):
            for node_name, state_update in event.items():
                step_msg = state_update.get("current_step", f"节点: {node_name}")
                
                # LangGraph conditional edge会导致同一节点重复触发，只更新不追加避免刷屏
                if st.session_state.last_node == node_name:
                    if st.session_state.logs:
                        st.session_state.logs[-1] = f"[{node_name}] {step_msg}"
                else:
                    st.session_state.logs.append(f"[{node_name}] {step_msg}")
                    st.session_state.last_node = node_name
                
                # 限制日志数量防止浏览器内存泄漏（长流程时尤其重要）
                if len(st.session_state.logs) > 20:
                    st.session_state.logs.pop(0)
                
                with log_container.container():
                    for log in st.session_state.logs[-6:]:
                        st.markdown(f"<div class='agent-log'>{log}</div>", unsafe_allow_html=True)
                
                progress_map = {
                    "planner": 0.15,
                    "search_1": 0.25, "search_2": 0.35, "search_3": 0.45, "search_4": 0.55,
                    "reviewer": 0.75,
                    "writer": 0.9
                }
                if node_name in progress_map:
                    progress_bar.progress(progress_map[node_name])
                
                status_card.markdown(f"""
                <div class="status-card">
                    <div style="color:#38bdf8;font-weight:600;font-size:1.1rem;">
                        {node_name.upper()} 节点
                    </div>
                    <div style="color:#e2e8f0;margin-top:0.5rem;">
                        {step_msg}
                    </div>
                    <div style="color:#64748b;font-size:0.85rem;margin-top:0.5rem;">
                        数据条数: {state_update.get('total_data_found', 0)} | 
                        重试次数: {state_update.get('loop_count', 0)}
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                report_content = state_update.get("report")
                if report_content and isinstance(report_content, str) and len(report_content) > 100:
                    report_container.markdown(f"<div class='report-card'>{report_content}</div>", unsafe_allow_html=True)
                    st.session_state.report = report_content
        
        progress_bar.progress(1.0)
        status_card.success("✅ 尽调分析完成")
        
    except Exception as e:
        st.error(f"工作流执行错误: {str(e)}")
        import traceback
        st.code(traceback.format_exc())
    finally:
        st.session_state.is_running = False
        st.rerun()

if start_button:
    if not api_key:
        st.error("⚠️ 请输入 DeepSeek API Key")
    elif not company_name.strip():
        st.error("⚠️ 请输入公司名称")
    else:
        run_workflow()

if st.session_state.report:
    st.success("✅ 分析完成！")
    st.download_button(
        label="📥 下载Markdown报告",
        data=st.session_state.report,
        file_name=f"{company_name}_尽调报告.md",
        mime="text/markdown",
        use_container_width=True
    )
    
    if st.button("🔄 重新分析", use_container_width=True):
        reset_session()
        st.rerun()