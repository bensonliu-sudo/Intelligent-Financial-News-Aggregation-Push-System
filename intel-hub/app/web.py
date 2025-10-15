# coding: utf-8
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional
import pandas as pd

import streamlit as st
import streamlit.components.v1 as components
# --- 放在 app/web.py 顶部 imports 下面 ---
from streamlit.components.v1 import html as st_html
from streamlit_autorefresh import st_autorefresh
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "intel.db"

st.set_page_config(page_title="Intel Hub - 实时看板", page_icon="🛰️", layout="wide")
# --- 仅加载一次的前端脚本：保存/恢复滚动位置 ---
components.html("""
<script>
(function() {
  const KEY = 'st-scroll-top';
  function save() {
    try {
      const y = document.scrollingElement ? document.scrollingElement.scrollTop : window.pageYOffset;
      localStorage.setItem(KEY, String(y||0));
    } catch(e){}
  }
  function restore() {
    try {
      const v = parseFloat(localStorage.getItem(KEY) || '0');
      if (!isNaN(v)) window.scrollTo({top: v, behavior: 'instant'});
    } catch(e){}
  }
  // 初次挂载立即恢复一次
  restore();
  // Streamlit 会频繁重绘：监听 DOM 变化后“再”恢复一次
  new MutationObserver(() => { restore(); }).observe(document.body, {subtree: true, childList: true});
  // 保存滚动
  window.addEventListener('scroll', save, {passive: true});
  window.addEventListener('beforeunload', save);
})();
</script>
""", height=0)
# ========== 样式 ==========
st.markdown("""
<style>
.radar{position:relative;width:20px;height:20px;margin-right:8px}
.radar:before,.radar:after{content:"";position:absolute;border:2px solid rgba(0,200,0,.7);border-radius:50%;inset:0;animation:pulse 1.6s linear infinite}
.radar:after{animation-delay:.8s}
@keyframes pulse{0%{transform:scale(.3);opacity:.9}70%{transform:scale(1.4);opacity:.1}100%{transform:scale(1.6);opacity:0}}
.header-small{color:#8b8b8b;font-size:.9rem;margin-top:2px}
.table-note{color:#909090;font-size:.85rem;margin-top:-6px}
.ih-table{width:100%;border-collapse:collapse;font-size:14px}
.ih-table th,.ih-table td{border-bottom:1px solid rgba(255,255,255,.08);padding:8px 10px;vertical-align:top}
.ih-table th{position:sticky;top:0;background:rgba(0,0,0,.25);backdrop-filter:blur(6px)}
.ih-link{color:inherit;text-decoration:none}
.ih-link:hover{text-decoration:underline}
.nowrap{white-space:nowrap}
.score-badge{padding:2px 8px;border-radius:999px;background:rgba(253,126,20,.15);border:1px solid rgba(253,126,20,.35)}
.small{font-size:12px;color:#a0a0a0}
/* 控制所有上下区块的垂直间距 */
div[data-testid="stVerticalBlock"] {
  gap: 0.2rem !important;          /* 默认大约是 1.5rem，可以缩小到 0.2–0.4 */
  margin-top: 0rem !important;     /* 去掉默认的额外 top 空白 */
  margin-bottom: 0rem !important;  /* 去掉默认的额外 bottom 空白 */
  padding-top: 0rem !important;
  padding-bottom: 0rem !important;
}
/* 表格容器与上方控件之间的空白 */
div[data-testid="stDataFrame"],
div[data-testid="stTable"] {
  margin-top: 0.3rem !important;   /* 默认接近 2rem，直接压缩 */
}
/* ========== 顶部空白（Header 占位）========== */
/* 方案A：直接隐藏 Streamlit 顶部 Header，占位高度变 0 */
header[data-testid="stHeader"]{
  height: 0px !important;
  visibility: hidden !important;
}
/* 有些版本 header 内还有一层 div，这里一起隐藏更稳妥 */
header[data-testid="stHeader"] > div { display: none !important; }

/* ========== 主容器上下内边距（整体上移的“总阀门”）========== */
/* 改这里可整体把内容往上“提”。建议从 0.6rem ~ 1rem 之间试 */
.block-container{
  padding-top: 0rem !important;   /* ← 顶部留白（越小越靠上）*/
  padding-bottom: 0.6rem !important;/* ↓ 底部留白 */
}

/* ========== 区块之间的垂直间距（行与行的空白）========== */
/* 页面里每一“行”之间默认 gap 很大，这里统一压缩 */
div[data-testid="stVerticalBlock"]{
  gap: 0.35rem !important;          /* 默认约 1.5rem → 改成更紧凑 */
  margin-top: -5rem !important;#此处是关键
  margin-bottom: 0rem !important;
  padding-top: 0rem !important;
  padding-bottom: 0rem !important;
}

/* ========== 表格/标题与上一行的间距再微调（可选）========== */
/* 如果“Headlines”标题或表格上面仍显得松，这里再压一压 */
h2, h3, .stMarkdown h2, .stMarkdown h3{
  margin-top: 0.4rem !important;
  margin-bottom: 0.4rem !important;
}
div[data-testid="stDataFrame"], div[data-testid="stTable"]{
  margin-top: 0.35rem !important;
}

/* ========== 顶部搜索区/状态区再压一压（可选）========== */
/* 如果你的“雷达 + 搜索框”那一行仍偏低，给那一行外面包一层容器
   并加 class="topbar"，然后这里单独调（不包也没关系，可删） */
.topbar{
  margin-top: 0rem !important;
  padding-top: 0rem !important;
}

/* 保留你之前的颜色/链接/表格样式（如有），放在这下面即可 …… */


</style>
""", unsafe_allow_html=True)

# ========== 顶栏控件 ==========
# left, mid, right, more = st.columns([1.1, 1.1, 1.6, 1.2], gap="small")
# with left:
#     min_score = st.slider("Min_threshold", 0, 100, 70, 5)
# # with mid:
# #     window_hours = st.slider("回看窗口（小时）", 1, 72, 48, 1)
# with right:
#     query = st.text_input("Search（headlines、sources、symbols、tags）", "")
# with more:
#     critical_only = st.checkbox("仅显示特别重要（≥critical）", value=False)

# col_a, col_b = st.columns([1, 2])
# with col_a:
#     auto_refresh = st.checkbox("自动刷新", value=True)
# with col_b:
#     interval = st.select_slider("刷新间隔（秒）", options=[5,10,15,20,30,45,60], value=10)

# # 软解决：整页刷新 + 保存/恢复滚动位置（感觉像“局部刷新”）
# # 使用局部 rerun，不触发整页 reload（滚动不丢）
# if auto_refresh:
#     st_autorefresh(interval=interval * 1000, key="auto-rerun")

components.html(f"""
<script>
(function(){{
  const KEY='ih_scroll_y';
  function saveScroll(){{ localStorage.setItem(KEY, String(window.scrollY||0)); }}
  window.addEventListener('beforeunload', saveScroll);
  document.addEventListener('visibilitychange', ()=>{{ if(document.hidden) saveScroll(); }});
  const y = parseFloat(localStorage.getItem(KEY)||'0');
  if (!isNaN(y)) {{
    // 等待 Streamlit 结构渲染完成再恢复滚动
    setTimeout(()=>window.scrollTo({{top:y, behavior:'instant'}}), 60);
  }}
}})();
</script>
""", height=0)

# ========== 雷达提示 ==========
# ========= 顶栏（雷达 + 状态 + 搜索）一行 =========
radar_col, status_col, search_col = st.columns([0.06, 0.34, 0.60], gap="small")

with radar_col:
    # 左侧小雷达
    st.markdown("<div class='radar'></div>", unsafe_allow_html=True)

with status_col:
    # 中间状态两行（你原来的两行都保留）
    st.markdown("**采集器运行中…** _collector tasks active_")
    st.markdown("<div class='header-small'></div>", unsafe_allow_html=True)

with search_col:
    # 右侧只保留搜索框（把标签折叠，减少占高）
    query = st.text_input(
        "关键词搜索（对标题、来源、symbols、tags）",
        key="q",
        placeholder="搜索关键词，支持标题/来源/symbols/tags",
        label_visibility="collapsed",
    )
st.markdown("---")

# ========== DB 工具 ==========
def _now_ms() -> int:
    import time
    return int(time.time() * 1000)

def _utc_ms_to_local_str(ms: int, tz_name: str) -> str:
    import datetime, pytz
    tz = pytz.timezone(tz_name)
    dt = datetime.datetime.utcfromtimestamp(ms/1000.0).replace(tzinfo=pytz.UTC)
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")

def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"数据库不存在: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def _fetch_unpushed(conn, since_ms: int, query: str) -> pd.DataFrame:
    sql = """
    SELECT id, ts_detected_utc, ts_published_utc, headline, source, link,
           market, symbols, categories, tags, score, pushed,
           thread_key
    FROM events
    WHERE ts_detected_utc >= ? AND IFNULL(pushed,0)=0
    """
    params = [since_ms]
    if query.strip():
        like = f"%{query.strip()}%"
        sql += " AND (headline LIKE ? OR source LIKE ? OR symbols LIKE ? OR tags LIKE ?)"
        params += [like, like, like, like]
    sql += " ORDER BY ts_detected_utc DESC LIMIT 200"
    return pd.read_sql_query(sql, conn, params=params)

def _fetch_high(conn, since_ms: int, min_score: int, query: str, critical_only: bool) -> pd.DataFrame:
    sql = """
    SELECT id, ts_detected_utc, ts_published_utc, headline, source, link,
           market, symbols, categories, tags, score, pushed,
           thread_key
    FROM events
    WHERE ts_detected_utc >= ? AND score >= ?
    """
    params = [since_ms, min_score]
    if critical_only:
        sql += " AND score >= 90"   # 你原来的“特别重要”逻辑
    if query.strip():
        like = f"%{query.strip()}%"
        sql += " AND (headline LIKE ? OR source LIKE ? OR symbols LIKE ? OR tags LIKE ?)"
        params += [like, like, like, like]
    sql += " ORDER BY score DESC, ts_detected_utc DESC LIMIT 500"
    return pd.read_sql_query(sql, conn, params=params)

def _top_count(df: pd.DataFrame, col: str, n: int = 10) -> pd.DataFrame:
    if col not in df:
        return pd.DataFrame(columns=[col, "count"])
    s = df[col].astype(str).str.split(r"[;,|\s]+", regex=True).explode()
    s = s[s.str.len() > 0]
    return s.value_counts().reset_index().rename(columns={"index": col, 0: "count"}).head(n)
# --- 在查询出 df_recent（或 df_top）的地方，渲染之前插入： ---
def _dedupe_latest(df: pd.DataFrame) -> pd.DataFrame:
    """
    强制按归一化标题去重：
      - 不考虑来源(source)
      - 每个标题保留分数最高、时间最新的一条
    """
    if df is None or df.empty:
        return df

    # 标题归一化：小写、去空格、去特殊字符、截断
    norm = (
        df.get("headline", "").fillna("")
          .str.lower()
          .str.replace(r"\s+", " ", regex=True)
          .str.replace(r"[^\w\s]", "", regex=True)
          .str.strip()
          .str.slice(0, 160)
    )

    # 排序：先分数高，再时间新
    tmp = df.assign(_key=norm).sort_values(
        by=["score", "ts_detected_utc"],
        ascending=[False, False],
        kind="mergesort",
    )

    # 去重：同一标题只留一条
    out = tmp.drop_duplicates(subset="_key", keep="first").drop(columns=["_key"])

    # 最终输出按时间排序（最新在上）
    return out.sort_values(by="ts_detected_utc", ascending=False).reset_index(drop=True)
# ========== HTML 表格渲染（标题为可点击文字） ==========
def render_table_html(df: pd.DataFrame, tz_name: str, *, show_score: bool = True) -> str:
    cols = ["时间", "来源"] + (["分数"] if show_score else []) + ["标题", "symbols", "tags"]
    rows = []
    for _, r in df.iterrows():
        time_str = _utc_ms_to_local_str(int(r["ts_detected_utc"]), tz_name)
        src = str(r.get("source", "") or "")
        score = int(r.get("score", 0) or 0)
        title = str(r.get("headline", "") or "")
        link = str(r.get("link", "") or "")
        symbols = str(r.get("symbols", "") or "")
        tags = str(r.get("tags", "") or "")
        # 标题以文字显示；有链接则可点
        if link.startswith("http"):
            title_html = f"<a class='ih-link' href='{link}' target='_blank' rel='noopener noreferrer'>{title}</a>"
        else:
            title_html = title
        tds = [
            f"<td class='nowrap small'>{time_str}</td>",
            f"<td>{src}</td>",
        ]
        if show_score:
            tds.append(f"<td><span class='score-badge'>{score}</span></td>")
        tds += [
            f"<td>{title_html}</td>",
            f"<td class='small'>{symbols}</td>",
            f"<td class='small'>{tags}</td>",
        ]
        rows.append("<tr>" + "".join(tds) + "</tr>")
    thead = "<tr>" + "".join([f"<th>{c}</th>" for c in cols]) + "</tr>"
    return f"<table class='ih-table'><thead>{thead}</thead><tbody>{''.join(rows)}</tbody></table>"

# ========== 读库 & 展示 ==========
since_ms = _now_ms() - 48 * 3600 * 1000
try:
    conn = _connect()
except Exception as e:
    st.error(f"无法连接数据库：{DB_PATH}\n{e}")
    st.stop()

# 未推送
# 未推送（按时间）
df_unpushed = _fetch_unpushed(conn, since_ms, query)
df_unpushed = _dedupe_latest(df_unpushed) 
df_high = _fetch_high(conn, since_ms, 70, query, False)
df_high = _dedupe_latest(df_high)
# 未推送最新流
st.subheader("🛰️ Headlines")
if df_unpushed.empty:
    st.info("窗口内暂无未推送的事件。")
else:
    html = render_table_html(df_unpushed, tz_name="Australia/Sydney", show_score=True)
    st.markdown(html, unsafe_allow_html=True)
    st.markdown("<div class='table-note'></div>", unsafe_allow_html=True)

st.markdown("---")

# 高等级 + 热度榜
left_main, right_main = st.columns([0.62, 0.38])

with left_main:
    st.subheader("📌 高等级流（按分倒序）")
    if df_high.empty:
        st.warning("窗口内没有满足条件的事件。请调低最小分数或扩大回看窗口。")
    else:
        html = render_table_html(df_high, tz_name="Australia/Sydney", show_score=True)
        st.markdown(html, unsafe_allow_html=True)

with right_main:
    st.subheader("🔥 热度榜")
    h1_since = _now_ms() - 1*3600*1000
    h24_since = _now_ms() - 24*3600*1000
    df_1h = pd.read_sql_query("SELECT symbols,tags FROM events WHERE ts_detected_utc>=?", conn, params=[h1_since])
    df_24h= pd.read_sql_query("SELECT symbols,tags FROM events WHERE ts_detected_utc>=?", conn, params=[h24_since])

    st.caption("过去 1 小时 Symbols")
    st.dataframe(_top_count(df_1h, "symbols", 10), use_container_width=True, hide_index=True)

    st.caption("过去 1 小时 Tags")
    st.dataframe(_top_count(df_1h, "tags", 10), use_container_width=True, hide_index=True)

    st.caption("过去 24 小时 Symbols")
    st.dataframe(_top_count(df_24h, "symbols", 10), use_container_width=True, hide_index=True)

    st.caption("过去 24 小时 Tags")
    st.dataframe(_top_count(df_24h, "tags", 10), use_container_width=True, hide_index=True)

try:
    conn.close()
except Exception:
    pass