#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
小红书爬虫 - 青龙面板版
搜索"成都约妆"关键词，通过QLAPI发送通知，避免重复通知
每10分钟执行一次

cron: 0 0,6-23 * * *
new Env('小红书成都约妆监控');
"""

import os
import sys
import json
import time
import hashlib
import requests
import random
from datetime import datetime

# 添加当前目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

try:
    from main import Data_Spider
    from xhs_utils.common_util import init
except ImportError as e:
    print(f"导入模块失败: {e}")
    sys.exit(1)

# 青龙面板QLAPI
try:
    from ql import QLAPI
except ImportError:
    # 如果不在青龙环境中，使用print模拟
    class MockQLAPI:
        @staticmethod
        def notify(data):
            print(f"\n=== 通知 ===")
            print(f"标题: {data.get('title', '无标题')}")
            print(f"内容: {data.get('content', '无内容')}")
            print("==========\n")

        @staticmethod
        def systemNotify(data):
            print(f"\n=== 系统通知 ===")
            print(f"标题: {data.get('title', '无标题')}")
            print(f"内容: {data.get('content', '无内容')}")
            print("===============\n")
    QLAPI = MockQLAPI()

# 配置 - 从环境变量读取
# 优化关键词：更偏向用户需求的表达方式
SEARCH_KEYWORDS = os.getenv('XHS_KEYWORDS', '成都化妆推荐,成都哪里化妆,成都化妆哪家好,成都美妆推荐,成都化妆店推荐,成都化妆攻略').split(',')
SEARCH_COUNT = int(os.getenv('XHS_COUNT', '50'))  # 增加搜索数量

# 备用关键词：当主要关键词效果不好时使用
BACKUP_KEYWORDS = ['成都美妆', '成都化妆', '成都妆容', '成都美容', '成都彩妆', '成都造型']
XHS_COOKIE = os.getenv('XHS_COOKIE', os.getenv('COOKIES', ''))  # 兼容COOKIES变量名
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', '')  # DeepSeek API密钥

# 兼容旧版本单个关键词配置 - 只在没有设置新配置时使用
if os.getenv('XHS_KEYWORD') and not os.getenv('XHS_KEYWORDS'):
    SEARCH_KEYWORDS = [os.getenv('XHS_KEYWORD')]

# 数据存储路径
SEEN_NOTES_FILE = os.getenv('XHS_SEEN_FILE', '/ql/data/scripts/xhs_seen_notes.json')

# 如果在非青龙环境中，使用当前目录
if not os.path.exists(os.path.dirname(SEEN_NOTES_FILE)):
    SEEN_NOTES_FILE = os.path.join(current_dir, 'xhs_seen_notes.json')

class XHSMonitor:
    def __init__(self):
        self.seen_notes = self.load_seen_notes()
        self.data_spider = Data_Spider()

    def load_seen_notes(self):
        """加载已看过的笔记ID"""
        try:
            if os.path.exists(SEEN_NOTES_FILE):
                with open(SEEN_NOTES_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return set(data.get('seen_ids', []))
            return set()
        except Exception as e:
            print(f"加载已看笔记记录失败: {e}")
            return set()

    def save_seen_notes(self):
        """保存已看过的笔记ID"""
        try:
            os.makedirs(os.path.dirname(SEEN_NOTES_FILE), exist_ok=True)

            data = {
                'seen_ids': list(self.seen_notes),
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'total_count': len(self.seen_notes)
            }

            with open(SEEN_NOTES_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"已保存 {len(self.seen_notes)} 个笔记ID")
        except Exception as e:
            print(f"保存记录失败: {e}")

    def generate_note_id(self, note_data):
        """生成笔记唯一ID"""
        content = f"{note_data.get('note_id', '')}{note_data.get('title', '')}"
        return hashlib.md5(content.encode()).hexdigest()

    def is_note_seen(self, note_data):
        """检查是否已看过"""
        note_id = self.generate_note_id(note_data)
        return note_id in self.seen_notes

    def mark_note_as_seen(self, note_data):
        """标记为已看过"""
        note_id = self.generate_note_id(note_data)
        self.seen_notes.add(note_id)

    def analyze_note_intent(self, note_data):
        """使用DeepSeek分析笔记意图"""
        if not DEEPSEEK_API_KEY:
            print("DeepSeek API密钥未配置，跳过意图分析")
            return True  # 如果没有配置API，默认通过

        try:
            title = note_data.get('title', '')
            desc = note_data.get('desc', '')
            nickname = note_data.get('nickname', '')

            # 构建分析内容
            content = f"标题: {title}\n作者: {nickname}\n内容: {desc}"

            # DeepSeek API请求
            headers = {
                'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
                'Content-Type': 'application/json'
            }

            data = {
                "model": "deepseek-chat",
                "messages": [
                    {
                        "role": "system",
                        "content": """你是小红书内容分析专家。请判断这个笔记是否是普通用户发布的有化妆需求的内容。

用户需求笔记特征（回答YES）：
1. 求助类：求推荐、求攻略、问哪里好、咨询价格
2. 分享类：作为顾客分享体验、晒化妆效果、记录过程
3. 疑问类：询问化妆相关问题、对比选择、求建议
4. 语气：使用"姐妹们"、"宝子们"、"求推荐"、"有没有"、"怎么样"

化妆师广告特征（回答NO）：
1. 服务宣传：接单、约妆、可预约、联系我、价格透明
2. 技术展示：专业化妆师、工作室、作品展示、客户案例
3. 营销语言：速约、一对一、上门服务、档期、排期
4. 昵称特征：包含"化妆师"、"美妆"、"工作室"等

分析要点：
- 重点看内容语气和表达方式
- 普通用户多用疑问句和求助语气
- 化妆师多用肯定句和推销语言

只回答：YES（用户需求）或 NO（化妆师广告）"""
                    },
                    {
                        "role": "user",
                        "content": content
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 10
            }

            response = requests.post(
                'https://api.deepseek.com/v1/chat/completions',
                headers=headers,
                json=data,
                timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                answer = result['choices'][0]['message']['content'].strip().upper()

                is_user_demand = answer == 'YES'
                print(f"AI分析结果: {answer} - {'用户需求' if is_user_demand else '化妆师广告'}")
                return is_user_demand
            else:
                print(f"DeepSeek API请求失败: {response.status_code}")
                return True  # API失败时默认通过

        except Exception as e:
            print(f"DeepSeek分析异常: {e}")
            return True  # 异常时默认通过

    def search_and_get_notes(self, keywords, count=5):
        """搜索并获取笔记详情 - 支持多关键词"""
        all_notes = []
        all_success_keywords = []

        try:
            # 初始化cookie
            cookies_str, base_path = init()
            if not cookies_str:
                return False, "Cookie未配置", []

            # 每个关键词搜索的数量
            per_keyword_count = max(1, count // len(keywords))

            for keyword in keywords:
                keyword = keyword.strip()
                if not keyword:
                    continue

                print(f"开始搜索关键词: {keyword}")

                # 随机化搜索参数，避免重复结果
                sort_choices = [0, 1, 2]  # 综合排序, 最新, 最多点赞
                time_choices = [0, 1, 2]  # 不限, 一天内, 一周内

                sort_type = random.choice(sort_choices)
                note_time = random.choice(time_choices)

                print(f"搜索参数: 排序={sort_type}, 时间={note_time}")

                note_data_list, success, msg = self.data_spider.spider_some_search_note(
                    query=keyword,
                    require_num=per_keyword_count,
                    cookies_str=cookies_str,
                    base_path=None,
                    save_choice='none',
                    sort_type_choice=sort_type,  # 随机排序
                    note_type=2,                 # 普通笔记
                    note_time=note_time,         # 随机时间范围
                    note_range=0,                # 不限
                    pos_distance=2,              # 附近
                    geo={                        # 成都地区
                        "latitude": 30.539416,
                        "longitude": 104.070491
                    }
                )

                if success and note_data_list:
                    print(f"关键词 '{keyword}' 搜索成功，获取到 {len(note_data_list)} 个笔记")
                    all_notes.extend(note_data_list)
                    all_success_keywords.append(keyword)
                    time.sleep(2)  # 关键词间隔
                else:
                    print(f"关键词 '{keyword}' 搜索失败: {msg}")

            # 去重（基于note_id）
            seen_note_ids = set()
            unique_notes = []
            for note in all_notes:
                note_id = note.get('note_id', '')
                if note_id and note_id not in seen_note_ids:
                    seen_note_ids.add(note_id)
                    unique_notes.append(note)

            if unique_notes:
                print(f"多关键词搜索完成，去重后获取到 {len(unique_notes)} 个笔记")
                success_msg = f"成功关键词: {', '.join(all_success_keywords)}, 获取{len(unique_notes)}个笔记"
                return True, success_msg, unique_notes
            else:
                return False, "所有关键词都未找到相关笔记", []

        except Exception as e:
            print(f"搜索异常: {e}")
            return False, f"搜索异常: {str(e)}", []

    def format_note_message(self, note_data):
        """格式化笔记通知消息"""
        title = f"📝 {note_data.get('title', '无标题')[:30]}"

        content_parts = [
            f"👤 作者: {note_data.get('nickname', '未知')}",
            f"❤️ 点赞: {note_data.get('liked_count', 0)}",
            f"💬 评论: {note_data.get('comment_count', 0)}",
            f"🔥 收藏: {note_data.get('collected_count', 0)}",
        ]

        # 笔记描述内容（完整内容，不截取）
        if note_data.get('desc'):
            content_parts.append(f"📄 内容: {note_data.get('desc')}")

        # 标签
        if note_data.get('tags'):
            tags = " ".join([f"#{tag}" for tag in note_data.get('tags', [])[:3]])
            content_parts.append(f"🏷️ 标签: {tags}")

        # 笔记链接
        if note_data.get('note_url'):
            content_parts.append(f"🔗 链接: {note_data.get('note_url')}")

        # 发布时间
        if note_data.get('upload_time'):
            content_parts.append(f"⏰ 发布: {note_data.get('upload_time')}")

        # 图片数量
        if note_data.get('image_list'):
            content_parts.append(f"🖼️ 图片: {len(note_data.get('image_list', []))} 张")

        return title, "\n".join(content_parts)

    def run(self):
        """主执行函数"""
        try:
            print(f"开始监控，使用关键词: {', '.join(SEARCH_KEYWORDS)}")

            # 搜索并获取笔记详情
            success, msg, note_data_list = self.search_and_get_notes(SEARCH_KEYWORDS, SEARCH_COUNT)

            if not success:
                print(f"搜索失败: {msg}")
                QLAPI.systemNotify({"title": "❌ 搜索失败", "content": f"{', '.join(SEARCH_KEYWORDS)}\n{msg}"})
                return False

            if not note_data_list:
                print("未找到笔记")
                QLAPI.systemNotify({"title": "ℹ️ 监控结果", "content": f"{', '.join(SEARCH_KEYWORDS)}\n未找到相关笔记"})
                return True

            print(f"获取到 {len(note_data_list)} 个笔记")

            # 过滤新笔记并进行AI意图分析
            new_notes = []
            new_notes_count = 0  # 新笔记总数
            filtered_ads_count = 0  # 被过滤的广告数

            for note_data in note_data_list:
                if not self.is_note_seen(note_data):
                    new_notes_count += 1
                    # 使用DeepSeek分析笔记意图
                    print(f"分析笔记: {note_data.get('title', '')[:30]}")
                    is_user_demand = self.analyze_note_intent(note_data)

                    if is_user_demand:
                        new_notes.append(note_data)
                        print(f"✅ 用户需求笔记，加入通知队列")
                    else:
                        filtered_ads_count += 1
                        print(f"❌ 化妆师广告笔记，已过滤")

                    self.mark_note_as_seen(note_data)
                    time.sleep(1)  # API请求间隔
                else:
                    print(f"已看过: {note_data.get('title', '')[:20]}")

            # 保存记录
            self.save_seen_notes()

            # 发送汇总通知
            summary = f"""📊 监控汇总 - {', '.join(SEARCH_KEYWORDS)}
📝 获取笔记: {len(note_data_list)} 个
🆕 新增笔记: {new_notes_count} 个
🤖 AI筛选后: {len(new_notes)} 个用户需求
🚫 过滤广告: {filtered_ads_count} 个化妆师广告
⏰ 检查时间: {datetime.now().strftime('%H:%M:%S')}
📊 历史记录: {len(self.seen_notes)} 个"""

            QLAPI.systemNotify({"title": "📊 小红书监控", "content": summary})

            # 如果用户需求笔记太少，尝试备用关键词
            if len(new_notes) == 0 and len(note_data_list) > 0:
                print("主要关键词未找到用户需求，尝试备用关键词...")
                backup_keyword = random.choice(BACKUP_KEYWORDS)
                print(f"使用备用关键词: {backup_keyword}")

                backup_success, backup_msg, backup_notes = self.search_and_get_notes([backup_keyword], 5)
                if backup_success and backup_notes:
                    for note_data in backup_notes:
                        if not self.is_note_seen(note_data):
                            print(f"备用搜索分析: {note_data.get('title', '')[:30]}")
                            is_user_demand = self.analyze_note_intent(note_data)

                            if is_user_demand:
                                new_notes.append(note_data)
                                print(f"✅ 备用搜索找到用户需求笔记")

                            self.mark_note_as_seen(note_data)
                            time.sleep(1)

                    self.save_seen_notes()

            # 发送新笔记通知
            for i, note_data in enumerate(new_notes, 1):
                title, content = self.format_note_message(note_data)
                QLAPI.systemNotify({"title": title, "content": content})
                print(f"已通知第 {i} 个新笔记")
                if i < len(new_notes):
                    time.sleep(3)

            print(f"完成! 新笔记: {len(new_notes)} 个")
            return True

        except Exception as e:
            error = f"执行错误: {str(e)}"
            print(error)
            QLAPI.systemNotify({"title": "💥 监控异常", "content": error})
            return False

def main():
    monitor = XHSMonitor()
    success = monitor.run()
    if not success:
        exit(1)

if __name__ == "__main__":
    main()
