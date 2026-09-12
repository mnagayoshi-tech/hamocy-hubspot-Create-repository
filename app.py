import streamlit as st
import requests
from datetime import date, datetime, timezone
import json
import base64

st.set_page_config(page_title="Hamocy 候補者登録", page_icon="🏢", layout="centered")

# ── 定数 ──────────────────────────────────────────────
PORTAL_ID = "243432503"
PIPELINE = "default"
DEAL_STAGE = "appointmentscheduled"  # 推薦固定
CONTACT_TO_ALLIANCE_ID = 33
DEAL_TO_ALLIANCE_ID = 41

GAKUREKI_OPTIONS = ["大卒", "大学院卒", "短大卒", "専門卒", "高卒", "中卒"]
KIBOU_OPTIONS = [
    "東京","神奈川","埼玉","千葉","大阪","愛知","福岡","茨城","栃木","群馬",
    "山梨","京都","兵庫","静岡","三重","北海道","宮城","広島","岡山","新潟",
    "長野","青森","岩手","秋田","山形","福島","富山","石川","福井","滋賀",
    "奈良","和歌山","鳥取","島根","山口","徳島","香川","愛媛","高知","佐賀",
    "岐阜","長崎","熊本","大分","宮崎","鹿児島","沖縄","指定なし"
]
CHANNEL_OPTIONS = ["キャリアパーク","マイナビ","OpenWork","Green","アライアンス","リクナビNEXT","doda","その他"]

# ── ユーティリティ ────────────────────────────────────
def date_to_ms(d: date) -> str:
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return str(int(dt.timestamp() * 1000))

def calc_age(birthdate: date) -> int:
    today = date.today()
    return today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))

def hs_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# ── AI抽出 ────────────────────────────────────────────
def extract_from_pdf(pdf_bytes: bytes, anthropic_key: str) -> dict:
    b64 = base64.standard_b64encode(pdf_bytes).decode()
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 1000,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                {"type": "text", "text": """この履歴書から以下をJSON形式で抽出してください。不明な場合はnull。
{
  "lastname": "姓（漢字）",
  "firstname": "名（漢字）",
  "furigana": "フリガナ（カタカナ、スペース区切り）",
  "phone": "携帯電話番号（数字のみ）",
  "email": "メールアドレス",
  "state": "都道府県名のみ（例:東京都→東京都）",
  "birthdate": "生年月日（YYYY-MM-DD）",
  "gakureki": "最終学歴（大卒/大学院卒/短大卒/専門卒/高卒/中卒）",
  "syusshin": "出身校名",
  "genshoku": "現職企業名",
  "keiken": "正社員経験社数（数字のみ）"
}
JSONのみ返してください。"""}
            ]
        }]
    }
    r = requests.post("https://api.anthropic.com/v1/messages", json=payload,
                      headers={"x-api-key": anthropic_key, "anthropic-version": "2023-06-01",
                               "Content-Type": "application/json"})
    if r.status_code == 200:
        text = r.json()["content"][0]["text"].strip()
        text = text.replace("```json","").replace("```","").strip()
        return json.loads(text)
    return {}

# ── HubSpot API ───────────────────────────────────────
def get_owners(token):
    r = requests.get("https://api.hubapi.com/crm/v3/owners", headers=hs_headers(token))
    return r.json().get("results", []) if r.status_code == 200 else []

def find_owner_id(owners, email):
    for o in owners:
        if o.get("email","").lower() == email.lower():
            return str(o["id"])
    return "162107431"

def search_contact(token, name):
    r = requests.post("https://api.hubapi.com/crm/v3/objects/contacts/search",
        json={"query": name, "properties": ["firstname","lastname","email"]},
        headers=hs_headers(token))
    d = r.json()
    return d["results"][0] if d.get("total",0) > 0 else None

def search_alliance(token, keyword):
    r = requests.post("https://api.hubapi.com/crm/v3/objects/p243432503_alliance/search",
        json={"query": keyword, "properties": ["name"]},
        headers=hs_headers(token))
    return r.json().get("results", []) if r.status_code == 200 else []

def search_company(token, keyword):
    r = requests.post("https://api.hubapi.com/crm/v3/objects/companies/search",
        json={"query": keyword, "properties": ["name"]},
        headers=hs_headers(token))
    return r.json().get("results", []) if r.status_code == 200 else []

def create_or_update_contact(token, props, existing_id=None):
    if existing_id:
        r = requests.patch(f"https://api.hubapi.com/crm/v3/objects/contacts/{existing_id}",
            json={"properties": props}, headers=hs_headers(token))
        return existing_id, r.json()
    else:
        r = requests.post("https://api.hubapi.com/crm/v3/objects/contacts",
            json={"properties": props}, headers=hs_headers(token))
        data = r.json()
        return data.get("id"), data

def associate_contact_alliance(token, contact_id, alliance_id):
    url = f"https://api.hubapi.com/crm/v4/objects/contacts/{contact_id}/associations/p243432503_alliance/{alliance_id}"
    r = requests.put(url, json=[{"associationCategory":"USER_DEFINED","associationTypeId":CONTACT_TO_ALLIANCE_ID}],
                     headers=hs_headers(token))
    return r.status_code in (200, 201)

def create_deal(token, deal_name, contact_id, company_id, alliance_id, owner_id, suisen_ms):
    props = {
        "dealname": deal_name,
        "pipeline": PIPELINE,
        "dealstage": DEAL_STAGE,
        "hubspot_owner_id": owner_id,
        "shiboudo": "第一志望群",
        "qiu_zhi_zhe_shi_dianno_song_zhu_mei": "竹",
        "suisen": suisen_ms,
    }
    associations = []
    if contact_id:
        associations.append({"to":{"id":contact_id},"types":[{"associationCategory":"HUBSPOT_DEFINED","associationTypeId":3}]})
    if company_id:
        associations.append({"to":{"id":company_id},"types":[{"associationCategory":"HUBSPOT_DEFINED","associationTypeId":5}]})
    if alliance_id:
        associations.append({"to":{"id":alliance_id},"types":[{"associationCategory":"USER_DEFINED","associationTypeId":DEAL_TO_ALLIANCE_ID}]})
    r = requests.post("https://api.hubapi.com/crm/v4/objects/deals",
        json={"properties": props, "associations": associations}, headers=hs_headers(token))
    return r.json()

# ── メイン UI ─────────────────────────────────────────
def main():
    st.title("🏢 Hamocy 候補者登録")

    # サイドバー
    with st.sidebar:
        st.header("⚙️ 設定")
        token = st.text_input("HubSpot Token", type="password")
        anthropic_key = st.text_input("Anthropic API Key", type="password")
        user_email = st.text_input("担当者メールアドレス", placeholder="m.nagayoshi@hamocy.com")

        owner_id = "162107431"
        if token and user_email:
            owners = get_owners(token)
            owner_id = find_owner_id(owners, user_email)
            st.caption(f"担当者ID: {owner_id}")

    if not token:
        st.info("左サイドバーに設定を入力してください")
        return

    # ─ PDFアップロード ─
    st.subheader("📄 履歴書アップロード（任意）")
    uploaded = st.file_uploader("PDFをアップロードするとAIが自動入力します", type=["pdf"])

    extracted = {}
    if uploaded and anthropic_key:
        with st.spinner("AIが読み取り中..."):
            extracted = extract_from_pdf(uploaded.read(), anthropic_key)
        if extracted:
            st.success("✅ 読み取り完了。内容を確認・修正してください。")

    st.divider()

    # ─ 候補者基本情報 ─
    st.subheader("👤 候補者情報")
    col1, col2 = st.columns(2)

    with col1:
        lastname  = st.text_input("姓*", value=extracted.get("lastname") or "")
        firstname = st.text_input("名*", value=extracted.get("firstname") or "")
        furigana  = st.text_input("フリガナ*", value=extracted.get("furigana") or "")
        phone     = st.text_input("携帯電話番号", value=extracted.get("phone") or "")
        email_val = st.text_input("メールアドレス", value=extracted.get("email") or "")

    with col2:
        # 生年月日
        bd_str = extracted.get("birthdate")
        try:
            bd_default = date.fromisoformat(bd_str) if bd_str else date(2000,1,1)
        except:
            bd_default = date(2000,1,1)
        birthdate = st.date_input("生年月日", value=bd_default,
                                  min_value=date(1960,1,1), max_value=date(2010,12,31))
        age = calc_age(birthdate)
        st.caption(f"年齢: {age}歳")

        # 居住地
        state_val = extracted.get("state") or "東京都"
        state_val = state_val.replace("都","").replace("道","").replace("府","").replace("県","")
        state_idx = KIBOU_OPTIONS.index(state_val) if state_val in KIBOU_OPTIONS else 0
        state = st.selectbox("居住地", KIBOU_OPTIONS, index=state_idx)

        gakureki_val = extracted.get("gakureki") or "大卒"
        gakureki_idx = GAKUREKI_OPTIONS.index(gakureki_val) if gakureki_val in GAKUREKI_OPTIONS else 0
        gakureki = st.selectbox("最終学歴", GAKUREKI_OPTIONS, index=gakureki_idx)
        syusshin = st.text_input("出身校", value=extracted.get("syusshin") or "")
        genshoku = st.text_input("現職企業", value=extracted.get("genshoku") or "")

    col3, col4 = st.columns(2)
    with col3:
        keiken_num = extracted.get("keiken") or "1"
        try: keiken_num = int(keiken_num)
        except: keiken_num = 1
        keiken_idx = min(max(keiken_num, 0), 10)
        keiken = st.selectbox("経験社数", [f"{i}社" for i in range(0,11)], index=keiken_idx)
        kibou = st.selectbox("希望勤務地", KIBOU_OPTIONS)

    with col4:
        channel = st.selectbox("流入チャネル", CHANNEL_OPTIONS,
                               index=CHANNEL_OPTIONS.index("アライアンス") if "アライアンス" in CHANNEL_OPTIONS else 0)
        oubobi = st.date_input("応募日", value=date.today())

    st.divider()

    # ─ アライアンス先 ─
    st.subheader("🤝 アライアンス先")
    alliance_input = st.text_input("アライアンス名（部分入力でOK）", placeholder="NowYouSee / インバウンドテクノロジー など")

    st.divider()

    # ─ 取引情報 ─
    st.subheader("📋 取引")
    num_deals = st.number_input("取引数", min_value=1, max_value=8, value=1)

    deals_input = []
    for i in range(int(num_deals)):
        cols = st.columns([3, 2, 2])
        with cols[0]:
            co = st.text_input(f"会社名 {i+1}", placeholder="BuySell Technologies", key=f"co_{i}")
        with cols[1]:
            loc = st.selectbox(f"勤務地 {i+1}", KIBOU_OPTIONS, key=f"loc_{i}")
        with cols[2]:
            pos = st.text_input(f"ポジション {i+1}", placeholder="営業職", key=f"pos_{i}")
        deals_input.append({"company": co, "location": loc, "position": pos})

    st.divider()

    # ─ 登録実行 ─
    if st.button("✅ 登録実行", type="primary", use_container_width=True):
        if not lastname or not firstname:
            st.error("姓・名は必須です")
            return

        with st.spinner("処理中..."):

            # 1. 重複チェック
            existing = search_contact(token, f"{lastname} {firstname}")
            existing_id = None
            if existing:
                st.warning(f"⚠️ 既存コンタクトが見つかりました: {existing['properties'].get('firstname','')} {existing['properties'].get('lastname','')}（ID: {existing['id']}）→ 更新します")
                existing_id = existing["id"]

            # 2. アライアンス検索
            alliance_id = None
            alliance_name = alliance_input
            if alliance_input:
                results = search_alliance(token, alliance_input)
                if results:
                    alliance_id = results[0]["id"]
                    alliance_name = results[0]["properties"].get("name", alliance_input)
                    st.info(f"🤝 アライアンス: {alliance_name}")

            # 3. コンタクト登録
            props = {
                "lastname": lastname,
                "firstname": firstname,
                "furigana": furigana,
                "mobilephone": phone,
                "email": email_val,
                "state": state,
                "seinengappi": date_to_ms(birthdate),
                "date_of_birth": date_to_ms(birthdate),
                "age": str(age),
                "saisyuu_gakureki": gakureki,
                "syusshin": syusshin,
                "genshoku": genshoku,
                "keiken_syasuu": keiken,
                "kiboukinmuchi": kibou,
                "ryunyu_chanel": channel,
                "oubobi": date_to_ms(oubobi),
                "hs_lead_status": "推薦",
                "rank": "D",
                "hubspot_owner_id": owner_id,
                "alaiancekigyou": alliance_name,
            }
            props = {k:v for k,v in props.items() if v}

            contact_id, result = create_or_update_contact(token, props, existing_id)
            if not contact_id:
                st.error(f"コンタクト登録エラー: {result}")
                return

            action = "更新" if existing_id else "新規作成"
            st.success(f"✅ コンタクト{action}完了 (ID: {contact_id})")

            # 4. アライアンス紐付け（コンタクト）
            if alliance_id:
                ok = associate_contact_alliance(token, contact_id, alliance_id)
                st.success("✅ アライアンス紐付け完了") if ok else st.warning("⚠️ アライアンス紐付け失敗")

            # 5. 取引作成
            suisen_ms = date_to_ms(date.today())
            for i, d in enumerate(deals_input):
                if not d["company"]:
                    continue

                # 会社検索
                company_id = None
                co_results = search_company(token, d["company"])
                if co_results:
                    company_id = co_results[0]["id"]

                # 取引名: 会社名/勤務地/ポジション
                parts = [d["company"], d["location"]]
                if d["position"]:
                    parts.append(d["position"])
                deal_name = "/".join(parts)

                deal_result = create_deal(token, deal_name, contact_id, company_id, alliance_id, owner_id, suisen_ms)
                deal_id = deal_result.get("id")
                if deal_id:
                    url = f"https://app.hubspot.com/contacts/{PORTAL_ID}/record/0-3/{deal_id}"
                    st.success(f"✅ 取引作成: [{deal_name}]({url})")
                else:
                    st.error(f"取引{i+1}エラー: {deal_result}")

            # コンタクトリンク
            c_url = f"https://app.hubspot.com/contacts/{PORTAL_ID}/record/0-1/{contact_id}"
            st.link_button("🔗 コンタクトをHubSpotで確認", c_url)

if __name__ == "__main__":
    main()
