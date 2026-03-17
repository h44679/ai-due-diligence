import os
import requests
import json
import time
from tavily import TavilyClient
import trafilatura
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from typing import List

class APIError(Exception):
    pass

def search_and_extract(keywords: List[str], max_results_per_kw: int = 2, api_key: str = None):
    TAVILY_API_KEY = api_key or os.getenv("TAVILY_API_KEY", "")
    if not TAVILY_API_KEY:
        raise APIError("Tavily API Key 未配置")
    
    try:
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
    except Exception as e:
        raise APIError(f"Tavily 客户端初始化失败: {e}")
    
    all_data = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }
    
    for kw in keywords:
        print(f"\n🔍 搜索关键词: {kw}")
        
        try:
            try:
                response = tavily.search(
                    query=kw,
                    search_depth="basic",
                    max_results=max_results_per_kw,
                    include_answer=False,
                    include_raw_content=False
                )
            except Exception as e:
                error_msg = str(e)
                if "Unauthorized" in error_msg or "invalid" in error_msg.lower():
                    raise APIError(f"Tavily API 认证失败: 请检查 API Key 是否正确")
                elif "rate limit" in error_msg.lower():
                    raise APIError(f"Tavily API 限流: 请稍后再试")
                else:
                    raise APIError(f"Tavily 搜索失败: {error_msg}")
            
            results = response.get('results', [])
            print(f"   找到 {len(results)} 个结果")
            
            for idx, result in enumerate(results):
                url = result['url']
                domain = urlparse(url).netloc
                print(f"   [{idx+1}/{len(results)}] {domain}", end=" ")
                
                text = ""
                fallback_level = "trafilatura"
                
                try:
                    # 视频和社交平台通常是多媒体内容，文本信息密度低且难提取，直接改用摘要
                    skip_domains = [
                        'youtube.com', 'youtu.be', 'twitter.com', 'x.com', 
                        'facebook.com', 'instagram.com', 'tiktok.com'
                    ]
                    if any(d in domain for d in skip_domains):
                        text = result.get('content', '')
                        fallback_level = "snippet_skip_video"
                        print(f"[⚪ 跳过] 视频/社交平台")
                    
                    else:
                        print(f"→ 提取...", end=" ")
                        
                        try:
                            # 15秒超时防止慢网站阻塞整个研究流程（Tavily API本身已消耗时间）
                            resp = requests.get(url, headers=headers, timeout=15)
                            resp.raise_for_status()
                        except requests.Timeout:
                            print(f"[⏱ 超时] 请求超过15秒")
                            text = result.get('content', '')
                            fallback_level = "snippet_timeout"
                            if text:
                                all_data.append(create_data_item(kw, url, domain, text, fallback_level))
                            continue
                        except requests.HTTPError as e:
                            # HTTP错误通常表示访问限制（403/500），改用API提供的摘要保证数据连续性
                            print(f"[🔴 HTTP错误] {e.response.status_code}")
                            text = result.get('content', '')
                            fallback_level = f"snippet_http_{e.response.status_code}"
                            if text:
                                all_data.append(create_data_item(kw, url, domain, text, fallback_level))
                            continue
                        except Exception as e:
                            print(f"[🔴 请求失败] {str(e)[:30]}")
                            text = result.get('content', '')
                            fallback_level = "snippet_request_failed"
                            if text:
                                all_data.append(create_data_item(kw, url, domain, text, fallback_level))
                            continue
                        
                        try:
                            text = trafilatura.extract(
                                resp.text,
                                include_comments=False,
                                include_tables=False,
                                deduplicate=True,
                                target_language="en"
                            ) or ""
                            text = text.strip()
                        except Exception as e:
                            print(f"提取失败: {e}")
                            text = ""
                        
                        # trafilatura擅长提取正文，但遇到非标准网页结构时内容可能过短，此时回退到BS4
                        if text and len(text) > 300:
                            fallback_level = "trafilatura"
                            print(f"[🟢 全文] {len(text)} 字符")
                        else:
                            print(f"[🟡 BS4]", end=" ")
                            fallback_level = "bs4"
                            
                            soup = BeautifulSoup(resp.text, 'html.parser')
                            for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                                element.decompose()
                            
                            paragraphs = soup.find_all(['p', 'h1', 'h2', 'h3', 'article'])
                            text = ' '.join(p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30)
                            text = text.strip()
                            
                            # BS4提取通常杂质较多，低于200字符视为不可靠，改用摘要
                            if len(text) < 200:
                                raise ValueError("BS4 内容不足")
                            
                            print(f"{len(text)} 字符")
                
                except Exception as e:
                    # 所有提取方式失败时，Tavily返回的摘要是最后保障，确保每个搜索结果都有对应记录
                    fallback_level = "snippet_fallback"
                    text = result.get('content', '')
                    print(f"[🔴 摘要] {len(text)} 字符 (回退)")
                
                if text:
                    # 限制3000字符防止下游LLM超出上下文窗口（4个关键词*2结果*3000=24000 tokens，在预算内）
                    all_data.append(create_data_item(kw, url, domain, text, fallback_level))
                
                # 0.3秒延迟避免触发目标站点的速率限制，保护IP不被封禁
                time.sleep(0.3)
                
        except APIError:
            raise
        except Exception as e:
            print(f"   ✗ 关键词 '{kw}' 处理失败: {e}")
            continue
    
    print(f"\n📊 总计提取: {len(all_data)} 条数据")
    return all_data

def create_data_item(keyword, url, domain, text, fallback_level):
    # 清理fallback_level字符串，避免特殊字符在日志或UI显示时造成格式混乱
    level_clean = fallback_level.replace('(', '_').replace(')', '').replace(' ', '_')
    
    source_tag = {
        "trafilatura": "🟢 全文",
        "bs4": "🟡 解析", 
        "snippet_fallback": "🔴 摘要",
        "snippet_skip_video": "⚪ 跳过",
        "snippet_timeout": "⏱ 超时",
        "snippet_request_failed": "❌ 失败",
        "snippet_http_403": "🚫 403禁止",
        "snippet_http_500": "🔴 500错误"
    }.get(fallback_level, "🔴 摘要")
    
    return {
        "keyword": keyword,
        "url": url,
        "domain": domain,
        "content": text[:3000],
        "content_length": len(text),
        "fallback_level": fallback_level,
        "source_tag": source_tag
    }