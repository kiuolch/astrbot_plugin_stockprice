import requests
import asyncio
import re
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# --- 配置常量 ---
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://finance.sina.com.cn/'
}

# 新浪股票API
SINA_API = "https://hq.sinajs.cn/list={}"

# A股代码正则匹配
# 沪市：600/601/603/605/688开头（6位数字）
# 深市：000/001/002/003/300开头（6位数字）
SH_PATTERN = re.compile(r'^(sh)?(6[0-9]{5})$', re.IGNORECASE)
SZ_PATTERN = re.compile(r'^(sz)?([0-9]{6})$', re.IGNORECASE)

# 深市主板判断：000/001/002/003开头为深市主板，300开头为创业板
SZ_MAIN_PATTERN = re.compile(r'^(sz)?(0[0-9]{5})$', re.IGNORECASE)
SZ_CYB_PATTERN = re.compile(r'^(sz)?(3[0-9]{5})$', re.IGNORECASE)


@register("stock_price", "waterfeet", "A股股票实时股价查询插件", "1.0")
class StockPricePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    def _normalize_code(self, user_input: str) -> tuple[str, str]:
        """
        标准化用户输入的股票代码
        返回: (normalized_code, market_name) 或 (None, error_msg)
        """
        user_input = user_input.strip().lower()
        
        # 检查是否带前缀
        if user_input.startswith('sh'):
            code = user_input[2:]
            if SH_PATTERN.match(user_input):
                return f"sh{code}", "沪市"
            else:
                return None, "沪市股票代码格式错误，应以600/601/603/605/688开头"
        
        elif user_input.startswith('sz'):
            code = user_input[2:]
            if SZ_MAIN_PATTERN.match(user_input):
                return f"sz{code}", "深市主板"
            elif SZ_CYB_PATTERN.match(user_input):
                return f"sz{code}", "创业板"
            else:
                return None, "深市股票代码格式错误，应以000/001/002/003/300开头"
        
        # 纯数字格式，自动判断
        elif user_input.isdigit() and len(user_input) == 6:
            # 沪市：6开头
            if user_input.startswith('6'):
                return f"sh{user_input}", "沪市"
            # 深市：0或3开头
            elif user_input.startswith('0'):
                return f"sz{user_input}", "深市主板"
            elif user_input.startswith('3'):
                return f"sz{user_input}", "创业板"
            else:
                return None, f"无法识别的股票代码格式，A股代码应以0、3或6开头"
        
        else:
            return None, "股票代码格式错误，请输入6位数字代码（如：600000 或 000001）或带前缀的代码（如：sh600000 或 sz000001）"

    def _fetch_stock_data_sync(self, code: str) -> dict:
        """
        同步请求新浪股票API
        返回: 解析后的数据字典，或空字典表示请求失败
        """
        url = SINA_API.format(code)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.encoding = 'gb2312'  # 新浪API使用GB2312编码
            resp.raise_for_status()
            text = resp.text
        except Exception as e:
            logger.error(f"接口请求失败: {e}")
            return {}

        # 解析数据
        # 格式: var hq_str_sh600000="浦发银行,10.50,10.48,10.55,...";
        try:
            if '=""' in text or 'var hq_str_' not in text:
                # 股票代码不存在
                return {"exists": False}
            
            # 提取数据部分
            data_start = text.find('="') + 2
            data_end = text.rfind('"')
            data_str = text[data_start:data_end]
            
            if not data_str:
                return {"exists": False}
            
            fields = data_str.split(',')
            if len(fields) < 10:
                return {"exists": False}
            
            # 解析字段
            # fields[0]: 股票名称
            # fields[1]: 今日开盘价
            # fields[2]: 昨日收盘价
            # fields[3]: 当前价
            # fields[4]: 今日最高价
            # fields[5]: 今日最低价
            # fields[8]: 成交量（手）
            # fields[9]: 成交金额（元）
            
            stock_name = fields[0]
            current_price = float(fields[3]) if fields[3] else 0.0
            prev_close = float(fields[2]) if fields[2] else 0.0
            open_price = float(fields[1]) if fields[1] else 0.0
            high_price = float(fields[4]) if fields[4] else 0.0
            low_price = float(fields[5]) if fields[5] else 0.0
            
            # 计算涨跌
            change = current_price - prev_close
            change_pct = (change / prev_close) * 100 if prev_close != 0 else 0
            
            return {
                "exists": True,
                "name": stock_name,
                "current": current_price,
                "prev_close": prev_close,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "change": change,
                "change_pct": change_pct
            }
            
        except Exception as e:
            logger.error(f"数据解析失败: {e}")
            return {}

    def _format_stock_output(self, code: str, market: str, data: dict) -> str:
        """格式化股票数据输出"""
        if not data.get("exists"):
            return (
                f"❌ 股票代码 **{code}** 不存在\n"
                f"\n"
                f"📋 **输入示例：**\n"
                f"• 沪市：600000 或 sh600000（浦发银行）\n"
                f"• 深市：000001 或 sz000001（平安银行）\n"
                f"• 创业板：300001 或 sz300001（特锐德）\n"
                f"\n"
                f"💡 请检查代码是否正确后重新输入"
            )
        
        # 判断涨跌
        change = data["change"]
        change_pct = data["change_pct"]
        
        if change > 0:
            arrow = "📈 🔴"
            symbol = "+"
        elif change < 0:
            arrow = "📉 🟢"
            symbol = ""
        else:
            arrow = "➖ ⚪"
            symbol = ""
        
        output = (
            f"📊 **{data['name']}** ({code.upper()})\n"
            f"🏛️ 市场：{market}\n"
            f"💰 当前价：¥{data['current']:.2f} {arrow}\n"
            f"📊 涨跌幅：{symbol}{change:.2f} ({symbol}{change_pct:.2f}%)\n"
        )
        
        return output

    @filter.command("查询股价")
    async def query_stock(self, event: AstrMessageEvent, code: str = ""):
        '''查询A股股票实时股价，用法：/查询股价 [股票代码]'''
        
        # 1. 检查参数
        if not code or not code.strip():
            return event.plain_result(
                "⚠️ 请输入股票代码\n"
                "\n"
                "📋 **使用方法：** /查询股价 [股票代码]\n"
                "\n"
                "**支持的格式：**\n"
                "• 纯数字：600000、000001、300001\n"
                "• 带前缀：sh600000、sz000001、sz300001\n"
                "\n"
                "**示例：**\n"
                "• /查询股价 600000\n"
                "• /查询股价 sh600000\n"
                "• /查询股价 000001"
            )
        
        # 2. 标准化代码
        normalized_code, market = self._normalize_code(code)
        if normalized_code is None:
            return event.plain_result(
                f"❌ {market}\n"
                f"\n"
                f"📋 **正确格式示例：**\n"
                f"• 沪市：600000 或 sh600000\n"
                f"• 深市主板：000001 或 sz000001\n"
                f"• 创业板：300001 或 sz300001"
            )
        
        # 3. 在线程池中执行同步请求
        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(None, self._fetch_stock_data_sync, normalized_code)
        except Exception as e:
            return event.plain_result(f"❌ 数据请求发生错误，请稍后再试")

        if not data:
            return event.plain_result("⚠️ 网络请求失败，请稍后再试。")

        # 4. 格式化输出
        result = self._format_stock_output(normalized_code, market, data)
        return event.plain_result(result)
