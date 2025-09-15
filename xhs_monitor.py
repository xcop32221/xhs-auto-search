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
import requests
from datetime import datetime

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
SEEN_NOTES_FILE = "/ql/data/scripts/xhs_seen_notes.json"

class XHSMonitor:
    def __init__(self):
        self.seen_notes = self.load_seen_notes()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Cookie': XHS_COOKIE,
            'Referer': 'https://www.xiaohongshu.com/',
            'Origin': 'https://www.xiaohongshu.com'
        })

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

    def search_notes(self, keyword, count=5):
        """搜索笔记"""
        try:
            url = "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes"
            data = {
                "keyword": keyword,
                "page": 1,
                "page_size": count,
                "search_id": "",
                "sort": "general",
                "note_type": 0,
                "ext_flags": [],
                "image_formats": ["jpg", "webp", "avif"]
            }

            response = self.session.post(url, json=data, timeout=30)

            if response.status_code == 200:
                result = response.json()
                if result.get('success') and result.get('data'):
                    items = result['data'].get('items', [])
                    notes = [item for item in items if item.get('model_type') == 'note']
                    return True, f"成功获取{len(notes)}个笔记", notes
                else:
                    return False, f"API错误: {result.get('msg', '未知错误')}", []
            else:
                return False, f"HTTP错误: {response.status_code}", []

        except Exception as e:
            return False, f"搜索异常: {str(e)}", []

    def get_note_detail(self, note_id, xsec_token):
        """获取笔记详情"""
        try:
            url = "https://edith.xiaohongshu.com/api/sns/web/v1/feed"
            data = {
                "source_note_id": note_id,
                "image_formats": ["jpg", "webp", "avif"],
                "extra": {"need_body_topic": "1"},
                "xsec_source": "pc_search",
                "xsec_token": xsec_token
            }

            response = self.session.post(url, json=data, timeout=30)

            if response.status_code == 200:
                result = response.json()
                if result.get('success') and result.get('data'):
                    items = result['data'].get('items', [])
                    if items:
                        return True, "成功", self.parse_note_info(items[0])
                return False, "数据为空", {}
            else:
                return False, f"HTTP错误: {response.status_code}", {}

        except Exception as e:
            return False, f"获取详情异常: {str(e)}", {}

    def parse_note_info(self, note_info):
        """解析笔记信息"""
        try:
            note_card = note_info.get('note_card', {})
            interact_info = note_card.get('interact_info', {})
            user = note_card.get('user', {})

            return {
                'id': note_info.get('id', ''),
                'title': note_card.get('display_title', '无标题'),
                'content': note_card.get('desc', ''),
                'author': user.get('nickname', '未知'),
                'likes': interact_info.get('liked_count', '0'),
                'comments': interact_info.get('comment_count', '0'),
                'views': interact_info.get('view_count', '0'),
                'publish_time': note_card.get('time', ''),
                'tags': [tag.get('name', '') for tag in note_card.get('tag_list', [])],
                'images': len(note_card.get('image_list', [])),
                'video': bool(note_card.get('video', {}).get('consumer', {}).get('origin_video_key', '')),
                'url': f"https://www.xiaohongshu.com/explore/{note_info.get('id', '')}"
            }
        except Exception as e:
            print(f"解析笔记信息错误: {e}")
            return {}

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

            if not XHS_COOKIE:
                error = "Cookie未配置，请设置XHS_COOKIE环境变量"
                print(error)
                QLAPI.notify("❌ 配置错误", error)
                return False

            # 搜索笔记
            success, msg, notes = self.search_notes(SEARCH_KEYWORD, SEARCH_COUNT)

            if not success:
                print(f"搜索失败: {msg}")
                QLAPI.notify("❌ 搜索失败", f"{SEARCH_KEYWORD}\n{msg}")
                return False

            if not notes:
                print("未找到笔记")
                return True

            print(f"获取到 {len(notes)} 个笔记")

            # 获取详情并过滤新笔记
            new_notes = []
            for note in notes:
                note_id = note.get('id', '')
                xsec_token = note.get('xsec_token', '')

                if note_id and xsec_token:
                    success, msg, note_detail = self.get_note_detail(note_id, xsec_token)
                    if success and note_detail:
                        if not self.is_note_seen(note_detail):
                            new_notes.append(note_detail)
                            self.mark_note_as_seen(note_detail)
                        else:
                            print(f"已看过: {note_detail.get('title', '')[:20]}")
                    time.sleep(2)  # 避免请求过频

            # 保存记录
            self.save_seen_notes()

            # 发送通知
            summary = f"""📊 监控汇总 - {SEARCH_KEYWORD}
📝 获取: {len(notes)} 个
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
