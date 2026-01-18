"""
HTMLからJSON-LD内の'headline'を全て抽出し、OpenAI LLMで都道府県を判定するスクリプト
（複数ページ対応版）
"""
import json
import requests
import pandas as pd
import time
from bs4 import BeautifulSoup
from openai import OpenAI
import os
from dotenv import load_dotenv
import streamlit as st
from datetime import date

# ==========================================
# 1日あたりのAPI使用制限（★重要）
# ==========================================

DAILY_TOKEN_LIMIT = 15000   # ≒ 約0.1ドル
TODAY = str(date.today())

if "daily_tokens" not in st.session_state:
    st.session_state.daily_tokens = {}

if TODAY not in st.session_state.daily_tokens:
    st.session_state.daily_tokens[TODAY] = 0

# ==========================================
# Streamlit画面表示
# ==========================================

st.title("記事タイトル抽出＆エリア別に整理アプリ")
st.info(
    "Webページから記事タイトルを取得し、"
    "AIを使って都道府県を判定します。"
)
st.warning("このアプリは、下記のHTML構造ようなURLで動作するように設計されています。")
st.write("参考URL：https://clinic.mynavi.jp/article_list/")

# ▼ URL入力欄（★追加）
base_url = st.text_input(
    label="取得対象URLを入力してください",
    value=""
)

# ▼ ページ数入力
page_count = st.number_input(
    "取得ページ数",
    min_value=1,
    max_value=5,
    value=3
)

# ==========================================
# 実行関数
# ==========================================

def extract_headlines_with_beautifulsoup(html_content):
    """BeautifulSoupを使用してJSON-LDからheadlineを抽出"""
    soup = BeautifulSoup(html_content, 'html.parser')
    headlines = []
    
    # type="application/ld+json"のscriptタグを全て取得
    scripts = soup.find_all('script', type='application/ld+json')
    
    for script in scripts:
        try:
            data = json.loads(script.string)
            if 'headline' in data:
                headlines.append(data['headline'])
        except (json.JSONDecodeError, TypeError):
            continue
    
    return headlines


def extract_prefecture_with_llm(headlines, api_key):
    """OpenAI LLMを使用してheadlineから都道府県を抽出"""
    
    # ▼ 想定トークン数（安全側の概算）
    estimated_tokens = len(headlines) * 120  

    if st.session_state.daily_tokens[TODAY] + estimated_tokens > DAILY_TOKEN_LIMIT:
        st.error(
            "本日のAPI利用上限（約0.1ドル）に達しました。"
            "明日以降に再実行してください。"
        )
        st.stop()
    
    client = OpenAI(api_key=api_key)
    
    # 全てのheadlineを一度に処理（効率化のため）
    headlines_text = "\n".join([f"{i+1}. {h}" for i, h in enumerate(headlines)])
    
    prompt = f"""以下の記事タイトル一覧から、それぞれ該当する都道府県を判断してください。

【ルール】
- 都道府県名のみを回答（例：東京都、大阪府、北海道）
- 東京23区や東京都内の市区は「東京都」
- 政令指定都市は所属する都道府県を回答（例：横浜市→神奈川県、神戸市→兵庫県）
- 判断できない場合は「不明」

【出力形式】
番号と都道府県名のみをカンマ区切りで出力してください。
例: 1,東京都
    2,大阪府
    3,不明

【記事タイトル一覧】
{headlines_text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=1000,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    
    # ▼ トークン使用量を加算（概算）
    st.session_state.daily_tokens[TODAY] += estimated_tokens

    # レスポンスをパース
    response_text = response.choices[0].message.content
    prefectures = ['不明'] * len(headlines)
    
    for line in response_text.strip().split('\n'):
        line = line.strip()
        if ',' in line:
            parts = line.split(',', 1)
            try:
                idx = int(parts[0].strip()) - 1
                pref = parts[1].strip()
                if 0 <= idx < len(headlines):
                    prefectures[idx] = pref
            except ValueError:
                continue
    
    return prefectures




# ==========================================
# メイン処理
# ==========================================

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    st.error("環境変数 OPENAI_API_KEY が設定されていません")
    st.stop()


# ▼ 実行ボタン（★重要）
if st.button("実行"):
    if not base_url:
        st.warning("URLを入力してください")
        st.stop()
    
    all_headlines = []
    all_prefectures = []

    progress = st.progress(0)

    for page in range(1, page_count + 1):
        if page == 1:
            url = base_url
        else:
            url = f"{base_url}{page}"

        st.write(f"処理中({page}ページ目)：{url}")

        response = requests.get(url)
        headlines = extract_headlines_with_beautifulsoup(response.text)

        prefectures = extract_prefecture_with_llm(headlines, api_key)

        all_headlines.extend(headlines)
        all_prefectures.extend(prefectures)

        progress.progress(page / page_count)
        time.sleep(3)

    df = pd.DataFrame({
        "headline": all_headlines,
        "都道府県": all_prefectures
    })
    df.index += 1
    df.index.name = "No"

    st.success(f"取得完了：{len(df)}件")
    st.dataframe(df)

    csv = df.to_csv(index=True).encode("utf-8-sig")
    st.download_button(
        label="CSVをダウンロード",
        data=csv,
        file_name="headlines_prefecture.csv",
        mime="text/csv"
    )

    remaining_tokens = DAILY_TOKEN_LIMIT - st.session_state.daily_tokens[TODAY]

    st.info(
        f"本日のAPI使用量（目安）："
        f"{st.session_state.daily_tokens[TODAY]} / {DAILY_TOKEN_LIMIT} トークン\n"
        f"（残り 約 {remaining_tokens} トークン ≒ 数十円）"
    )