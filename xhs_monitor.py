#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
小红书爬虫 - 青龙面板版
搜索"成都约妆"关键词，通过QLAPI发送通知，避免重复通知
每10分钟执行一次

cron: */10 * * * *
new Env('小红书成都约妆监控');
"""

import os
import sys
import json
import time
import hashlib
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
        def notify(title, content):
            print(f"\n=== 通知 ===")
            print(f"标题: {title}")
            print(f"内容: {content}")
            print("==========\n")
    QLAPI = MockQLAPI()

# 配置 - 从环境变量读取
SEARCH_KEYWORD = os.getenv('XHS_KEYWORD', '成都约妆')
SEARCH_COUNT = int(os.getenv('XHS_COUNT', '5'))
XHS_COOKIE = os.getenv('XHS_COOKIE', os.getenv('COOKIES', ''))  # 兼容COOKIES变量名

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
        content = f"{note_data.get('id', '')}{note_data.get('title', '')}"
        return hashlib.md5(content.encode()).hexdigest()

    def is_note_seen(self, note_data):
        """检查是否已看过"""
        note_id = self.generate_note_id(note_data)
        return note_id in self.seen_notes

    def mark_note_as_seen(self, note_data):
        """标记为已看过"""
        note_id = self.generate_note_id(note_data)
        self.seen_notes.add(note_id)

    def search_and_get_notes(self, keyword, count=5):
        """搜索并获取笔记详情"""
        try:
            # 初始化cookie
            cookies_str, base_path = init()
            if not cookies_str:
                return False, "Cookie未配置", []

            print(f"开始搜索: {keyword}")

            # 使用原有的API搜索
            note_data_list, success, msg = self.data_spider.spider_some_search_note(
                query=keyword,
                require_num=count,
                cookies_str=cookies_str,
                base_path=None,
                save_choice='none'
            )

            if success:
                print(f"搜索成功，获取到 {len(note_data_list)} 个笔记")
                return True, f"成功获取{len(note_data_list)}个笔记", note_data_list
            else:
                print(f"搜索失败: {msg}")
                return False, f"搜索失败: {msg}", []

        except Exception as e:
            print(f"搜索异常: {e}")
            return False, f"搜索异常: {str(e)}", []

    def format_note_message(self, note_data):
        """格式化笔记通知消息"""
        title = f"📝 {note_data.get('title', '无标题')[:30]}"

        content_parts = [
            f"👤 作者: {note_data.get('author', '未知')}",
            f"❤️ 点赞: {note_data.get('likes', 0)}",
            f"💬 评论: {note_data.get('comments', 0)}",
        ]

        if note_data.get('content'):
            preview = note_data.get('content')[:100]
            if len(note_data.get('content')) > 100:
                preview += "..."
            content_parts.append(f"📄 {preview}")

        if note_data.get('tags'):
            tags = " ".join([f"#{tag}" for tag in note_data.get('tags', [])[:3]])
            content_parts.append(f"🏷️ {tags}")

        if note_data.get('url'):
            content_parts.append(f"🔗 {note_data.get('url')}")

        return title, "\n".join(content_parts)

    def run(self):
        """主执行函数"""
        try:
            print(f"开始监控: {SEARCH_KEYWORD}")

            # 搜索并获取笔记详情
            success, msg, note_data_list = self.search_and_get_notes(SEARCH_KEYWORD, SEARCH_COUNT)

            if not success:
                print(f"搜索失败: {msg}")
                QLAPI.notify("❌ 搜索失败", f"{SEARCH_KEYWORD}\n{msg}")
                return False

            if not note_data_list:
                print("未找到笔记")
                QLAPI.notify("ℹ️ 监控结果", f"{SEARCH_KEYWORD}\n未找到相关笔记")
                return True

            print(f"获取到 {len(note_data_list)} 个笔记")

            # 过滤新笔记
            new_notes = []
            for note_data in note_data_list:
                if not self.is_note_seen(note_data):
                    new_notes.append(note_data)
                    self.mark_note_as_seen(note_data)
                else:
                    print(f"已看过: {note_data.get('title', '')[:20]}")

            # 保存记录
            self.save_seen_notes()

            # 发送汇总通知
            summary = f"""📊 监控汇总 - {SEARCH_KEYWORD}
📝 获取: {len(note_data_list)} 个
🆕 新增: {len(new_notes)} 个
⏰ {datetime.now().strftime('%H:%M:%S')}
📊 历史: {len(self.seen_notes)} 个"""

            QLAPI.notify("📊 小红书监控", summary)

            # 发送新笔记通知
            for i, note_data in enumerate(new_notes, 1):
                title, content = self.format_note_message(note_data)
                QLAPI.notify(title, content)
                print(f"已通知第 {i} 个新笔记")
                if i < len(new_notes):
                    time.sleep(3)

            print(f"完成! 新笔记: {len(new_notes)} 个")
            return True

        except Exception as e:
            error = f"执行错误: {str(e)}"
            print(error)
            QLAPI.notify("💥 监控异常", error)
            return False

def main():
    monitor = XHSMonitor()
    success = monitor.run()
    if not success:
        exit(1)

if __name__ == "__main__":
    main()
