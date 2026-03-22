import anthropic
import requests
import os
import random
import json
from datetime import datetime, timezone, timedelta
from collections import Counter

# ============================================================
# 環境変数
# ============================================================
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_ANON_KEY"]

# X API（ラベル解除後に有効化）
X_API_KEY = os.environ.get("X_API_KEY", "")
X_API_SECRET = os.environ.get("X_API_SECRET", "")
X_ACCESS_TOKEN = os.environ.get("X_ACCESS_TOKEN", "")
X_ACCESS_TOKEN_SECRET = os.environ.get("X_ACCESS_TOKEN_SECRET", "")

SITE_URL = "https://anotokinokoe.github.io/anotokinokoe/?v=3"

# ============================================================
# Supabaseからデータ取得
# ============================================================
def fetch_voices():
    """Supabaseから全投稿データを取得"""
    url = f"{SUPABASE_URL}/rest/v1/voices?is_deleted=eq.false&select=*"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return resp.json()
    else:
        print(f"Supabase取得エラー: {resp.status_code}")
        return []

# ============================================================
# データ分析
# ============================================================
def analyze_data(voices):
    """投稿データからランキング・統計を生成"""
    total = len(voices)
    
    # タイプ別カウント
    type_counts = Counter(v["type"] for v in voices)
    
    # カテゴリ別カウント（後悔系のみ）
    regret_voices = [v for v in voices if v["type"] in ("do", "dont")]
    cat_counts = Counter(v["cat"] for v in regret_voices)
    cat_ranking = cat_counts.most_common(5)
    
    # 年代別の後悔カテゴリTOP3
    age_rankings = {}
    age_groups = {
        "20代": ["20代前半", "20代後半"],
        "30代": ["30代前半", "30代後半"],
        "40代": ["40代"],
        "50代": ["50代"],
    }
    for label, ages in age_groups.items():
        age_voices = [v for v in regret_voices if v["age"] in ages]
        if age_voices:
            ac = Counter(v["cat"] for v in age_voices)
            age_rankings[label] = ac.most_common(3)
    
    # 性別別の後悔カテゴリTOP3
    gender_rankings = {}
    for g in ["男性", "女性"]:
        gv = [v for v in regret_voices if v.get("gender") == g]
        if gv:
            gc = Counter(v["cat"] for v in gv)
            gender_rankings[g] = gc.most_common(3)
    
    # 最も共感された投稿
    top_empathy = sorted(voices, key=lambda v: v.get("empathy_count", 0), reverse=True)[:3]
    
    return {
        "total": total,
        "type_counts": dict(type_counts),
        "cat_ranking": cat_ranking,
        "age_rankings": age_rankings,
        "gender_rankings": gender_rankings,
        "top_empathy": top_empathy,
        "do_count": type_counts.get("do", 0),
        "dont_count": type_counts.get("dont", 0),
        "good_count": type_counts.get("good", 0),
    }

# ============================================================
# 曜日別投稿タイプ
# ============================================================
def get_post_type():
    """JST基準で曜日に応じた投稿タイプを返す"""
    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    weekday = now.weekday()  # 0=月 1=火 ... 6=日
    
    types = {
        0: "data",      # 月：データ提示型
        1: "poll",      # 火：ポール/問いかけ型
        2: "hybrid",    # 水：ハイブリッド型
        3: "data",      # 木：データ提示型
        4: "poll",      # 金：ポール/問いかけ型
        5: "thread",    # 土：スレッド型（長文）
        6: "thread",    # 日：スレッド型（長文）
    }
    return types[weekday], now.strftime("%A")

# ============================================================
# プロンプト生成
# ============================================================
def build_prompt(post_type, stats):
    """投稿タイプとデータに基づいてClaudeへのプロンプトを生成"""
    
    # 共通のデータ部分
    data_context = f"""
【実データ（{stats['total']}件の投稿から集計）】
- 「やっておけばよかった」: {stats['do_count']}件
- 「やめておけばよかった」: {stats['dont_count']}件
- 「やってよかった」: {stats['good_count']}件

後悔カテゴリランキング:
"""
    for i, (cat, count) in enumerate(stats['cat_ranking'][:5], 1):
        pct = round(count / max(stats['do_count'] + stats['dont_count'], 1) * 100)
        data_context += f"  {i}位: {cat}（{count}件, {pct}%）\n"
    
    for age, ranking in stats['age_rankings'].items():
        data_context += f"\n{age}の後悔TOP3: "
        data_context += ", ".join([f"{cat}({c}件)" for cat, c in ranking])
    
    if stats['gender_rankings']:
        data_context += "\n"
        for g, ranking in stats['gender_rankings'].items():
            data_context += f"\n{g}の後悔TOP3: "
            data_context += ", ".join([f"{cat}({c}件)" for cat, c in ranking])
    
    # タイプ別プロンプト
    if post_type == "data":
        return f"""
あなたはXで「人生選択データベース」というアカウントを運営しています。
以下の実データを使って、データ提示型のポストを1つ作ってください。

{data_context}

条件：
- 140文字以内
- 具体的な数字・割合を必ず含める（上記の実データから引用）
- 「◯人中◯人が〜」「◯%が〜」のような表現
- ハッシュタグ2つ以内
- URLは含めない
- データの出典を捏造しない（「◯件の声から」のように自サイトのデータであることを示す）

ポスト本文だけ出力してください。説明不要。
"""
    
    elif post_type == "poll":
        return f"""
あなたはXで「人生選択データベース」というアカウントを運営しています。
以下の実データを参考に、問いかけ型のポストを1つ作ってください。

{data_context}

条件：
- 140文字以内
- 読者が思わず答えたくなる問いかけで終わる
- データに基づいた前振り + 質問の構成
- ハッシュタグ2つ以内
- URLは含めない
- 「あなたは？」「どう思いますか？」で終わる

ポスト本文だけ出力してください。説明不要。
"""
    
    elif post_type == "hybrid":
        return f"""
あなたはXで「人生選択データベース」というアカウントを運営しています。
以下の実データを使って、データ提示＋問いかけのハイブリッド型ポストを1つ作ってください。

{data_context}

条件：
- 140文字以内
- 前半でデータ（数字）を提示し、後半で問いかける
- 具体的な数字を必ず含める
- ハッシュタグ2つ以内
- URLは含めない

ポスト本文だけ出力してください。説明不要。
"""
    
    else:  # thread
        return f"""
あなたはXで「人生選択データベース」というアカウントを運営しています。
以下の実データを使って、スレッド用の1ポスト目（フック）を作ってください。

{data_context}

条件：
- 140文字以内
- 「続きはスレッドで👇」で終わる
- 衝撃的なデータや意外な事実から始める
- 具体的な数字を必ず含める
- ハッシュタグなし（スレッドの最後に入れるため）
- URLは含めない

ポスト本文だけ出力してください。説明不要。
"""

# ============================================================
# 画像生成
# ============================================================
def generate_image(stats, post_type):
    """投稿データからSNS共有用の画像を生成"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        
        # 日本語フォント設定
        jp_fonts = [f.name for f in fm.fontManager.ttflist 
                    if any(k in f.name.lower() for k in ['noto', 'gothic', 'mincho', 'meiryo', 'hiragino', 'ipag', 'ipam'])]
        if jp_fonts:
            plt.rcParams['font.family'] = jp_fonts[0]
        else:
            # フォールバック
            plt.rcParams['font.family'] = 'DejaVu Sans'
        
        # ダークテーマ（サイトと統一）
        bg_color = '#0d0d0d'
        text_color = '#e8e2d9'
        accent_color = '#c8a96e'
        accent_dont = '#c87070'
        accent_good = '#6ec8a0'
        dim_color = '#7a7468'
        
        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=150)
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)
        ax.axis('off')
        
        # 年代別ランキングを選択
        age_key = random.choice(list(stats['age_rankings'].keys())) if stats['age_rankings'] else None
        
        if age_key and stats['age_rankings'][age_key]:
            ranking = stats['age_rankings'][age_key]
            max_count = ranking[0][1] if ranking else 1
            
            # タイトル
            ax.text(0.5, 0.92, f'{age_key}が後悔していること TOP{len(ranking)}',
                    transform=ax.transAxes, fontsize=18, fontweight='bold',
                    color=accent_color, ha='center', va='top')
            
            ax.text(0.5, 0.84, f'「あの時の声」{stats["total"]}件のデータより',
                    transform=ax.transAxes, fontsize=9,
                    color=dim_color, ha='center', va='top',
                    fontstyle='italic')
            
            # バーチャート
            colors = [accent_color, '#a0968a', dim_color, '#5a5450', '#4a4440']
            for i, (cat, count) in enumerate(ranking):
                y = 0.68 - i * 0.18
                bar_width = (count / max_count) * 0.6
                
                # 順位
                ax.text(0.08, y, f'{i+1}', transform=ax.transAxes,
                        fontsize=28, color=colors[i] if i < len(colors) else dim_color,
                        ha='center', va='center', fontstyle='italic', fontweight='bold')
                
                # バー
                bar = plt.Rectangle((0.18, y - 0.03), bar_width, 0.06,
                                     transform=ax.transAxes, 
                                     facecolor=colors[i] if i < len(colors) else dim_color,
                                     alpha=0.3, zorder=1)
                ax.add_patch(bar)
                
                # カテゴリ名
                ax.text(0.20, y, cat, transform=ax.transAxes,
                        fontsize=13, color=text_color, va='center', zorder=2)
                
                # 件数
                pct = round(count / max(stats['do_count'] + stats['dont_count'], 1) * 100)
                ax.text(0.85, y, f'{count}件 ({pct}%)', transform=ax.transAxes,
                        fontsize=10, color=dim_color, va='center', ha='right',
                        family='monospace')
            
            # フッター
            ax.text(0.5, 0.05, 'anotokinokoe.github.io/anotokinokoe',
                    transform=ax.transAxes, fontsize=8,
                    color=dim_color, ha='center', va='bottom',
                    family='monospace', alpha=0.6)
        
        else:
            # データが少ない場合はシンプルな統計画像
            ax.text(0.5, 0.7, f'投稿数 {stats["total"]}件',
                    transform=ax.transAxes, fontsize=32, fontweight='bold',
                    color=accent_color, ha='center')
            ax.text(0.5, 0.45, 
                    f'やっておけばよかった {stats["do_count"]}件\nやめておけばよかった {stats["dont_count"]}件\nやってよかった {stats["good_count"]}件',
                    transform=ax.transAxes, fontsize=14,
                    color=text_color, ha='center', va='center', linespacing=1.8)
        
        plt.tight_layout(pad=1.0)
        
        img_path = '/tmp/post_image.png'
        plt.savefig(img_path, facecolor=bg_color, edgecolor='none',
                    bbox_inches='tight', pad_inches=0.3)
        plt.close()
        
        print(f"画像生成完了: {img_path}")
        return img_path
        
    except Exception as e:
        print(f"画像生成エラー: {e}")
        return None

# ============================================================
# X投稿（画像付き）
# ============================================================
def post_to_x(text, image_path=None):
    """tweepyでXに投稿（画像付き対応）"""
    if not all([X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET]):
        print("X API キーが未設定のためスキップ")
        return None
    
    try:
        import tweepy
        
        # v1.1 API（画像アップロード用）
        auth = tweepy.OAuthHandler(X_API_KEY, X_API_SECRET)
        auth.set_access_token(X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET)
        api_v1 = tweepy.API(auth)
        
        # v2 API（ツイート投稿用）
        client = tweepy.Client(
            consumer_key=X_API_KEY,
            consumer_secret=X_API_SECRET,
            access_token=X_ACCESS_TOKEN,
            access_token_secret=X_ACCESS_TOKEN_SECRET,
        )
        
        media_id = None
        if image_path and os.path.exists(image_path):
            media = api_v1.media_upload(image_path)
            media_id = media.media_id
            print(f"画像アップロード完了: media_id={media_id}")
        
        kwargs = {"text": text}
        if media_id:
            kwargs["media_ids"] = [media_id]
        
        response = client.create_tweet(**kwargs)
        print(f"X投稿完了: {response.data['id']}")
        return response
        
    except Exception as e:
        print(f"X投稿エラー: {e}")
        return None

# ============================================================
# Discord送信（画像付き）
# ============================================================
def send_to_discord(text, post_type, day_name, image_path=None):
    """Discordに投稿内容を送信"""
    type_labels = {
        "data": "📊 データ提示型",
        "poll": "❓ 問いかけ型",
        "hybrid": "🔀 ハイブリッド型",
        "thread": "🧵 スレッド型",
    }
    
    content = (
        f"📢 **今日のXポスト** ({type_labels.get(post_type, post_type)})\n\n"
        f"```\n{text}\n```\n\n"
        f"⬆️ これをコピーしてXに投稿してください！"
    )
    
    if image_path and os.path.exists(image_path):
        # 画像付き送信
        with open(image_path, 'rb') as f:
            files = {'file': ('post_image.png', f, 'image/png')}
            payload = {"content": content}
            resp = requests.post(DISCORD_WEBHOOK_URL, data=payload, files=files)
    else:
        payload = {"content": content}
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    
    print(f"Discord送信: {resp.status_code}")

# ============================================================
# メイン
# ============================================================
def main():
    # 1. Supabaseからデータ取得
    print("Supabaseからデータ取得中...")
    voices = fetch_voices()
    print(f"取得件数: {len(voices)}")
    
    # 2. データ分析
    stats = analyze_data(voices)
    print(f"分析完了: {stats['total']}件, カテゴリTOP={stats['cat_ranking'][:3]}")
    
    # 3. 曜日に応じた投稿タイプ決定
    post_type, day_name = get_post_type()
    print(f"投稿タイプ: {post_type} ({day_name})")
    
    # 4. Claude APIでポスト生成
    prompt = build_prompt(post_type, stats)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    post_text = message.content[0].text.strip()
    full_post = f"{post_text}\n\n{SITE_URL}"
    print(f"生成テキスト:\n{post_text}")
    
    # 5. 画像生成
    image_path = generate_image(stats, post_type)
    
    # 6. Discord送信
    send_to_discord(full_post, post_type, day_name, image_path)
    
    # 7. X投稿（APIキーが設定されている場合）
    post_to_x(full_post, image_path)

if __name__ == "__main__":
    main()
