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
    animation: fadeIn 0.3s ease-in;
}
@keyframes fadeIn {
    from { opacity: 0; transform: translateX(-10px); }
    to { opacity: 1; transform: translateX(0); }
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

with st.sidebar:
    st.header("⚙️ 配置中心")
    
    # Streamlit Secrets访问在Cloud和本地表现不同，需要兼容处理
    try:
        api_key = st.secrets.get("DEEPSEEK_API_KEY", "")
        tavily_key = st.secrets.get("TAVILY_API_KEY", "")
        secrets_available = True
    except Exception:
        secrets_available = False
        api_key = ""
        tavily_key = ""
    
    # 只有secrets不可用时才显示输入框，兼顾安全性与本地调试便利性
    if not api_key:
        api_key = st.text_input(
            "DeepSeek API Key", 
            type="password", 
            value=st.session_state.get("api_key_input", ""),
            key="api_key_input"
        )
    else:
        st.success("✓ DeepSeek Key 已配置 (Secrets)")
    
    if not tavily_key:
        tavily_key = st.text_input(
            "Tavily API Key", 
            type="password",
            value=st.session_state.get("tavily_key_input", ""),
            key="tavily_key_input"
        )
    else:
        st.success("✓ Tavily Key 已配置 (Secrets)")
    
    st.markdown("---")
    company_name = st.text_input(
        "🏢 目标公司", 
        value="Tesla",
        disabled=st.session_state.is_running
    )
    
    # 运行时禁用按钮防止重复提交（防抖动）
    start_button = st.button(
        "🚀 开始尽调分析", 
        type="primary", 
        use_container_width=True,
        disabled=st.session_state.is_running or not graph_available
    )

st.markdown("""
<div style="text-align: center; margin-bottom: 2rem;">
    <h1 style="color: #e0f2fe; margin-bottom: 0.5rem;">🏔️ AI 公司尽调系统</h1>
    <p style="color: #94a3b8; font-size: 0.9rem;">LangGraph 驱动 • 多 Agent 协作 • 高质量数据筛选</p>
</div>
""", unsafe_allow_html=True)

def reset_session():
    """清空状态开始新的工作流"""
    st.session_state.report = None
    st.session_state.logs = []
    st.session_state.is_running = False

def run_workflow():
    """封装工作流逻辑，与UI渲染解耦，支持异常时的状态清理"""
    st.session_state.is_running = True
    st.session_state.report = None
    st.session_state.logs = []
    
    progress_bar = st.progress(0)
    status_card = st.empty()
    log_container = st.empty()
    report_container = st.empty()
    
    # LangGraph的stream期望接收dict格式的state，不是Pydantic模型实例
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
        node_progress = {
            "planner": 0.2,
            "researcher": 0.5,
            "reviewer": 0.7,
            "writer": 0.9
        }
        
        logs_display = log_container.container()
        
        for event in workflow_app.stream(initial_input):
            for node_name, state_update in event.items():
                step_msg = state_update.get("current_step", f"节点: {node_name}")
                
                # 限制内存中的日志数量，防止长流程导致浏览器内存泄漏
                st.session_state.logs.append(f"[{node_name}] {step_msg}")
                if len(st.session_state.logs) > 50:
                    st.session_state.logs.pop(0)
                
                # 仅显示最近5条日志，平衡信息密度与可读性
                with logs_display:
                    for log in st.session_state.logs[-5:]:
                        st.markdown(f"<div class='agent-log'>{log}</div>", 
                                  unsafe_allow_html=True)
                
                # 节点级进度条更新，给用户清晰的阶段感知
                if node_name in node_progress:
                    progress_bar.progress(node_progress[node_name])
                
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
                
                # 检查report字段是否存在且非空（可能是空字符串或太短）
                report_content = state_update.get("report")
                if report_content and isinstance(report_content, str) and len(report_content) > 100:
                    report_container.markdown(
                        f"<div class='report-card'>{report_content}</div>", 
                        unsafe_allow_html=True
                    )
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

# 报告生成后展示下载按钮，放在if start_button块外确保rerun后依然可见
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