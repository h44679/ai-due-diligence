import os
import json
from json import JSONDecodeError
from typing import Dict, List
from openai import OpenAI, APIError, AuthenticationError

def get_search_plan(
    company_name: str, 
    client: OpenAI = None, 
    api_key: str = None
) -> Dict[str, List[str]]:
    """
    生成公司尽调搜索计划，失败时返回fallback策略确保服务可用性。
    """
    if client is None:
        api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise AuthenticationError("API key must be provided via argument or env var")
        
        # SiliconFlow是DeepSeek的国内代理，base_url末尾空格会导致404
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.siliconflow.cn/v1"
        )
    
    system_prompt = """你是一个专业的公司尽调搜索规划专家。
用户给你一个公司名，你必须从CEO、创始团队、融资、商业模式等维度，**生成 4 个**精准的英文搜索关键词。
只输出纯 JSON，不要任何额外文字。
格式严格如下：
{
  "search_plans": ["keyword1", "keyword2", "keyword3", "keyword4"]
}
**注意：只能生成4个关键词，不要多也不要少。**"""

    try:
        response = client.chat.completions.create(
            model="Pro/deepseek-ai/DeepSeek-V3",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"公司名：{company_name}"}
            ],
            # temperature>1容易产生幻觉关键词，0.7在保证创意的同时保持准确性
            temperature=0.7,
            max_tokens=500,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        
        # 必须验证JSON结构，防止模型返回字段名错误或数量不对
        json_data = json.loads(content)
        if not isinstance(json_data.get("search_plans"), list) or len(json_data["search_plans"]) != 4:
            raise ValueError(f"模型返回格式错误: {content}")
            
        return json_data
        
    except (JSONDecodeError, ValueError, APIError) as e:
        # 结构化错误和API错误统一返回fallback，保证上游Agent能继续执行
        print(f"[Planner] 规划失败，使用fallback策略: {e}")
        return {
            "search_plans": [
                f"{company_name} CEO founder",
                f"{company_name} funding valuation", 
                f"{company_name} business model revenue",
                f"{company_name} competitors market share"
            ]
        }

if __name__ == "__main__":
    # 本地IDE调试块，生产环境由LangGraph编排调用
    test_key = os.getenv("DEEPSEEK_API_KEY")
    if test_key:
        result = get_search_plan("Tesla", api_key=test_key)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("请设置 DEEPSEEK_API_KEY 环境变量")