# -*- coding: utf-8 -*-
"""
MC 聊天实时翻译  ——  Minecraft 国际服中文助手

原理：读取 Minecraft Java 版日志 logs/latest.log 里的 [CHAT] 行，
      实时翻译成中文，显示在一个无边框、半透明、置顶的悬浮窗里。

只依赖 Python 标准库（tkinter / urllib），无需 pip 安装任何东西。
"""

import ctypes
import ctypes.wintypes as wt
import asyncio
import difflib
import json
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

APP_NAME = "MC 聊天翻译"
APP_VER = "1.1"

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
CACHE_PATH = BASE_DIR / "cache.json"
HISTORY_PATH = BASE_DIR / "聊天记录.log"

# ---------------------------------------------------------------- 配色
KEY_COLOR = "#010203"      # 透明色键（这个颜色的像素会变全透明）
PANEL = "#12151a"          # 面板底色
BORDER = "#2b323b"
TEXT_MAIN = "#e8ecf1"
TEXT_DIM = "#7f8b9a"
TEXT_SYS = "#93a3b8"
ACCENT = "#5ac8fa"
BTN_HOVER = "#232a33"

NAME_COLORS = ["#7ec8e3", "#f2b880", "#a8d98a", "#e8a0bf",
               "#c7b3f0", "#f0d78c", "#8fd6c9", "#f5a97f"]

FONT_CN = "Microsoft YaHei UI"


# ================================================================ 配置
DEFAULTS = {
    "x": 40, "y": 300, "width": 560, "height": 430,
    "opacity": 0.98,
    "font_size": 10,
    "always_on_top": True,
    "show_original": True,
    "filter_system": False,
    "filter_join": True,
    "follow_mc": True,
    "offset_x": 24,
    "offset_y": 90,
    "click_through": False,
    "show_input": True,
    "channel": "auto",          # auto / volc / mymemory / youdao / llm
    "llm_base": "https://api.deepseek.com/v1",
    "llm_key": "",
    "llm_model": "deepseek-chat",
    "log_path": "",
    "game_root": "",
    "read_from_end": True,
    "max_lines": 300,
    "ocr_region": "window",     # window / cursor / screen
    "ocr_scale": 2,
    "ocr_interval": 3.0,
    "ocr_max": 40,
    "cfg_ver": 2,
}


class Config:
    def __init__(self):
        self.data = dict(DEFAULTS)
        self.lock = threading.Lock()
        self.existed = CONFIG_PATH.exists()
        try:
            if self.existed:
                saved = json.loads(CONFIG_PATH.read_text("utf-8"))
                self.data.update({k: v for k, v in saved.items() if k in DEFAULTS})
        except Exception:
            pass

    def get(self, k, d=None):
        return self.data.get(k, DEFAULTS.get(k, d))

    def set(self, k, v):
        with self.lock:
            self.data[k] = v

    def save(self):
        try:
            with self.lock:
                CONFIG_PATH.write_text(
                    json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass


# ================================================================ 游戏词典
# 1) 缩写/黑话 -> 完整英文（喂给翻译引擎前先展开，效果提升非常明显）
SLANG = {
    "gg": "good game", "wp": "well played", "ggwp": "good game well played",
    "ez": "easy", "e z": "easy", "rekt": "destroyed", "noob": "newbie",
    "nub": "newbie", "newb": "newbie", "brb": "be right back",
    "afk": "away from keyboard", "ty": "thank you", "thx": "thanks",
    "tysm": "thank you so much", "np": "no problem", "wb": "welcome back",
    "lol": "lol", "lmao": "laughing", "rofl": "laughing", "omg": "oh my god",
    "wtf": "what the hell", "idk": "i do not know", "tbh": "to be honest",
    "imo": "in my opinion", "imho": "in my opinion", "btw": "by the way",
    "pls": "please", "plz": "please", "plss": "please", "u": "you",
    "ur": "your", "r": "are", "y": "why", "k": "ok", "bc": "because",
    "cuz": "because", "coz": "because", "gf": "good fight", "gl": "good luck",
    "hf": "have fun", "gtg": "got to go", "cya": "see you",
    "dm": "direct message", "pm": "private message", "op": "overpowered",
    "pvp": "player versus player", "pve": "player versus environment",
    "tp": "teleport", "xp": "experience", "exp": "experience", "hp": "health",
    "ench": "enchantment", "enchant": "enchantment", "dia": "diamond",
    "dias": "diamonds", "ems": "emeralds", "neth": "netherite",
    "ely": "elytra", "pots": "potions", "pot": "potion",
    "gapple": "golden apple", "god apple": "enchanted golden apple",
    "notch apple": "enchanted golden apple", "echest": "ender chest",
    "shulker": "shulker box", "grief": "destroy", "griefing": "destroying",
    "grif": "destroy", "base": "base", "spawn": "spawn point",
    "nether": "the nether", "overworld": "overworld",
    "smp": "survival multiplayer", "ah": "auction house",
    "lvl": "level", "lvls": "levels", "lvl": "level",
    "hacker": "hacker", "hax": "hacks", "xray": "xray cheat",
    "staff": "staff", "mod": "moderator", "admin": "administrator",
    "gm": "game master", "srv": "server", "mc": "minecraft",
    "1v1": "one versus one", "2v2": "two versus two",
    "wanna": "want to", "gonna": "going to", "gotta": "got to",
    "rn": "right now", "atm": "at the moment", "ngl": "not gonna lie",
    "fr": "for real", "sus": "suspicious", "pog": "awesome",
    "poggers": "awesome", "sheesh": "wow", "oof": "ouch",
    "sick": "awesome", "insane": "amazing", "lit": "great",
    "goat": "the greatest", "cracked": "very skilled", "sweaty": "tryhard",
    "rip": "rest in peace", "f": "pay respects", "brb": "be right back",
    "ig": "i guess", "jk": "just kidding", "tho": "though", "thru": "through",
    "msg": "message", "add": "add", "pls": "please", "sry": "sorry",
}

# 2) 游戏术语英文 -> 中文（翻译后做兜底替换，保证术语一定对）
TERMS = {
    "netherite": "下界合金", "nether": "下界", "the end": "末地",
    "overworld": "主世界", "elytra": "鞘翅", "creeper": "苦力怕",
    "enderman": "末影人", "endermite": "末影螨", "ghast": "恶魂",
    "blaze": "烈焰人", "wither": "凋灵", "end crystal": "末影水晶",
    "ender dragon": "末影龙", "warden": "监守者", "shulker": "潜影贝",
    "shulker box": "潜影盒", "beacon": "信标", "conduit": "潮涌核心",
    "mending": "经验修补", "sharpness": "锋利", "protection": "保护",
    "unbreaking": "耐久", "fortune": "时运", "silk touch": "精准采集",
    "looting": "抢夺", "smite": "亡灵杀手", "knockback": "击退",
    "efficiency": "效率", "redstone": "红石", "lapis": "青金石",
    "lapis lazuli": "青金石", "emerald": "绿宝石", "emeralds": "绿宝石",
    "diamond": "钻石", "diamonds": "钻石", "gold": "金", "iron": "铁",
    "coal": "煤炭", "quartz": "石英", "ancient debris": "远古残骸",
    "obsidian": "黑曜石", "crying obsidian": "哭泣的黑曜石",
    "bedrock": "基岩", "glowstone": "荧石", "sea lantern": "海晶灯",
    "torch": "火把", "campfire": "营火", "lantern": "灯笼",
    "chest": "箱子", "barrel": "木桶", "hopper": "漏斗",
    "piston": "活塞", "repeater": "红石中继器", "comparator": "红石比较器",
    "observer": "侦测器", "dispenser": "发射器", "dropper": "投掷器",
    "crafting table": "工作台", "furnace": "熔炉", "anvil": "铁砧",
    "enchanting table": "附魔台", "brewing stand": "酿造台",
    "cauldron": "炼药锅", "chestplate": "胸甲", "helmet": "头盔",
    "leggings": "护腿", "boots": "靴子", "sword": "剑", "pickaxe": "镐",
    "axe": "斧", "shovel": "锹", "hoe": "锄", "bow": "弓",
    "crossbow": "弩", "arrow": "箭", "shield": "盾牌", "trident": "三叉戟",
    "fishing rod": "钓鱼竿", "firework": "烟花", "totem": "不死图腾",
    "totem of undying": "不死图腾", "golden apple": "金苹果",
    "enchanted golden apple": "附魔金苹果", "ender pearl": "末影珍珠",
    "ender eye": "末影之眼", "blaze rod": "烈焰棒", "nether star": "下界之星",
    "dragon egg": "龙蛋", "slime": "史莱姆", "magma cube": "岩浆怪",
    "hoglin": "疣猪兽", "piglin": "猪灵", "zombified piglin": "僵尸猪灵",
    "silverfish": "蠹虫", "phantom": "幻翼", "drowned": "溺尸",
    "husk": "尸壳", "stray": "流浪者", "pillager": "掠夺者",
    "ravager": "劫掠兽", "vex": "恼鬼", "evoker": "唤魔者",
    "vindicator": "卫道士", "witch": "女巫", "spider": "蜘蛛",
    "cave spider": "洞穴蜘蛛", "wolf": "狼", "cat": "猫", "horse": "马",
    "llama": "羊驼", "villager": "村民", "wandering trader": "流浪商人",
    "iron golem": "铁傀儡", "snow golem": "雪傀儡", "bee": "蜜蜂",
    "turtle": "海龟", "dolphin": "海豚", "guardian": "守卫者",
    "elder guardian": "远古守卫者", "strider": "炽足兽", "frog": "青蛙",
    "allay": "悦灵", "camel": "骆驼", "sniffer": "嗅探兽",
    "armadillo": "犰狳", "breeze": "旋风人", "bogged": "沼骸",
    "zombie": "僵尸", "skeleton": "骷髅", "witch hut": "女巫小屋",
    "village": "村庄", "villages": "村庄", "stronghold": "要塞",
    "nether fortress": "下界要塞", "bastion": "堡垒遗迹",
    "end city": "末地城", "dungeon": "地牢", "mineshaft": "废弃矿井",
    "ancient city": "远古城市", "portal": "传送门", "spawner": "刷怪笼",
    "spawn point": "出生点", "spawn": "出生点", "biome": "生物群系",
    "chunk": "区块", "seed": "种子", "mob": "怪物", "mobs": "怪物",
    "boss": "首领", "raid": "袭击", "farm": "农场", "base": "基地",
    "house": "房子", "arena": "竞技场", "guild": "公会", "clan": "氏族",
    "party": "队伍", "team": "队伍", "teammate": "队友", "squad": "小队",
    "rank": "权限组", "admin": "管理员", "administrator": "管理员",
    "moderator": "管理员", "staff": "工作人员", "owner": "服主",
    "ban": "封禁", "banned": "被封禁", "mute": "禁言", "muted": "被禁言",
    "kick": "踢出", "kicked": "被踢出", "warn": "警告",
    "report": "举报", "hacker": "外挂", "hackers": "外挂", "cheat": "作弊",
    "cheater": "作弊者", "lag": "卡顿", "laggy": "卡", "ping": "延迟",
    "fps": "帧数", "tps": "服务器流畅度", "giveaway": "抽奖",
    "crate": "宝箱", "key": "钥匙", "kit": "装备包", "token": "代币",
    "coins": "金币", "auction house": "拍卖行", "shop": "商店",
    "trade": "交易", "trading": "交易", "sell": "出售", "selling": "出售",
    "buy": "购买", "buying": "收购", "price": "价格", "cheap": "便宜",
    "expensive": "贵", "deal": "划算", "scam": "诈骗", "scammer": "骗子",
    "whisper": "私聊", "message": "私聊", "private message": "私聊",
    "survival": "生存", "creative": "创造", "hardcore": "极限",
    "skyblock": "空岛生存", "bedwars": "起床战争", "anarchy": "无政府",
    "event": "活动", "restart": "重启", "maintenance": "维护",
    "update": "更新", "season": "赛季", "quest": "任务", "npc": "NPC",
}

# 3) 常见整句（命中就不联网，秒出结果）
PHRASES = {
    "gg": "打得好", "gg wp": "打得好，干得漂亮", "gg ez": "轻松拿下",
    "ez": "太简单了", "ty": "谢谢", "thx": "谢谢", "tysm": "太感谢了",
    "np": "不客气", "wb": "欢迎回来", "lol": "哈哈", "lmao": "哈哈哈",
    "rofl": "哈哈哈", "omg": "天哪", "wtf": "什么鬼", "brb": "马上回来",
    "afk": "挂机中", "hi": "你好", "hello": "你好", "hey": "嗨",
    "yo": "哟", "sup": "怎么样", "welcome": "欢迎", "nice": "不错",
    "cool": "酷", "ok": "好的", "okay": "好的", "yes": "是", "no": "不",
    "sorry": "抱歉", "sry": "抱歉", "help": "求助", "help me": "帮帮我",
    "gl": "祝好运", "hf": "玩得开心", "gl hf": "祝好运，玩得开心",
    "gtg": "我得走了", "cya": "再见", "bye": "再见", "rip": "节哀",
    "idk": "不知道", "noob": "菜鸟", "ez clap": "轻松拿下",
    "wp": "干得漂亮", "gf": "打得不错", "1": "1", "0": "0",
    "anyone here": "有人在吗", "anyone": "有人吗",
}


# 4) 多词黑话（整段替换，比单词替换更准）
PHRASE_PRE = [
    (r"\bez clap\b", "easy win"), (r"\bget rekt\b", "you got destroyed"),
    (r"\bgg wp\b", "good game well played"), (r"\bgg ez\b", "good game easy"),
    (r"\bwb bro\b", "welcome back bro"), (r"\bno u\b", "no, you"),
    (r"\bwanna\b", "want to"), (r"\bgonna\b", "going to"),
    (r"\bbrb\b", "be right back"), (r"\bafk\b", "away from keyboard"),
    (r"\bnvm\b", "never mind"), (r"\bomw\b", "on my way"),
    (r"\bic\b", "i see"), (r"\bikr\b", "i know right"),
    (r"\bftw\b", "for the win"), (r"\bimo\b", "in my opinion"),
    (r"\bdont\b", "do not"), (r"\bdoesnt\b", "does not"),
    (r"\bcant\b", "cannot"), (r"\bwont\b", "will not"),
    (r"\bim\b", "i am"), (r"\bive\b", "i have"), (r"\bpls\b", "please"),
    (r"\bthx\b", "thanks"), (r"\bsmh\b", "shaking my head"),
    (r"\bgl hf\b", "good luck have fun"), (r"\b1v1 me\b", "fight me one on one"),
]

# 5) 机器翻译常见的错误中文术语 -> 正确译名（译后再纠正一遍）
ZH_FIX = {
    "产卵点": "出生点", "产卵": "出生点", "产卵地": "出生点",
    "胸牌": "胸甲", "胸铠": "胸甲", "护胸": "胸甲",
    "祖母绿": "绿宝石", "祖母绿宝石": "绿宝石",
    "爬行者": "苦力怕", "苦力霸": "苦力怕", "内瑟赖特": "下界合金",
    "地狱石": "下界合金", "下界石": "下界合金", "尼德莱特": "下界合金",
    "硬币": "金币", "钱币": "金币", "信用点": "金币",
    "下界合金套": "下界合金套装", "翅膀": "鞘翅", "鞘翅膜": "鞘翅",
    "末地龙": "末影龙", "末影螨虫": "末影螨",
    "凋零": "凋灵", "凋零怪": "凋灵", "凋灵骷髅头": "凋灵骷髅头颅",
    "僵尸猪人": "僵尸猪灵", "猪人": "猪灵", "猪林": "猪灵",
    "掠夺兽": "劫掠兽", "掠夺者队长": "袭击队长",
    "村庄居民": "村民", "铁傀儡人": "铁傀儡",
    "钻石剑" : "钻石剑", "钻石胸甲": "钻石胸甲",
    "交易行": "拍卖行", "拍卖": "拍卖行",
    "私信我": "私聊我", "私信": "私聊", "密语": "私聊",
    "小声点": "私聊我", "低声说": "私聊",
    "破坏我的底座": "拆我的家", "底座": "基地",
    "基地建设": "建基地", "刷怪笼子": "刷怪笼",
    "突袭": "袭击", "伟大的袭击": "精彩的袭击",
    "重生点": "出生点", "重生的地方": "出生点",
    "服务器在10分钟内重启": "服务器将在 10 分钟后重启",
    "有3个祖母绿交易": "有 3 个绿宝石交易",
    "鼓掌": "拿下", "拍手": "拿下", "被摧毁": "被虐",
    "新手": "菜鸟", "菜鸟玩家": "菜鸟",
    "经验值修补": "经验修补", "经验修补术": "经验修补",
    "精准触摸": "精准采集", "丝绸之触": "精准采集",
    "时运附魔": "时运", "耐久度": "耐久",
    "下界要塞堡垒": "下界要塞", "堡垒遗迹": "堡垒遗迹",
    "末地传送门框": "末地传送门框架",
    "凋灵之星": "下界之星", "地狱之星": "下界之星",
    "末影珍珠传送": "末影珍珠", "潜影盒箱": "潜影盒",
    "刷怪塔": "刷怪塔", "经验农场": "经验农场",
    "套装装": "套装", "装各": "各", "黑客": "外挂", "作弊者": "外挂",
    "杀气": "杀戮光环", "杀灵气": "杀戮光环", "杀戮灵气": "杀戮光环",
    "飞行作弊": "飞行挂", "穿墙作弊": "穿墙挂", "价格检查": "问价",
    "小声点": "私聊我", "小声": "私聊", "悄悄话": "私聊",
}


def has_cjk(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in s)


def cjk_ratio(s: str) -> float:
    if not s:
        return 0.0
    n = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    return n / len(s)


# 6) 中->英 回话时，先把中文术语换成英文，翻出来老外才看得懂
ZH2EN = {
    "末影龙": "Ender Dragon", "末影人": "Enderman", "苦力怕": "Creeper",
    "下界合金": "netherite", "鞘翅": "elytra", "潜影盒": "shulker box",
    "绿宝石": "emerald", "钻石": "diamond", "铁锭": "iron ingot",
    "金锭": "gold ingot", "黑曜石": "obsidian", "附魔": "enchant",
    "附魔台": "enchanting table", "刷怪笼": "spawner", "工作台": "crafting table",
    "熔炉": "furnace", "信标": "beacon", "不死图腾": "totem of undying",
    "金苹果": "golden apple", "末影珍珠": "ender pearl", "末影之眼": "ender eye",
    "出生点": "spawn point", "基地": "base", "拆家": "grief", "袭击": "raid",
    "胸甲": "chestplate", "头盔": "helmet", "护腿": "leggings", "靴子": "boots",
    "剑": "sword", "镐": "pickaxe", "盾牌": "shield", "三叉戟": "trident",
    "村庄": "village", "要塞": "stronghold", "地牢": "dungeon",
    "下界": "the Nether", "末地": "the End", "主世界": "overworld",
    "服务器": "server", "管理员": "admin", "外挂": "hacker", "作弊": "cheat",
    "封禁": "ban", "禁言": "mute", "举报": "report", "组队": "team up",
    "队伍": "party", "公会": "guild", "交易": "trade", "出售": "selling",
    "收购": "buying", "价格": "price", "便宜": "cheap", "贵": "expensive",
    "私聊": "pm me", "拍卖行": "auction house", "商店": "shop",
    "重生": "respawn", "传送": "teleport", "传送门": "portal",
    "生存": "survival", "创造": "creative", "空岛": "skyblock",
    "起床战争": "bedwars", "经验": "exp", "等级": "level",
    "卡": "lag", "延迟": "ping", "外挂狗": "hacker",
}


def zh_to_en_terms(text: str) -> str:
    for zh, en in sorted(ZH2EN.items(), key=lambda kv: -len(kv[0])):
        # 前后留空格，避免 "有人一起" 被拼成 "Anyonetogether"
        text = text.replace(zh, f" {en} ")
    return re.sub(r"\s{2,}", " ", text).strip()


def expand_slang(text: str) -> str:
    """把黑话缩写展开成完整英文，提升机器翻译质量。"""
    for pat, rep in PHRASE_PRE:
        text = re.sub(pat, rep, text, flags=re.I)

    def repl(m):
        w = m.group(0)
        low = w.lower()
        return SLANG.get(low, w)

    # 只替换独立单词，避免误伤（如 "op" 在 "opening" 里）
    return re.sub(r"[A-Za-z']+", repl, text)


def fix_terms(text: str) -> str:
    """翻译后：残留英文术语换中文 + 纠正机器翻译的错误译名。"""
    if not text:
        return text
    items = sorted(TERMS.items(), key=lambda kv: -len(kv[0]))
    for en, zh in items:
        if en in text and en.isascii():
            text = re.sub(r"(?<![A-Za-z])" + re.escape(en) + r"(?![A-Za-z])",
                          zh, text, flags=re.I)
    for _ in range(2):   # 跑两遍，处理「A→B，B→C」这种连锁纠正
        for wrong, right in sorted(ZH_FIX.items(), key=lambda kv: -len(kv[0])):
            if wrong in text and wrong != right:
                text = text.replace(wrong, right)
    # 中英之间补空格，读起来更舒服（Steve加入了游戏 -> Steve 加入了游戏）
    text = re.sub(r"(?<=[A-Za-z0-9])(?=[\u4e00-\u9fff])", " ", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])(?=[A-Za-z0-9])", " ", text)
    # 清理机器翻译常见小毛病
    text = text.replace("，。", "。").replace("。。", "。")
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


# ================================================================ 翻译引擎
class Translator:
    """多通道翻译，自动降级；带内存+磁盘缓存。"""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.cache = {}
        self.lock = threading.Lock()
        self.dirty = False
        self.fails = {}          # 通道 -> 连续失败次数
        self.cooldown = {}       # 通道 -> 冷却到期时间
        self.last_use = {}
        self.pool = ThreadPoolExecutor(max_workers=4)
        self._load_cache()
        self.stats = {"ok": 0, "fail": 0, "cached": 0}

    # ---------- 缓存
    def _load_cache(self):
        try:
            if CACHE_PATH.exists():
                self.cache = json.loads(CACHE_PATH.read_text("utf-8"))
                if not isinstance(self.cache, dict):
                    self.cache = {}
        except Exception:
            self.cache = {}

    def save_cache(self):
        with self.lock:
            if not self.dirty:
                return
            data = dict(self.cache)
            self.dirty = False
        try:
            if len(data) > 6000:
                data = dict(list(data.items())[-6000:])
            CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
        except Exception:
            pass

    # ---------- 各通道
    def _post_json(self, url, payload, headers=None, timeout=8):
        h = {"Content-Type": "application/json",
             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0.0.0 Safari/537.36",
             "Accept": "application/json, text/plain, */*"}
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers=h, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def ch_volc(self, text, src, tgt):
        """火山引擎（豆包）网页版翻译，免密钥。"""
        lang = {"en": "en", "zh": "zh"}
        data = self._post_json(
            "https://translate.volcengine.com/crx/translate/v1/",
            {"source_language": lang.get(src, "en"),
             "target_language": lang.get(tgt, "zh"),
             "text": text},
            {"Origin": "https://translate.volcengine.com",
             "Referer": "https://translate.volcengine.com/"})
        out = (data.get("translation") or "").strip()
        if not out:
            raise ValueError("empty")
        return out

    def ch_mymemory(self, text, src, tgt):
        pair = {"en": "en", "zh": "zh-CN"}
        url = ("https://api.mymemory.translated.net/get?q="
               + urllib.parse.quote(text)
               + f"&langpair={pair.get(src,'en')}|{pair.get(tgt,'zh-CN')}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        out = (data.get("responseData", {}).get("translatedText") or "").strip()
        if not out or out.upper() == text.upper():
            raise ValueError("empty")
        return out

    def ch_youdao(self, text, src, tgt):
        lang = {"en": "en", "zh": "zh-CHS"}
        url = ("https://aidemo.youdao.com/trans?q=" + urllib.parse.quote(text)
               + f"&from={lang.get(src,'en')}&to={lang.get(tgt,'zh-CHS')}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        out = (data.get("translation") or [""])[0].strip()
        if not out:
            raise ValueError("empty")
        return out

    def ch_llm(self, text, src, tgt):
        """OpenAI 兼容接口（DeepSeek / 通义 / 智谱 / 硅基流动 / Ollama…）。"""
        key = (self.cfg.get("llm_key") or "").strip()
        base = (self.cfg.get("llm_base") or "").strip().rstrip("/")
        if not key or not base:
            raise ValueError("未配置大模型")
        if tgt == "zh":
            sys_p = ("你是 Minecraft 玩家聊天翻译器。把英文玩家聊天翻译成简洁自然的中文口语。"
                     "游戏术语用国服译名（netherite=下界合金，elytra=鞘翅，creeper=苦力怕，"
                     "grief=拆家，spawn=出生点，raid=袭击，base=基地）。"
                     "保留玩家名、数字、坐标、物品数量。只输出译文，不要任何解释。")
        else:
            sys_p = ("Translate Chinese Minecraft player chat into short natural English "
                     "as players actually type in global chat. Keep player names and numbers. "
                     "Output only the translation.")
        data = self._post_json(
            base + "/chat/completions",
            {"model": self.cfg.get("llm_model") or "deepseek-chat",
             "messages": [{"role": "system", "content": sys_p},
                          {"role": "user", "content": text}],
             "temperature": 0.2, "max_tokens": 300},
            {"Authorization": "Bearer " + key}, timeout=20)
        out = data["choices"][0]["message"]["content"].strip()
        if not out:
            raise ValueError("empty")
        return out.strip('"')

    # ---------- 主流程
    def channel_order(self):
        ch = self.cfg.get("channel")
        all_ch = ["llm", "volc", "mymemory", "youdao"]
        if ch == "auto":
            # 有 key 优先大模型
            if (self.cfg.get("llm_key") or "").strip():
                return all_ch
            return ["volc", "mymemory", "youdao"]
        return [ch] + [c for c in all_ch if c != ch]

    def translate(self, text: str, src="en", tgt="zh") -> str:
        raw = text.strip()
        if not raw:
            return ""
        # 已经是中文就不用翻（只有少量汉字混在英文里时仍然翻）
        if tgt == "zh" and cjk_ratio(raw) > 0.3:
            return raw

        key = f"{src}>{tgt}|{raw.lower()}"
        with self.lock:
            if key in self.cache:
                self.stats["cached"] += 1
                return self.cache[key]

        # 整句词典（仅英译中）
        if tgt == "zh":
            low = raw.lower().strip(" .!?~")
            if low in PHRASES:
                with self.lock:
                    self.cache[key] = PHRASES[low]
                    self.dirty = True
                return PHRASES[low]

        prepared = expand_slang(raw) if src == "en" else zh_to_en_terms(raw)

        now = time.time()
        last_err = None
        for name in self.channel_order():
            if self.cooldown.get(name, 0) > now:
                continue
            fn = getattr(self, "ch_" + name, None)
            if not fn:
                continue
            # 同通道最小间隔，避免被限流
            gap = {"youdao": 1.0, "mymemory": 0.3}.get(name, 0.12)
            wait = gap - (now - self.last_use.get(name, 0))
            if wait > 0:
                time.sleep(min(wait, 1.2))
            try:
                out = fn(prepared, src, tgt)
                self.last_use[name] = time.time()
                if tgt == "zh":
                    out = fix_terms(out)
                with self.lock:
                    self.cache[key] = out
                    self.dirty = True
                    self.stats["ok"] += 1
                self.fails[name] = 0
                return out
            except Exception as e:
                last_err = e
                self.fails[name] = self.fails.get(name, 0) + 1
                if self.fails[name] >= 3:
                    self.cooldown[name] = time.time() + 180
                    self.fails[name] = 0
                continue

        # 全部通道失败：本地词表兜底
        self.stats["fail"] += 1
        if tgt == "zh":
            fallback = fix_terms(prepared)
            if fallback and fallback != prepared:
                return fallback
        return ""

    def translate_async(self, text, cb, src="en", tgt="zh"):
        self.pool.submit(lambda: cb(self.translate(text, src, tgt)))


# ================================================================ 日志监听
CHAT_RE = re.compile(r"\[CHAT\]\s?(.*)$")
TAG_RE = re.compile(r"^(?:\[[^\]]{1,32}\]\s*)+")
PLAYER_RE = re.compile(r"^<([^>]{1,32})>\s*(.*)$")
NAME_COLON_RE = re.compile(r"^([A-Za-z0-9_]{2,16})\s*[:»>]\s+(.+)$")
# NPC 说话：Madame Eleanor Q. Goldsworth III: xxx / The Handler: xxx
NPC_COLON_RE = re.compile(
    r"^([A-Z][A-Za-z0-9_'.-]*(?:\s+[A-Za-z0-9_.'\-]+){1,6})\s*:\s+(.+)$")
# § 在 GBK 编码的日志里会变成 ¡ì，两种都要去掉
COLOR_RE = re.compile(r"(?:[§\u00a7]|¡ì).?")
DECO_RE = re.compile(r"^[>»*=\-~_\s]+|[<«*=\-~_\s]+$")
# 进出服务器的提示（Hypixel 大厅会刷屏）
JOIN_RE = re.compile(
    r"(joined|left|quit) the (game|lobby|server|world)|has (joined|left) the game"
    r"|加入了游戏|退出了游戏|加入了大厅", re.I)


@dataclass
class ChatMsg:
    id: int
    ts: str
    name: str
    text: str
    is_system: bool = False
    zh: str = ""
    done: bool = False
    created: float = field(default_factory=time.time)


def parse_chat_line(line: str):
    """从一行日志里提取聊天内容，返回 (ts, name, text, is_system) 或 None。"""
    m = CHAT_RE.search(line)
    if not m:
        return None
    payload = COLOR_RE.sub("", m.group(1)).strip()
    if not payload:
        return None

    ts = ""
    mt = re.match(r"^\[(\d{2}:\d{2}:\d{2})\]", line)
    if mt:
        ts = mt.group(1)

    s = payload
    # 交替剥掉「装饰符」和「[头衔]/[等级]」，直到稳定
    # 例：[476] ? [MVP+] cheeselord1972: hi  ->  cheeselord1972: hi
    for _ in range(4):
        before = s
        s = re.sub(r"^[^A-Za-z0-9\[<]+", "", s).strip()
        t = TAG_RE.match(s)
        if t:
            s = s[t.end():].strip()
        if s == before:
            break

    mp = PLAYER_RE.match(s)
    if mp:
        return ts, mp.group(1), DECO_RE.sub("", mp.group(2)).strip(), False

    mc = NAME_COLON_RE.match(s)
    if mc:
        return ts, mc.group(1), DECO_RE.sub("", mc.group(2)).strip(), False

    mn = NPC_COLON_RE.match(s)
    if mn:
        return ts, mn.group(1).strip(), DECO_RE.sub("", mn.group(2)).strip(), False

    return ts, "系统", DECO_RE.sub("", s).strip(), True


# ---------------------------------------------------------------- 找游戏目录
def _log_of(root: Path) -> list:
    """一个游戏目录下所有可能的 latest.log（含版本隔离 / 实例隔离）。"""
    out = [root / "logs" / "latest.log"]
    for pat in ("versions/*/logs/latest.log",
                "instances/*/minecraft/logs/latest.log",
                "instances/*/.minecraft/logs/latest.log",
                "profiles/*/logs/latest.log"):
        try:
            out += list(root.glob(pat))
        except Exception:
            pass
    return out


def _known_roots() -> list:
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    cands = [
        Path(appdata) / ".minecraft",
        Path(appdata) / "PCL" / ".minecraft",
        Path(appdata) / ".hmcl" / ".minecraft",
        Path(appdata) / "HMCL" / ".minecraft",
        Path(appdata) / "PrismLauncher" / "instances",
        Path(appdata) / "com.modrinth.theseus" / "profiles",
        Path(local) / "Packages" / "Microsoft.MinecraftUWP_8wekyb3d8bbwe" / "LocalState",
    ]
    return [c for c in cands if c.exists()]


def _game_dir_from_process() -> list:
    """从正在运行的 javaw 命令行里读 --gameDir（最准）。"""
    try:
        cmd = ["powershell", "-NoProfile", "-Command",
               "(Get-CimInstance Win32_Process -Filter \"Name='javaw.exe'\").CommandLine"]
        out = subprocess.run(cmd, capture_output=True, timeout=8,
                             creationflags=0x08000000).stdout
        text = out.decode("mbcs", "replace") if isinstance(out, bytes) else str(out)
    except Exception:
        return []
    dirs = []
    for m in re.finditer(r'--gameDir\s+"?([^"\r\n]+)"?', text):
        d = m.group(1).strip().strip('"')
        if d and os.path.isdir(d):
            dirs.append(d)
    return dirs


_SKIP_DIRS = {"windows", "$recycle.bin", "system volume information",
              "program files", "program files (x86)", "programdata", "appdata",
              "node_modules", "$windows.~bt", "recovery", "perflogs", "msocache",
              "onedrivetemp", "temp", "tmp"}


def _deep_scan(budget=8.0, max_depth=4) -> list:
    """在磁盘上找 .minecraft 目录（后台跑，带时间上限）。"""
    t0 = time.time()
    found = []
    drives = [f"{d}:\\" for d in "CDEFGH" if os.path.exists(f"{d}:\\")]
    for drive in drives:
        stack = [(drive, 0)]
        while stack:
            if time.time() - t0 > budget:
                return found
            cur, depth = stack.pop()
            if depth > max_depth:
                continue
            try:
                with os.scandir(cur) as it:
                    for e in it:
                        try:
                            if not e.is_dir(follow_symlinks=False):
                                continue
                            low = e.name.lower()
                            if low == ".minecraft":
                                found.append(e.path)
                                continue
                            if low in _SKIP_DIRS or low.startswith("."):
                                continue
                            stack.append((e.path, depth + 1))
                        except OSError:
                            pass
            except OSError:
                pass
    return found


def _newest_log(paths) -> str:
    best, best_t = "", 0.0
    for p in paths:
        try:
            p = Path(p)
            if p.is_file():
                t = p.stat().st_mtime
                if t > best_t:
                    best, best_t = str(p), t
        except Exception:
            pass
    return best


def find_log_path(deep=False, extra_roots=None) -> str:
    """按优先级找最新被写过的 latest.log。"""
    roots = []
    roots += _game_dir_from_process()
    roots += [str(r) for r in _known_roots()]
    if extra_roots:
        roots += list(extra_roots)
    if deep:
        roots += _deep_scan()

    cands = []
    for r in dict.fromkeys(roots):
        cands += _log_of(Path(r))
    return _newest_log(cands)


def default_log_path() -> str:
    appdata = os.environ.get("APPDATA", "")
    return str(Path(appdata) / ".minecraft" / "logs" / "latest.log")


class LogWatcher(threading.Thread):
    def __init__(self, app, path: str):
        super().__init__(daemon=True)
        self.app = app
        self.path = Path(path)
        self.pos = 0
        self.stop_flag = False
        self.first = True
        self.enc = "utf-8"

    def _detect_enc(self):
        """中文系统上 Minecraft 日志是 GBK 写的，得跟着变。"""
        try:
            head = self.path.open("rb").read(400000)
        except Exception:
            return "utf-8"
        for enc in ("utf-8", "gbk"):
            try:
                head.decode(enc)
                return enc
            except Exception:
                continue
        return "utf-8"

    def run(self):
        while not self.stop_flag:
            try:
                if not self.path.exists():
                    self.app.on_log_state("未找到日志文件，等待游戏启动…")
                    self.first = True
                    time.sleep(1.5)
                    continue
                size = self.path.stat().st_size
                if self.first:
                    self.first = False
                    self.enc = self._detect_enc()
                    self.pos = size if self.app.cfg.get("read_from_end") else 0
                    self.app.on_log_state(f"监听中 · {self.path.parent.parent.name}")
                if size < self.pos:      # 日志被轮转/清空
                    self.pos = 0
                    self.enc = self._detect_enc()
                if size > self.pos:
                    with open(self.path, "rb") as f:
                        f.seek(self.pos)
                        chunk = f.read()
                        self.pos = f.tell()
                    for line in chunk.decode(self.enc, "replace").splitlines():
                        r = parse_chat_line(line)
                        if r:
                            ts, name, text, is_sys = r
                            self.app.on_chat(ts, name, text, is_sys)
            except Exception as e:
                self.app.on_log_state(f"日志读取异常：{type(e).__name__}")
            time.sleep(0.25)

    def stop(self):
        self.stop_flag = True


# ================================================================ 屏幕 OCR
try:
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    from winrt.windows.globalization import Language
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

OCR_PIP = ("pip install winrt-Windows.Media.Ocr winrt-Windows.Graphics.Imaging "
           "winrt-Windows.Storage.Streams winrt-Windows.Foundation "
           "winrt-Windows.Foundation.Collections winrt-Windows.Globalization winrt-runtime")


def ocr_is_useful(text: str) -> bool:
    """筛掉数字、坐标、符号这类没意义的东西。"""
    t = text.strip()
    if len(t) < 3 or has_cjk(t):
        return False
    letters = sum(ch.isalpha() for ch in t)
    if letters < 3:
        return False
    return letters / len(t) >= 0.45


class ScreenOCR:
    """用 Windows 系统自带 OCR 识别屏幕文字（免费、离线）。"""

    def __init__(self):
        self.engine = None
        self.err = ""

    def _ensure(self):
        if self.engine is not None:
            return True
        if not OCR_AVAILABLE:
            self.err = "未安装 OCR 组件"
            return False
        for tag in ("en-US", "en-GB", "en"):
            try:
                e = OcrEngine.try_create_from_language(Language(tag))
                if e:
                    self.engine = e
                    return True
            except Exception:
                pass
        try:
            e = OcrEngine.try_create_from_user_profile_languages()
            if e:
                self.engine = e
                return True
        except Exception:
            pass
        self.err = "系统没装英文 OCR 语言包"
        return False

    async def _ocr_async(self, img):
        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        stream = InMemoryRandomAccessStream()
        w = DataWriter(stream.get_output_stream_at(0))
        w.write_bytes(buf.getvalue())
        await w.store_async()
        await w.flush_async()
        stream.seek(0)
        dec = await BitmapDecoder.create_async(stream)
        bmp = await dec.get_software_bitmap_async()
        res = await self.engine.recognize_async(bmp)
        out = []
        for line in res.lines:
            words = list(line.words)
            if not words:
                continue
            r = words[0].bounding_rect
            out.append((line.text, int(r.x), int(r.y),
                        int(r.width), int(r.height)))
        return out

    def grab_and_ocr(self, bbox=None, scale=2):
        """截屏并识别，返回 [(text, x, y, w, h)]；失败返回 None。"""
        if not self._ensure():
            return None
        try:
            from PIL import ImageGrab
        except Exception:
            self.err = "缺少 Pillow（pip install pillow）"
            return None
        try:
            img = ImageGrab.grab(bbox=bbox, all_screens=True)
        except Exception:
            img = ImageGrab.grab(all_screens=True)
        img = img.convert("RGB")
        if scale > 1:
            from PIL import Image
            img = img.resize((img.width * scale, img.height * scale),
                             Image.LANCZOS)
        try:
            lines = asyncio.run(self._ocr_async(img))
        except Exception as e:
            self.err = f"{type(e).__name__}"
            return None
        if scale > 1:
            lines = [(t, x // scale, y // scale, w // scale, h // scale)
                     for t, x, y, w, h in lines]
        return lines


# ================================================================ Win32 工具
user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020


def get_hwnd(root):
    try:
        h = user32.GetParent(root.winfo_id())
        return h or root.winfo_id()
    except Exception:
        return 0


def set_click_through(hwnd, on: bool):
    try:
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if on:
            ex |= WS_EX_LAYERED | WS_EX_TRANSPARENT
        else:
            ex &= ~WS_EX_TRANSPARENT
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
        return True
    except Exception:
        return False


def dark_titlebar(win):
    """把窗口标题栏改成深色（Win10 1809+）。"""
    try:
        win.update_idletasks()
        hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
        for attr in (20, 19):        # DWMWA_USE_IMMERSIVE_DARK_MODE
            v = ctypes.c_int(1)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0:
                break
    except Exception:
        pass


def find_mc_window():
    """找 Minecraft 游戏窗口，返回 (left, top, right, bottom) 或 None。"""
    result = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value
            if "Minecraft" not in title and "我的世界" not in title:
                return True
            r = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            w, h = r.right - r.left, r.bottom - r.top
            if w < 400 or h < 300:
                return True
            result.append((r.left, r.top, r.right, r.bottom))
            return False
        except Exception:
            return True

    user32.EnumWindows(cb, 0)
    return result[0] if result else None


class HotkeyThread(threading.Thread):
    """注册全局热键（即使游戏全屏聚焦也能用）。"""

    def __init__(self, app, mapping):
        super().__init__(daemon=True)
        self.app = app
        self.mapping = mapping      # {vk: action}
        self.stop_flag = False
        self.ok = {}

    def run(self):
        MOD_NOREPEAT = 0x4000
        for vk, act in self.mapping.items():
            ok = user32.RegisterHotKey(None, vk, MOD_NOREPEAT, vk)
            self.ok[act] = bool(ok)
        msg = wt.MSG()
        while not self.stop_flag:
            got = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)
            if got:
                if msg.message == 0x0312:      # WM_HOTKEY
                    act = self.mapping.get(int(msg.wParam))
                    if act:
                        self.app.hotkey_q.put(act)
            else:
                time.sleep(0.04)
        for vk in self.mapping:
            try:
                user32.UnregisterHotKey(None, vk)
            except Exception:
                pass

    def stop(self):
        self.stop_flag = True


def get_dpi_scale() -> float:
    try:
        user32.SetProcessDPIAware()
        hdc = user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)   # LOGPIXELSX
        user32.ReleaseDC(0, hdc)
        return max(1.0, dpi / 96.0)
    except Exception:
        return 1.0


# ================================================================ 悬浮窗
class OverlayApp:
    def __init__(self, cfg: Config, log_path: str, demo=False):
        import tkinter as tk
        self.tk = tk
        self.cfg = cfg
        self.demo = demo
        self.scale = get_dpi_scale()
        try:
            self._prev_fg = user32.GetForegroundWindow()
        except Exception:
            self._prev_fg = 0

        # 第一次运行：按屏幕缩放放大默认窗口，并放到屏幕右侧（不挡左下角聊天框）
        if not cfg.existed:
            sw = user32.GetSystemMetrics(0)
            w, h = int(560 * self.scale), int(430 * self.scale)
            cfg.set("width", w)
            cfg.set("height", h)
            cfg.set("x", max(0, sw - w - int(30 * self.scale)))
            cfg.set("y", int(90 * self.scale))
        # 老版本用户：默认位置在左下角，会挡住聊天框，升级后挪到右侧一次
        elif int(cfg.get("cfg_ver") or 0) < 2:
            sw = user32.GetSystemMetrics(0)
            w = int(cfg.get("width"))
            cfg.set("x", max(0, sw - w - int(30 * self.scale)))
            cfg.set("y", int(90 * self.scale))
            cfg.set("cfg_ver", 2)
            cfg.save()

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.configure(bg=KEY_COLOR)
        self.root.attributes("-topmost", bool(cfg.get("always_on_top")))
        try:
            self.root.attributes("-alpha", float(cfg.get("opacity")))
        except Exception:
            pass
        try:
            self.root.attributes("-transparentcolor", KEY_COLOR)
        except Exception:
            pass

        self.w = int(cfg.get("width"))
        self.h = int(cfg.get("height"))
        self.root.geometry(f"{self.w}x{self.h}+{int(cfg.get('x'))}+{int(cfg.get('y'))}")

        self.translator = Translator(cfg)
        self.result_q = queue.Queue()
        self.reply_q = queue.Queue()
        self.hotkey_q = queue.Queue()
        self.pending = []
        self.msg_id = 0
        self.count = 0
        self.log_state = "正在查找游戏日志…"
        self.last_chat = ("", 0.0)
        self._hwnd = 0
        self._through = False

        # 屏幕 OCR
        self.ocr = ScreenOCR()
        self.ocr_q = queue.Queue()
        self._ocr_busy = False
        self._ocr_mem = {}
        self._auto_ocr = False
        self.ocr_state = ""

        self._build_ui()

        self.watcher = None
        if log_path and Path(log_path).is_file():
            self._start_watcher(log_path)
        else:
            self.log_state = "正在查找游戏日志…"
            self.root.after(400, self._auto_discover)

        self.hotkeys = HotkeyThread(self, {0x77: "toggle", 0x76: "through",
                                           0x78: "clear", 0x75: "settings",
                                           0x79: "scan", 0x7A: "cursor"})
        self.hotkeys.start()

        self.root.after(200, self._init_hwnd)
        self.root.after(120, self._tick)
        self.root.after(1000, self._follow_tick)
        self.root.after(60000, self._save_tick)
        if demo:
            self.root.after(600, self._demo_tick)

    # ---------------- 基础
    def s(self, v):
        return int(round(v * self.scale))

    def _init_hwnd(self):
        self._hwnd = get_hwnd(self.root)
        self._no_activate()
        # 如果启动时把焦点从游戏抢走了，还回去
        try:
            if self._prev_fg and user32.GetForegroundWindow() == self._hwnd:
                user32.SetForegroundWindow(self._prev_fg)
        except Exception:
            pass
        if self.cfg.get("click_through"):
            self.set_through(True)

    def _no_activate(self):
        """置顶但不抢游戏焦点（否则一启动就把键盘从游戏里抢走）。"""
        try:
            if not self._hwnd:
                self._hwnd = get_hwnd(self.root)
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
            user32.SetWindowPos(self._hwnd, -1, 0, 0, 0, 0,
                                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        except Exception:
            pass

    # ---------------- 界面
    def _build_ui(self):
        tk = self.tk
        self.cv = tk.Canvas(self.root, bg=KEY_COLOR, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)

        fs = int(self.cfg.get("font_size"))
        self.f_name = (FONT_CN, self.s(fs), "bold")
        self.f_zh = (FONT_CN, self.s(fs))
        self.f_orig = (FONT_CN, max(7, self.s(fs - 2)))
        self.f_sys = (FONT_CN, max(7, self.s(fs - 1)))
        self.f_ui = (FONT_CN, max(8, self.s(9)))

        # 聊天文本区
        self.text = tk.Text(self.root, bg=PANEL, fg=TEXT_MAIN, bd=0,
                            highlightthickness=0, wrap="word", cursor="arrow",
                            padx=0, pady=0, spacing1=self.s(3), spacing3=self.s(2),
                            insertwidth=0, font=self.f_zh)
        self.text.tag_configure("name", foreground=ACCENT, font=self.f_name)
        self.text.tag_configure("zh", foreground=TEXT_MAIN, font=self.f_zh)
        self.text.tag_configure("orig", foreground=TEXT_DIM, font=self.f_orig)
        self.text.tag_configure("sys", foreground=TEXT_SYS, font=self.f_sys)
        self.text.tag_configure("hint", foreground="#5c6774", font=self.f_ui)
        self.text.tag_configure("time", foreground="#4f5a66", font=self.f_orig)
        self.text.configure(state="disabled")
        self.text.bind("<MouseWheel>",
                       lambda e: self.text.yview_scroll(int(-e.delta / 120), "units"))

        # 顶栏
        self.top = tk.Frame(self.root, bg=PANEL)
        self.title = tk.Label(self.top, text="MC 翻译", bg=PANEL, fg="#c9d3de",
                              font=(FONT_CN, self.s(10), "bold"), anchor="w")
        self.title.pack(side="left", padx=(0, self.s(8)))
        self.drag_widgets = [self.top, self.title, self.cv]

        # 聊天 / 屏幕 两个标签
        self.mode = "chat"
        self.tabs = {}
        for key, label in [("chat", "聊天"), ("screen", "屏幕")]:
            lb = tk.Label(self.top, text=label, bg=PANEL, fg=TEXT_DIM,
                          font=(FONT_CN, self.s(9)), padx=self.s(7), pady=1,
                          cursor="hand2")
            lb.pack(side="left", padx=(0, self.s(3)))
            lb.bind("<Button-1>", lambda e, k=key: self._set_mode(k))
            self.tabs[key] = lb

        self.btns = {}
        for key, label, cmd in [("settings", "设置", self.open_settings),
                                ("clear", "清屏", self.clear),
                                ("through", "穿透", self.toggle_through),
                                ("scan", "扫描", lambda: self.scan_screen()),
                                ("hide", "—", self.toggle_show),
                                ("close", "×", self.quit)]:
            b = tk.Label(self.top, text=label, bg=PANEL, fg=TEXT_DIM,
                         font=(FONT_CN, self.s(9)), padx=self.s(5), pady=1,
                         cursor="hand2")
            b.pack(side="right", padx=(self.s(1), 0))
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>", lambda e, w=b: w.configure(bg=BTN_HOVER, fg="#ffffff"))
            b.bind("<Leave>", lambda e, w=b: w.configure(bg=PANEL, fg=TEXT_DIM))
            self.btns[key] = b

        # 屏幕翻译用的第二个文本区
        self.text2 = tk.Text(self.root, bg=PANEL, fg=TEXT_MAIN, bd=0,
                             highlightthickness=0, wrap="word", cursor="arrow",
                             padx=0, pady=0, spacing1=self.s(3), spacing3=self.s(2),
                             insertwidth=0, font=self.f_zh)
        self.text2.tag_configure("ocr_zh", foreground=TEXT_MAIN, font=self.f_zh)
        self.text2.tag_configure("ocr_en", foreground=TEXT_DIM, font=self.f_orig)
        self.text2.tag_configure("ocr_head", foreground="#5c6774", font=self.f_ui)
        self.text2.tag_configure("hint", foreground="#5c6774", font=self.f_ui)
        self.text2.configure(state="disabled")
        self.text2.bind("<MouseWheel>",
                        lambda e: self.text2.yview_scroll(int(-e.delta / 120), "units"))

        # 底栏（中→英快捷回话）
        self.bottom = tk.Frame(self.root, bg=PANEL)
        self.entry = tk.Entry(self.bottom, bg="#1b2028", fg="#dfe6ee", bd=0,
                              highlightthickness=1, highlightbackground="#2f3742",
                              highlightcolor=ACCENT, insertbackground="#dfe6ee",
                              takefocus=0, font=(FONT_CN, self.s(10)))
        self.entry.pack(side="left", fill="both", expand=True, ipady=self.s(3))
        self.entry.insert(0, "输入中文，回车翻成英文并复制")
        self.entry.configure(fg="#5c6774")
        self.entry.bind("<FocusIn>", self._entry_focus_in)
        self.entry.bind("<FocusOut>", self._entry_focus_out)
        self.entry.bind("<Return>", lambda e: self.quick_reply())

        self.send_btn = tk.Label(self.bottom, text="翻译并复制", bg="#22303c",
                                 fg="#8fd0ea", font=(FONT_CN, self.s(9)),
                                 padx=self.s(8), pady=self.s(4), cursor="hand2")
        self.send_btn.pack(side="right", padx=(self.s(6), 0))
        self.send_btn.bind("<Button-1>", lambda e: self.quick_reply())

        # 状态栏
        self.status = tk.Label(self.root, text="", bg=PANEL, fg="#66727f",
                               font=(FONT_CN, max(7, self.s(8))), anchor="w")

        # 拖拽 / 缩放
        for w in self.drag_widgets:
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
        self.grip = tk.Label(self.root, text="◢", bg=PANEL, fg="#3d4753",
                             font=(FONT_CN, self.s(8)), cursor="size_nw_se")
        self.grip.bind("<ButtonPress-1>", self._resize_start)
        self.grip.bind("<B1-Motion>", self._resize_move)

        self.root.bind("<Configure>", lambda e: self._layout())
        self._layout()
        self._hint()
        self._set_mode("chat")

    def _set_mode(self, mode):
        self.mode = mode
        for k, lb in self.tabs.items():
            if k == mode:
                lb.configure(fg="#ffffff", bg="#232a33")
            else:
                lb.configure(fg=TEXT_DIM, bg=PANEL)
        self._last_size = None
        self._layout()
        self._update_status()
        if mode == "screen":
            self._screen_hint()

    def _layout(self):
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        if w < 50 or h < 50:
            return
        if getattr(self, "_last_size", None) == (w, h):
            return
        self._last_size = (w, h)
        pad = self.s(13)
        top_h = self.s(30)
        show_input = self.cfg.get("show_input") and self.mode == "chat"
        bottom_h = self.s(38) if show_input else 0
        status_h = self.s(20)

        self.cv.delete("all")
        r = self.s(13)
        self._round_rect(pad // 2, pad // 2, w - pad // 2, h - pad // 2, r,
                         fill=PANEL, outline=BORDER)
        self.cv.create_line(pad + self.s(4), pad // 2 + 1, w - pad - self.s(4),
                            pad // 2 + 1, fill="#1e2630")
        self.cv.create_line(pad, pad // 2 + top_h + self.s(2),
                            w - pad, pad // 2 + top_h + self.s(2),
                            fill="#1e2530")

        self.top.place(x=pad, y=pad // 2 + self.s(4), width=w - 2 * pad,
                       height=top_h)
        body_y = pad // 2 + top_h + self.s(6)
        body_h = h - top_h - bottom_h - status_h - pad - self.s(8)
        if self.mode == "chat":
            self.text2.place_forget()
            self.text.place(x=pad, y=body_y, width=w - 2 * pad, height=body_h)
        else:
            self.text.place_forget()
            self.text2.place(x=pad, y=body_y, width=w - 2 * pad, height=body_h)

        if show_input:
            self.bottom.place(x=pad, y=h - pad // 2 - status_h - bottom_h,
                              width=w - 2 * pad, height=bottom_h - self.s(6))
        else:
            self.bottom.place_forget()
        self.status.place(x=pad, y=h - pad // 2 - status_h + self.s(2),
                          width=w - 2 * pad - self.s(16), height=status_h)
        self.grip.place(x=w - pad - self.s(6), y=h - pad - self.s(4))
        self._update_status()

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
               x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
               x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.cv.create_polygon(pts, smooth=True, **kw)

    def _hint(self):
        self.text.configure(state="normal")
        self.text.insert("end", "\n  等待游戏聊天…\n", "hint")
        self.text.insert("end", "  进游戏后聊天会自动出现在这里（F6 设置 / F8 隐藏 / F7 穿透）\n", "hint")
        self.text.configure(state="disabled")

    # ---------------- 屏幕 OCR 翻译
    def _screen_hint(self):
        if self.text2.get("1.0", "end").strip():
            return
        t = self.text2
        t.configure(state="normal")
        t.insert("end", "\n  屏幕取词翻译\n", "hint")
        t.insert("end", "  F10 扫描游戏窗口 · F11 翻译鼠标附近的物品提示\n", "hint")
        t.insert("end", "  侧边栏、物品名、任务提示都能翻（走系统 OCR，个别字可能认错）\n", "hint")
        t.configure(state="disabled")

    def _panel_rect(self):
        try:
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            return (x, y, x + self.root.winfo_width(), y + self.root.winfo_height())
        except Exception:
            return None

    def _ocr_bbox(self, region):
        if region == "screen":
            return None
        if region == "cursor":
            pt = wt.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            dx, dy = self.s(420), self.s(300)
            return (pt.x - dx, pt.y - dy, pt.x + dx, pt.y + dy)
        r = find_mc_window()
        if r:
            return r
        return None

    def scan_screen(self, region=None):
        region = region or self.cfg.get("ocr_region") or "window"
        if not OCR_AVAILABLE:
            self._set_mode("screen")
            self._ocr_message("还没装 OCR 组件（只需装一次）\n\n"
                              "在文件夹里按住 Shift 右键 → 在此处打开 PowerShell，粘贴：\n\n"
                              + OCR_PIP)
            return
        if self._ocr_busy:
            return
        self._set_mode("screen")
        self._ocr_busy = True
        self.ocr_state = "识别中…"
        self._update_status()
        bbox = self._ocr_bbox(region)

        def work():
            lines = self.ocr.grab_and_ocr(bbox, scale=int(self.cfg.get("ocr_scale")))
            if lines is None:
                self.ocr_q.put(("err", self.ocr.err or "OCR 失败"))
                return
            panel = self._panel_rect()
            items, seen = [], set()
            for text, x, y, w2, h2 in lines:
                if panel:
                    px1, py1, px2, py2 = panel
                    # 排除自己这个悬浮窗，避免自我翻译
                    if x < px2 and x + w2 > px1 and y < py2 and y + h2 > py1:
                        continue
                t = re.sub(r"\s+", " ", text).strip(" .|·-—_")
                if not ocr_is_useful(t):
                    continue
                k = re.sub(r"[^a-z]", "", t.lower())
                if k in seen:
                    continue
                seen.add(k)
                items.append((t, x, y))
            items.sort(key=lambda it: (it[2] // 10, it[1]))
            items = items[:int(self.cfg.get("ocr_max"))]
            out = []
            for t, x, y in items:
                out.append((t, self._ocr_translate(t)))
            self.ocr_q.put(("ok", out))

        threading.Thread(target=work, daemon=True).start()

    def _ocr_translate(self, text):
        """OCR 每次结果都有细微差别，做个模糊去重，省接口调用。"""
        key = re.sub(r"[^a-z0-9]", "", text.lower())
        if key in self._ocr_mem:
            return self._ocr_mem[key]
        for k, v in list(self._ocr_mem.items())[-300:]:
            if abs(len(k) - len(key)) <= 3 and k and key:
                if difflib.SequenceMatcher(None, k, key).ratio() > 0.87:
                    self._ocr_mem[key] = v
                    return v
        zh = self.translator.translate(text)
        self._ocr_mem[key] = zh
        if len(self._ocr_mem) > 800:
            for k in list(self._ocr_mem)[:200]:
                self._ocr_mem.pop(k, None)
        return zh

    def _ocr_message(self, msg):
        t = self.text2
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("end", "\n  " + msg + "\n", "hint")
        t.configure(state="disabled")

    def _render_ocr(self, items):
        t = self.text2
        t.configure(state="normal")
        t.delete("1.0", "end")
        if not items:
            t.insert("end", "\n  这一屏没识别到需要翻译的英文\n", "hint")
        else:
            t.insert("end", f"  扫描到 {len(items)} 条 · {datetime.now():%H:%M:%S}\n\n",
                     "ocr_head")
            for en, zh in items:
                t.insert("end", (zh or en) + "\n", "ocr_zh")
                if zh and zh != en:
                    t.insert("end", en + "\n", "ocr_en")
                t.insert("end", "\n")
        t.configure(state="disabled")
        t.see("1.0")

    def toggle_auto_ocr(self):
        self._auto_ocr = not self._auto_ocr
        if self._auto_ocr:
            self._auto_tick()
        self._update_status()

    def _auto_tick(self):
        if not self._auto_ocr:
            return
        if not self._ocr_busy:
            self.scan_screen()
        gap = int(float(self.cfg.get("ocr_interval")) * 1000)
        self.root.after(max(1500, gap), self._auto_tick)

    # ---------------- 拖拽/缩放
    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        if not hasattr(self, "_dx"):
            return
        x = e.x_root - self._dx
        y = e.y_root - self._dy
        self.root.geometry(f"+{x}+{y}")
        self.cfg.set("x", x)
        self.cfg.set("y", y)
        # 记录相对游戏窗口的偏移，这样自动跟随时会保持你放的位置
        r = find_mc_window()
        if r:
            self.cfg.set("offset_x", r[2] - (x + self.root.winfo_width()))
            self.cfg.set("offset_y", y - r[1])

    def _resize_start(self, e):
        self._rw, self._rh = self.root.winfo_width(), self.root.winfo_height()
        self._rx, self._ry = e.x_root, e.y_root

    def _resize_move(self, e):
        if not hasattr(self, "_rw"):
            return
        w = max(self.s(320), self._rw + (e.x_root - self._rx))
        h = max(self.s(200), self._rh + (e.y_root - self._ry))
        self.root.geometry(f"{w}x{h}")
        self._last_size = None
        self._layout()
        self.cfg.set("width", w)
        self.cfg.set("height", h)

    # ---------------- 输入框占位
    def _entry_focus_in(self, _):
        if self.entry.get().startswith("输入中文"):
            self.entry.delete(0, "end")
            self.entry.configure(fg="#dfe6ee")

    def _entry_focus_out(self, _):
        if not self.entry.get().strip():
            self.entry.insert(0, "输入中文，回车翻成英文并复制")
            self.entry.configure(fg="#5c6774")

    # ---------------- 聊天接收
    def on_log_state(self, s):
        self.log_state = s

    def on_chat(self, ts, name, text, is_system):
        if not text:
            return
        if is_system and self.cfg.get("filter_system"):
            return
        # 进出大厅的刷屏提示
        if is_system and self.cfg.get("filter_join") and JOIN_RE.search(text):
            return
        if len(text) < 2:
            return
        # 去重（同一个人 2 秒内重复同一句）
        key = (name, text)
        if self.last_chat[0] == key and time.time() - self.last_chat[1] < 2:
            return
        self.last_chat = (key, time.time())

        self.msg_id += 1
        msg = ChatMsg(self.msg_id, ts or datetime.now().strftime("%H:%M:%S"),
                      name, text, is_system)
        self.pending.append(msg)

        # 已是中文就不用翻
        if cjk_ratio(text) > 0.3:
            msg.zh = text
            msg.done = True
            self._flush()
            return

        self.translator.translate_async(
            text, lambda zh, m=msg: self.result_q.put((m.id, zh)))

    def _tick(self):
        # 翻译结果
        try:
            while True:
                mid, zh = self.result_q.get_nowait()
                for m in self.pending:
                    if m.id == mid:
                        m.zh = zh or ""
                        m.done = True
                        break
        except queue.Empty:
            pass
        # 热键
        try:
            while True:
                act = self.hotkey_q.get_nowait()
                {"toggle": self.toggle_show, "through": self.toggle_through,
                 "clear": self.clear, "settings": self.open_settings,
                 "scan": lambda: self.scan_screen("window"),
                 "cursor": lambda: self.scan_screen("cursor")}.get(
                    act, lambda: None)()
        except queue.Empty:
            pass
        # 回话翻译结果
        try:
            while True:
                self._on_reply(self.reply_q.get_nowait())
        except queue.Empty:
            pass
        # OCR 结果
        try:
            while True:
                kind, payload = self.ocr_q.get_nowait()
                self._ocr_busy = False
                if kind == "err":
                    self.ocr_state = "OCR 失败：" + str(payload)
                    self._ocr_message("识别失败：" + str(payload))
                else:
                    self.ocr_state = f"已识别 {len(payload)} 条"
                    self._render_ocr(payload)
                self._update_status()
        except queue.Empty:
            pass

        self._flush()
        self._update_status()
        self.root.after(120, self._tick)

    def _flush(self):
        """按顺序显示（超时也放行，避免某条卡住整条队列）。"""
        now = time.time()
        while self.pending:
            m = self.pending[0]
            if not m.done and now - m.created < 8:
                break
            self.pending.pop(0)
            self._render(m)

    def _render(self, m: ChatMsg):
        t = self.text
        t.configure(state="normal")
        if self.count == 0:
            t.delete("1.0", "end")
        self.count += 1

        if m.is_system:
            t.insert("end", m.zh or m.text, "sys")
            t.insert("end", "\n")
        else:
            color = NAME_COLORS[hash(m.name) % len(NAME_COLORS)]
            tag = f"n_{m.name}"
            t.tag_configure(tag, foreground=color, font=self.f_name)
            t.insert("end", m.name, tag)
            t.insert("end", "  ", "zh")
            t.insert("end", (m.zh or m.text) + "\n", "zh")
            if self.cfg.get("show_original") and m.zh and m.zh != m.text:
                t.insert("end", " " * (len(m.name) + 2) + m.text + "\n", "orig")

        # 限制行数
        total = int(t.index("end-1c").split(".")[0])
        if total > int(self.cfg.get("max_lines")):
            t.delete("1.0", f"{total - int(self.cfg.get('max_lines')) // 2}.0")
        t.configure(state="disabled")
        t.see("end")
        self._update_status()

        try:
            with open(HISTORY_PATH, "a", encoding="utf-8") as f:
                f.write(f"[{m.ts}] {m.name}: {m.text}  =>  {m.zh}\n")
        except Exception:
            pass

    def _update_status(self):
        ch = {"auto": "自动", "volc": "火山", "mymemory": "MyMemory",
              "youdao": "有道", "llm": "大模型"}.get(self.cfg.get("channel"), "自动")
        if self.mode == "screen":
            region = {"window": "游戏窗口", "cursor": "鼠标附近",
                      "screen": "全屏"}.get(self.cfg.get("ocr_region"), "游戏窗口")
            auto = "自动 " if self._auto_ocr else ""
            txt = (f"屏幕翻译 · {region} · {auto}{self.ocr_state or '待扫描'}"
                   f"   ·   F10 扫描 / F11 取词")
        else:
            txt = f"{self.log_state}   ·   {ch}   ·   已译 {self.count} 条"
        t = getattr(self, "_toast", None)
        if t and time.time() < t[1]:
            txt = "✓ " + t[0]
        if txt != getattr(self, "_last_status", None):
            self._last_status = txt
            try:
                self.status.configure(text=txt)
            except Exception:
                pass

    def toast(self, msg, secs=2.0):
        self._toast = (msg, time.time() + secs)
        self._last_status = None
        self._update_status()

    # ---------------- 快捷回话
    def quick_reply(self):
        txt = self.entry.get().strip()
        if not txt or txt.startswith("输入中文"):
            return
        self.send_btn.configure(text="翻译中…", fg="#5c6774")

        def work():
            self.reply_q.put(self.translator.translate(txt, "zh", "en") or "")

        threading.Thread(target=work, daemon=True).start()

    def _on_reply(self, out: str):
        if out:
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(out)
                self.send_btn.configure(text="已复制 ✓", fg="#8ad98a")
            except Exception:
                self.send_btn.configure(text="翻译完成", fg="#8fd0ea")
        else:
            self.send_btn.configure(text="翻译失败", fg="#e08a8a")
        self.root.after(1600, lambda: self.send_btn.configure(
            text="翻译并复制", fg="#8fd0ea"))

    # ---------------- 功能
    def toggle_through(self):
        self.set_through(not self._through)

    def set_through(self, on):
        if not self._hwnd:
            self._hwnd = get_hwnd(self.root)
        ok = set_click_through(self._hwnd, on)
        self._through = bool(on and ok)
        self.cfg.set("click_through", self._through)
        if self._through:
            self.btns["through"].configure(text="穿透✓", fg="#f0b37e")
        else:
            self.btns["through"].configure(text="穿透", fg=TEXT_DIM)

    def toggle_show(self):
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self.root.attributes("-topmost", bool(self.cfg.get("always_on_top")))
            self.root.after(80, self._no_activate)
        else:
            self.root.withdraw()

    def clear(self):
        self.count = 0
        self.pending.clear()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self.text2.configure(state="normal")
        self.text2.delete("1.0", "end")
        self.text2.configure(state="disabled")
        self._ocr_mem.clear()
        self._hint()
        self._update_status()

    def _follow_tick(self):
        if self.cfg.get("follow_mc") and not getattr(self, "_dragging", False):
            r = find_mc_window()
            if r:
                left, top, right, bottom = r
                w = self.root.winfo_width()
                # 默认贴右侧，避开左下角的聊天框和底部物品栏
                x = right - w - int(self.cfg.get("offset_x"))
                y = top + int(self.cfg.get("offset_y"))
                x = max(left, x)
                if abs(self.root.winfo_x() - x) > 3 or abs(self.root.winfo_y() - y) > 3:
                    self.root.geometry(f"+{x}+{y}")
                    self.cfg.set("x", x)
                    self.cfg.set("y", y)
        self.root.after(1200, self._follow_tick)

    def _save_tick(self):
        self.cfg.save()
        self.translator.save_cache()

        # 日志文件没了 / 换版本换实例了，就重新找一次（后台做，不卡界面）
        def work():
            need = True
            if self.watcher:
                try:
                    p = Path(self.watcher.path)
                    need = (not p.exists()) or time.time() - p.stat().st_mtime > 300
                except Exception:
                    need = True
            if not need:
                return
            newer = find_log_path()
            if newer and (not self.watcher or newer != str(self.watcher.path)):
                self.root.after(0, lambda: self._start_watcher(newer))
            elif not self.watcher:
                self.root.after(0, self._auto_discover)

        threading.Thread(target=work, daemon=True).start()
        self.root.after(60000, self._save_tick)

    # ---------------- 设置窗口
    def open_settings(self):
        tk = self.tk
        BG = "#1a1e24"
        win = tk.Toplevel(self.root)
        win.title("设置")
        win.configure(bg=BG)
        win.attributes("-topmost", True)
        scr_h = win.winfo_screenheight()
        W, H = self.s(470), min(self.s(760), scr_h - self.s(60))
        x = min(max(0, self.root.winfo_x() + self.s(30)), win.winfo_screenwidth() - W - 10)
        y = min(max(0, self.root.winfo_y()), scr_h - H - self.s(50))
        win.geometry(f"{W}x{H}+{x}+{y}")
        win.resizable(False, True)

        # 底部按钮栏先占位，内容区滚动
        bar = tk.Frame(win, bg=BG)
        bar.pack(side="bottom", fill="x", padx=self.s(16), pady=self.s(12))

        wrap = tk.Frame(win, bg=BG)
        wrap.pack(side="top", fill="both", expand=True)
        cv = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        vsb = tk.Scrollbar(wrap, orient="vertical", command=cv.yview,
                           width=self.s(10), bg=BG, troughcolor="#20262e",
                           bd=0, relief="flat", activebackground="#3a4552")
        cv.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(cv, bg=BG)
        cv.create_window((0, 0), window=inner, anchor="nw",
                         width=W - self.s(26))
        inner.bind("<Configure>", lambda e: cv.configure(
            scrollregion=cv.bbox("all")))
        win.bind("<MouseWheel>", lambda e: cv.yview_scroll(
            int(-e.delta / 120), "units"))

        L = dict(bg=BG, fg="#cfd8e3", font=(FONT_CN, self.s(9)))
        E = dict(bg="#242b34", fg="#e6ecf3", insertbackground="#e6ecf3", bd=0,
                 highlightthickness=1, highlightbackground="#333c47",
                 highlightcolor=ACCENT, font=(FONT_CN, self.s(9)))
        row = [0]
        inner.grid_columnconfigure(0, weight=1)

        def label(t, top=8):
            tk.Label(inner, text=t, anchor="w", **L).grid(
                row=row[0], column=0, columnspan=2, sticky="w",
                padx=self.s(16), pady=(self.s(top), self.s(1)))
            row[0] += 1

        def section(t, top=16):
            tk.Label(inner, text=t, anchor="w", bg=BG, fg="#6f7d8c",
                     font=(FONT_CN, self.s(8), "bold")).grid(
                row=row[0], column=0, columnspan=2, sticky="w",
                padx=self.s(16), pady=(self.s(top), self.s(2)))
            row[0] += 1

        # ---- 翻译通道
        section("翻译通道", top=14)
        var_ch = tk.StringVar(value=self.cfg.get("channel"))
        ch_frame = tk.Frame(inner, bg=BG)
        ch_frame.grid(row=row[0], column=0, columnspan=2, sticky="w",
                      padx=self.s(14), pady=self.s(2))
        row[0] += 1
        chs = [("auto", "自动（推荐）"), ("volc", "火山/豆包"),
               ("mymemory", "MyMemory"), ("youdao", "有道"), ("llm", "大模型")]
        for i, (val, txt) in enumerate(chs):
            tk.Radiobutton(ch_frame, text=txt, variable=var_ch, value=val,
                           bg=BG, fg="#cfd8e3", selectcolor="#2a3340",
                           activebackground=BG, activeforeground="#ffffff",
                           font=(FONT_CN, self.s(9)), bd=0, highlightthickness=0
                           ).grid(row=i // 3, column=i % 3, sticky="w",
                                  padx=(0, self.s(14)), pady=1)

        # ---- 大模型
        section("大模型 API（可选，质量最好）")
        label("接口地址", top=6)
        e_base = tk.Entry(inner, **E)
        e_base.insert(0, self.cfg.get("llm_base"))
        e_base.grid(row=row[0], column=0, columnspan=2, sticky="we",
                    padx=self.s(16), pady=1)
        row[0] += 1
        label("API Key", top=6)
        e_key = tk.Entry(inner, **E, show="*")
        e_key.insert(0, self.cfg.get("llm_key"))
        e_key.grid(row=row[0], column=0, columnspan=2, sticky="we",
                   padx=self.s(16), pady=1)
        row[0] += 1
        label("模型名", top=6)
        e_model = tk.Entry(inner, **E)
        e_model.insert(0, self.cfg.get("llm_model"))
        e_model.grid(row=row[0], column=0, columnspan=2, sticky="we",
                     padx=self.s(16), pady=1)
        row[0] += 1

        # ---- 显示
        section("显示")
        var_orig = tk.BooleanVar(value=bool(self.cfg.get("show_original")))
        var_fsys = tk.BooleanVar(value=bool(self.cfg.get("filter_system")))
        var_fjoin = tk.BooleanVar(value=bool(self.cfg.get("filter_join")))
        var_follow = tk.BooleanVar(value=bool(self.cfg.get("follow_mc")))
        var_top = tk.BooleanVar(value=bool(self.cfg.get("always_on_top")))
        var_input = tk.BooleanVar(value=bool(self.cfg.get("show_input")))
        for txt, v in [("显示英文原文", var_orig),
                       ("过滤「加入/离开大厅」刷屏", var_fjoin),
                       ("过滤其它系统消息", var_fsys),
                       ("自动吸附到 Minecraft 窗口右侧", var_follow),
                       ("窗口置顶", var_top),
                       ("显示回话输入框", var_input)]:
            tk.Checkbutton(inner, text=txt, variable=v, bg=BG, fg="#cfd8e3",
                           selectcolor="#2a3340", activebackground=BG,
                           activeforeground="#ffffff", font=(FONT_CN, self.s(9)),
                           bd=0, highlightthickness=0, anchor="w").grid(
                row=row[0], column=0, columnspan=2, sticky="w",
                padx=self.s(13), pady=1)
            row[0] += 1

        # ---- 屏幕翻译
        section("屏幕翻译（物品栏 / 侧边栏 / 任务提示）")
        var_region = tk.StringVar(value=self.cfg.get("ocr_region"))
        rg = tk.Frame(inner, bg=BG)
        rg.grid(row=row[0], column=0, columnspan=2, sticky="w",
                padx=self.s(14), pady=self.s(2))
        row[0] += 1
        for i, (val, txt) in enumerate([("window", "整个游戏窗口"),
                                        ("cursor", "鼠标附近（看物品提示）"),
                                        ("screen", "整个屏幕")]):
            tk.Radiobutton(rg, text=txt, variable=var_region, value=val, bg=BG,
                           fg="#cfd8e3", selectcolor="#2a3340", activebackground=BG,
                           activeforeground="#fff", font=(FONT_CN, self.s(9)),
                           bd=0, highlightthickness=0).grid(
                row=i // 2, column=i % 2, sticky="w", padx=(0, self.s(14)))

        label("识别清晰度（越高越慢）", top=8)
        var_oscale = tk.StringVar(value=str(self.cfg.get("ocr_scale")))
        of = tk.Frame(inner, bg=BG)
        of.grid(row=row[0], column=0, columnspan=2, sticky="w",
                padx=self.s(14), pady=self.s(2))
        row[0] += 1
        for i, (val, txt) in enumerate([("1", "快"), ("2", "标准"), ("3", "最清楚")]):
            tk.Radiobutton(of, text=txt, variable=var_oscale, value=val, bg=BG,
                           fg="#cfd8e3", selectcolor="#2a3340", activebackground=BG,
                           activeforeground="#fff", font=(FONT_CN, self.s(9)),
                           bd=0, highlightthickness=0).pack(side="left",
                                                            padx=(0, self.s(14)))
        var_auto = tk.BooleanVar(value=False)
        tk.Checkbutton(inner, text="进入「屏幕」标签时自动反复扫描", variable=var_auto,
                       bg=BG, fg="#cfd8e3", selectcolor="#2a3340",
                       activebackground=BG, activeforeground="#fff",
                       font=(FONT_CN, self.s(9)), bd=0, highlightthickness=0,
                       anchor="w").grid(row=row[0], column=0, columnspan=2,
                                        sticky="w", padx=self.s(13), pady=1)
        row[0] += 1

        label("不透明度", top=10)
        sc_op = tk.Scale(inner, from_=0.35, to=1.0, resolution=0.01,
                         orient="horizontal", bg=BG, fg="#8b98a8",
                         troughcolor="#2a3340", highlightthickness=0, bd=0,
                         font=(FONT_CN, self.s(8)), length=self.s(330),
                         sliderrelief="flat", activebackground=ACCENT)
        sc_op.set(float(self.cfg.get("opacity")))
        sc_op.grid(row=row[0], column=0, columnspan=2, sticky="w", padx=self.s(16))
        row[0] += 1

        label("字号", top=8)
        sc_fs = tk.Scale(inner, from_=8, to=18, resolution=1, orient="horizontal",
                         bg=BG, fg="#8b98a8", troughcolor="#2a3340",
                         highlightthickness=0, bd=0, font=(FONT_CN, self.s(8)),
                         length=self.s(330), sliderrelief="flat",
                         activebackground=ACCENT)
        sc_fs.set(int(self.cfg.get("font_size")))
        sc_fs.grid(row=row[0], column=0, columnspan=2, sticky="w", padx=self.s(16))
        row[0] += 1

        # ---- 日志
        section("日志文件")
        logrow = tk.Frame(inner, bg=BG)
        logrow.grid(row=row[0], column=0, columnspan=2, sticky="we",
                    padx=self.s(16), pady=(self.s(2), self.s(16)))
        row[0] += 1
        e_log = tk.Entry(logrow, **E)
        e_log.insert(0, str(self.watcher.path) if self.watcher else "")
        e_log.pack(side="left", fill="x", expand=True)
        btn_detect = tk.Label(logrow, text="自动检测", bg="#242b34", fg="#8fd0ea",
                              font=(FONT_CN, self.s(8)), padx=self.s(8),
                              pady=self.s(3), cursor="hand2")
        btn_detect.pack(side="right", padx=(self.s(6), 0))

        def apply():
            self.cfg.set("channel", var_ch.get())
            self.cfg.set("llm_base", e_base.get().strip())
            self.cfg.set("llm_key", e_key.get().strip())
            self.cfg.set("llm_model", e_model.get().strip())
            self.cfg.set("show_original", bool(var_orig.get()))
            self.cfg.set("filter_system", bool(var_fsys.get()))
            self.cfg.set("filter_join", bool(var_fjoin.get()))
            self.cfg.set("follow_mc", bool(var_follow.get()))
            self.cfg.set("always_on_top", bool(var_top.get()))
            self.cfg.set("show_input", bool(var_input.get()))
            self.cfg.set("ocr_region", var_region.get())
            self.cfg.set("ocr_scale", int(var_oscale.get()))
            self.cfg.set("opacity", float(sc_op.get()))
            self.cfg.set("font_size", int(sc_fs.get()))
            newlog = e_log.get().strip()
            if newlog and os.path.isfile(newlog) and (
                    not self.watcher or str(self.watcher.path) != newlog):
                self._start_watcher(newlog)
            self.cfg.save()
            self.root.attributes("-alpha", float(sc_op.get()))
            self.root.attributes("-topmost", bool(var_top.get()))
            self._apply_fonts()
            self._last_size = None
            self._layout()
            if var_auto.get() and not self._auto_ocr:
                self.toggle_auto_ocr()
            elif not var_auto.get() and self._auto_ocr:
                self.toggle_auto_ocr()
            win.destroy()
            self.toast("设置已保存")

        def detect():
            e_log.delete(0, "end")
            e_log.insert(0, "正在扫描…")
            win.update_idletasks()

            def work():
                p = find_log_path(deep=True)
                self.root.after(0, lambda: (
                    e_log.delete(0, "end"),
                    e_log.insert(0, p if p else "没找到，请手动粘贴 latest.log 的完整路径")))

            threading.Thread(target=work, daemon=True).start()

        btn_detect.bind("<Button-1>", lambda e: detect())

        b1 = tk.Button(bar, text="保存", command=apply, bg="#2b6f8f", fg="#ffffff",
                       bd=0, font=(FONT_CN, self.s(9)), padx=self.s(18),
                       pady=self.s(4), activebackground="#3485a8",
                       activeforeground="#fff", cursor="hand2")
        b1.pack(side="right")
        b2 = tk.Button(bar, text="测试翻译", command=self.test_channel,
                       bg="#2a3340", fg="#cfd8e3", bd=0,
                       font=(FONT_CN, self.s(9)), padx=self.s(14), pady=self.s(4),
                       activebackground="#37424f", activeforeground="#fff",
                       cursor="hand2")
        b2.pack(side="right", padx=self.s(8))
        tk.Label(bar, text="F6 设置 · F7 穿透 · F8 隐藏 · F10 扫描",
                 bg=BG, fg="#5c6774", font=(FONT_CN, self.s(8))).pack(side="left")

        dark_titlebar(win)
        win.transient(self.root)
        win.grab_set()

    def _start_watcher(self, path):
        try:
            if self.watcher:
                self.watcher.stop()
        except Exception:
            pass
        self.watcher = LogWatcher(self, path)
        self.watcher.start()
        self.cfg.set("log_path", str(path))
        self.log_state = f"监听中 · {Path(path).parent.parent.name}"

    def _auto_discover(self, attempt=0):
        """后台找日志（首次可能要扫盘几秒），找到就接上。"""
        def work():
            p = find_log_path(deep=True)
            if p:
                self.root.after(0, lambda: self._start_watcher(p))
            else:
                self.root.after(0, lambda: self.on_log_state(
                    "没找到日志 · 点「设置」手动指定 latest.log"))
                if attempt < 3:
                    self.root.after(8000, lambda: self._auto_discover(attempt + 1))
        threading.Thread(target=work, daemon=True).start()

    def _apply_fonts(self):
        fs = int(self.cfg.get("font_size"))
        self.f_name = (FONT_CN, self.s(fs), "bold")
        self.f_zh = (FONT_CN, self.s(fs))
        self.f_orig = (FONT_CN, max(7, self.s(fs - 2)))
        self.f_sys = (FONT_CN, max(7, self.s(fs - 1)))
        self.text.configure(font=self.f_zh, spacing1=self.s(3), spacing3=self.s(2))
        self.text.tag_configure("name", font=self.f_name)
        self.text.tag_configure("zh", font=self.f_zh)
        self.text.tag_configure("orig", font=self.f_orig)
        self.text.tag_configure("sys", font=self.f_sys)

    def test_channel(self):
        def work():
            tr = Translator(self.cfg)
            s = "gg wp, anyone selling diamond sword? pm me"
            out = tr.translate(s)
            self.root.after(0, lambda: self._popup_result(out or "全部通道失败（网络不通？）"))
        threading.Thread(target=work, daemon=True).start()

    def _popup_result(self, text):
        tk = self.tk
        w = tk.Toplevel(self.root)
        w.title("测试结果")
        w.configure(bg="#1a1e24")
        w.attributes("-topmost", True)
        w.geometry(f"{self.s(400)}x{self.s(140)}+{self.root.winfo_x()+60}+{self.root.winfo_y()+60}")
        tk.Label(w, text="测试句：gg wp, anyone selling diamond sword? pm me",
                 bg="#1a1e24", fg="#8b98a8", font=(FONT_CN, self.s(8)),
                 wraplength=self.s(370), justify="left").pack(padx=14, pady=(14, 6))
        tk.Label(w, text=text, bg="#1a1e24", fg="#8ad98a",
                 font=(FONT_CN, self.s(10)), wraplength=self.s(370),
                 justify="left").pack(padx=14)

    # ---------------- 演示
    DEMO = [
        ("Steve", "gg wp everyone, that was a great raid"),
        ("Alex", "anyone selling netherite chestplate? paying 10 diamonds"),
        ("Notch", "wb bro, long time no see lol"),
        ("Herobrine", "pls dont grief my base, i spent 3 hours on it"),
        ("Steve", "brb 5 min, my mom is calling"),
        ("Alex", "there is a village at spawn with 3 emerald trades, come fast"),
        ("CreeperKing", "ez clap, get rekt noob"),
        ("Notch", "does anyone have spare elytra? i can trade totem"),
        ("Herobrine", "server restart in 10 minutes, save your stuff"),
        ("Steve", "lol he fell in lava with all his diamonds"),
    ]

    def _demo_tick(self):
        if not self.DEMO:
            return
        name, text = self.DEMO.pop(0)
        self.on_chat(datetime.now().strftime("%H:%M:%S"), name, text, False)
        if self.DEMO:
            self.root.after(1400, self._demo_tick)

    # ---------------- 退出
    def quit(self):
        try:
            self.cfg.save()
            self.translator.save_cache()
            if self.watcher:
                self.watcher.stop()
            self.hotkeys.stop()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.mainloop()


# ================================================================ 入口
def main():
    import argparse
    ap = argparse.ArgumentParser(description="MC 聊天实时翻译悬浮窗")
    ap.add_argument("--log", default="", help="指定 latest.log 路径")
    ap.add_argument("--demo", action="store_true", help="演示模式（示例聊天）")
    ap.add_argument("--check", action="store_true", help="测试翻译通道后退出")
    ap.add_argument("--reset", action="store_true", help="重置窗口位置")
    args = ap.parse_args()

    cfg = Config()
    if args.reset:
        cfg.set("x", 40)
        cfg.set("y", 300)
        cfg.save()

    if args.check:
        print("=" * 52)
        print(" 翻译通道测试")
        print("=" * 52)
        tr = Translator(cfg)
        sample = "gg wp, anyone selling diamond sword? pm me"
        for name in ["volc", "mymemory", "youdao"]:
            t0 = time.time()
            try:
                out = getattr(tr, "ch_" + name)(sample, "en", "zh")
                print(f"  [OK]   {name:<9} {int((time.time()-t0)*1000):>5}ms  {out}")
            except Exception as e:
                print(f"  [FAIL] {name:<9} {int((time.time()-t0)*1000):>5}ms  "
                      f"{type(e).__name__}: {str(e)[:60]}")
        if (cfg.get("llm_key") or "").strip():
            try:
                out = tr.ch_llm(sample, "en", "zh")
                print(f"  [OK]   llm       {out}")
            except Exception as e:
                print(f"  [FAIL] llm       {type(e).__name__}: {str(e)[:60]}")
        else:
            print("  [--]   llm       未配置 API Key（可选）")
        print()
        p = find_log_path()
        if not p:
            print(" 正在扫描磁盘找游戏目录…")
            p = find_log_path(deep=True)
        print(f" 日志文件：{p or '未找到'}")
        if p:
            print(f" 游戏目录：{Path(p).parent.parent}")
        return

    log_path = args.log or ""
    if not log_path:
        saved = cfg.get("log_path")
        if saved and Path(saved).is_file():
            log_path = saved
    if not log_path:
        log_path = find_log_path()
    app = OverlayApp(cfg, log_path, demo=args.demo)
    app.run()


if __name__ == "__main__":
    main()
