import streamlit as st
import requests
from datetime import date, datetime, timezone
import json, base64

st.set_page_config(page_title="Hamocy 候補者登録", page_icon="🏢", layout="centered")

PORTAL_ID    = "243432503"
PIPELINE     = "default"
DEAL_STAGE   = "appointmentscheduled"
CONTACT_TO_ALLIANCE_ID = 33
DEAL_TO_ALLIANCE_ID    = 41
DEAL_TO_JOB_ID         = 36

GAKUREKI = ["大卒","大学院卒","短大卒","専門卒","高卒","中卒"]
PREFS    = [
    "東京","神奈川","埼玉","千葉","大阪","愛知","福岡","茨城","栃木","群馬",
    "山梨","京都","兵庫","静岡","三重","北海道","宮城","広島","岡山","新潟",
    "長野","青森","岩手","秋田","山形","福島","富山","石川","福井","滋賀",
    "奈良","和歌山","鳥取","島根","山口","徳島","香川","愛媛","高知","佐賀",
    "岐阜","長崎","熊本","大分","宮崎","鹿児島","沖縄","指定なし"
]
CHANNELS = ["アライアンス","キャリアパーク","マイナビ","OpenWork","Green","リクナビNEXT","doda","その他"]

# ── ユーティリティ ─────────────────────────────────────────
def ms(d: date) -> str:
    return str(int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()*1000))

def age(bd: date) -> int:
    t = date.today()
    return t.year - bd.year - ((t.month, t.day) < (bd.month, bd.day))

def hdr(token): return {"Authorization":f"Bearer {token}","Content-Type":"application/json"}

# ── AI抽出 ─────────────────────────────────────────────────
PROMPT = """以下の候補者情報から項目を抽出してJSONで返してください。不明はnull。

{
  "lastname":  "姓（漢字）",
  "firstname": "名（漢字）",
  "furigana":  "フリガナ（カタカナ、姓名スペース区切り）",
  "phone":     "携帯電話番号（数字のみ、ハイフンなし）",
  "email":     "メールアドレス",
  "state":     "都道府県（例：東京都、神奈川県）",
  "birthdate": "生年月日（YYYY-MM-DD）",
  "gakureki":  "最終学歴（大卒/大学院卒/短大卒/専門卒/高卒/中卒）",
  "syusshin":  "出身校名",
  "genshoku":  "現職企業名（在籍中の最新企業）",
  "keiken":    "正社員・契約社員の経験社数（数字のみ、アルバイト除く）",
  "kibou":     "希望勤務地の第1希望（都道府県名のみ、例：東京）"
}

JSONのみ返してください。"""

def extract(content_blocks: list, api_key: str) -> dict:
    r = requests.post("https://api.anthropic.com/v1/messages",
        json={"model":"claude-sonnet-4-6","max_tokens":1000,
              "messages":[{"role":"user","content": content_blocks + [{"type":"text","text":PROMPT}]}]},
        headers={"x-api-key":api_key,"anthropic-version":"2023-06-01","Content-Type":"application/json"})
    if r.status_code == 200:
        txt = r.json()["content"][0]["text"].strip().replace("```json","").replace("```","").strip()
        try: return json.loads(txt)
        except: return {}
    return {}

# ── HubSpot ────────────────────────────────────────────────
def owners(token):
    r = requests.get("https://api.hubapi.com/crm/v3/owners", headers=hdr(token))
    return r.json().get("results",[]) if r.ok else []

def owner_id(ows, email):
    for o in ows:
        if o.get("email","").lower() == email.lower(): return str(o["id"])
    return "162107431"

def search(token, obj, q, props=["name"]):
    r = requests.post(f"https://api.hubapi.com/crm/v3/objects/{obj}/search",
        json={"query":q,"properties":props}, headers=hdr(token))
    return r.json().get("results",[]) if r.ok else []

def upsert_contact(token, props, eid=None):
    if eid:
        r = requests.patch(f"https://api.hubapi.com/crm/v3/objects/contacts/{eid}",
            json={"properties":props}, headers=hdr(token))
        return eid, r.ok
    r = requests.post("https://api.hubapi.com/crm/v3/objects/contacts",
        json={"properties":props}, headers=hdr(token))
    d = r.json(); return d.get("id"), r.ok

def assoc_contact_alliance(token, cid, aid):
    r = requests.put(
        f"https://api.hubapi.com/crm/v4/objects/contacts/{cid}/associations/p243432503_alliance/{aid}",
        json=[{"associationCategory":"USER_DEFINED","associationTypeId":CONTACT_TO_ALLIANCE_ID}],
        headers=hdr(token))
    return r.status_code in (200,201)

def make_deal(token, name, cid, company_id, alliance_id, job_id, oid, suisen_ms):
    assocs = []
    if cid:        assocs.append({"to":{"id":cid},       "types":[{"associationCategory":"HUBSPOT_DEFINED","associationTypeId":3}]})
    if company_id: assocs.append({"to":{"id":company_id},"types":[{"associationCategory":"HUBSPOT_DEFINED","associationTypeId":5}]})
    if alliance_id:assocs.append({"to":{"id":alliance_id},"types":[{"associationCategory":"USER_DEFINED","associationTypeId":DEAL_TO_ALLIANCE_ID}]})
    if job_id:     assocs.append({"to":{"id":job_id},    "types":[{"associationCategory":"USER_DEFINED","associationTypeId":DEAL_TO_JOB_ID}]})
    r = requests.post("https://api.hubapi.com/crm/v4/objects/deals", headers=hdr(token),
        json={"properties":{"dealname":name,"pipeline":PIPELINE,"dealstage":DEAL_STAGE,
              "hubspot_owner_id":oid,"shiboudo":"第一志望群",
              "qiu_zhi_zhe_shi_dianno_song_zhu_mei":"竹","suisen":suisen_ms},
              "associations":assocs})
    return r.json()

# ── UI ─────────────────────────────────────────────────────
def main():
    st.title("🏢 Hamocy 候補者登録")

    with st.sidebar:
        st.header("⚙️ 設定")
        token = st.secrets.get("HUBSPOT_TOKEN","") or st.text_input("HubSpot Token", type="password")
        api_key = st.secrets.get("ANTHROPIC_API_KEY","") or st.text_input("Anthropic API Key", type="password")
        email = st.text_input("担当者メール", placeholder="m.nagayoshi@hamocy.com")
        oid = "162107431"
        if token and email:
            oid = owner_id(owners(token), email)
            st.caption(f"担当者ID: {oid}")

    if not token:
        st.info("サイドバーにTokenを入力してください")
        return

    # ── 入力方法 ──────────────────────────────────────────
    st.subheader("📥 候補者情報の入力")
    method = st.radio("入力方法", ["📄 PDFアップロード", "📝 テキスト貼り付け"], horizontal=True)

    extracted = {}
    if method == "📄 PDFアップロード":
        f = st.file_uploader("履歴書PDFをドラッグ＆ドロップ", type=["pdf"],
                             label_visibility="collapsed")
        if f and api_key:
            with st.spinner("AIが読み取り中..."):
                b64 = base64.standard_b64encode(f.read()).decode()
                blocks = [{"type":"document","source":{"type":"base64","media_type":"application/pdf","data":b64}}]
                extracted = extract(blocks, api_key)
            if extracted:
                st.success("✅ 読み取り完了")
    else:
        txt = st.text_area("候補者情報をここに貼り付け", height=200,
                           placeholder="氏名、生年月日、連絡先、学歴・職歴など...")
        if txt and api_key:
            with st.spinner("AIが読み取り中..."):
                blocks = [{"type":"text","text":txt}]
                extracted = extract(blocks, api_key)
            if extracted:
                st.success("✅ 読み取り完了")

    if extracted:
        with st.expander("📋 読み取り内容を確認", expanded=False):
            st.json(extracted)

    st.divider()

    # ── 追加入力（AIで取れない情報） ─────────────────────
    col1, col2 = st.columns(2)
    with col1:
        channel = st.selectbox("流入チャネル", CHANNELS)
        oubobi  = st.date_input("応募日", value=date.today())
    with col2:
        kibou_default = extracted.get("kibou","東京")
        kibou_default = kibou_default.replace("都","").replace("道","").replace("府","").replace("県","") if kibou_default else "東京"
        kidx = PREFS.index(kibou_default) if kibou_default in PREFS else 0
        kibou = st.selectbox("希望勤務地", PREFS, index=kidx)

    st.divider()

    # ── アライアンス ──────────────────────────────────────
    st.subheader("🤝 アライアンス先")
    alliance_input = st.text_input("アライアンス名（部分入力でOK）",
                                   placeholder="NowYouSee / インバウンドテクノロジー など")

    st.divider()

    # ── 取引 ─────────────────────────────────────────────
    st.subheader("📋 取引")
    num = st.number_input("取引数", min_value=1, max_value=8, value=1)
    deals_in = []
    for i in range(int(num)):
        cols = st.columns([3,2,2])
        with cols[0]: co  = st.text_input(f"会社名 {i+1}（部分入力でOK）", key=f"co_{i}")
        with cols[1]: loc = st.selectbox(f"勤務地 {i+1}", PREFS, key=f"loc_{i}")
        with cols[2]: pos = st.text_input(f"出張等 {i+1}", placeholder="出張/店舗", key=f"pos_{i}")
        deals_in.append({"company":co,"location":loc,"position":pos})

    st.divider()

    if st.button("✅ 登録実行", type="primary", use_container_width=True):
        if not extracted:
            st.error("先に候補者情報を読み取らせてください")
            return

        ln = extracted.get("lastname") or ""
        fn = extracted.get("firstname") or ""
        if not ln or not fn:
            st.error("氏名が読み取れませんでした。テキスト貼り付けでお試しください")
            return

        with st.spinner("HubSpotに登録中..."):

            # 生年月日・年齢
            bd_str = extracted.get("birthdate")
            bd = date.fromisoformat(bd_str) if bd_str else None
            age_val = str(age(bd)) if bd else ""

            # 重複チェック
            existing = search(token, "contacts", f"{ln} {fn}", ["firstname","lastname","email"])
            eid = existing[0]["id"] if existing else None
            if eid:
                st.warning(f"⚠️ 既存コンタクト発見 (ID:{eid}) → 更新します")

            # アライアンス
            alliance_id = None
            alliance_name = alliance_input
            if alliance_input:
                ar = search(token, "p243432503_alliance", alliance_input)
                if ar:
                    alliance_id   = ar[0]["id"]
                    alliance_name = ar[0]["properties"].get("name", alliance_input)
                    st.info(f"🤝 {alliance_name}")

            # コンタクト登録
            keiken_num = extracted.get("keiken") or "1"
            try: keiken_num = int(str(keiken_num))
            except: keiken_num = 1

            props = {
                "lastname":      ln,
                "firstname":     fn,
                "furigana":      extracted.get("furigana") or "",
                "mobilephone":   extracted.get("phone") or "",
                "email":         extracted.get("email") or "",
                "state":         extracted.get("state") or "",
                "seinengappi":   ms(bd) if bd else "",
                "date_of_birth": ms(bd) if bd else "",
                "age":           age_val,
                "saisyuu_gakureki": extracted.get("gakureki") or "",
                "syusshin":      extracted.get("syusshin") or "",
                "genshoku":      extracted.get("genshoku") or "",
                "keiken_syasuu": f"{keiken_num}社",
                "kiboukinmuchi": kibou,
                "ryunyu_chanel": channel,
                "oubobi":        ms(oubobi),
                "hs_lead_status":"推薦",
                "rank":          "D",
                "hubspot_owner_id": oid,
                "alaiancekigyou": alliance_name,
            }
            props = {k:v for k,v in props.items() if v}

            cid, ok = upsert_contact(token, props, eid)
            if not cid:
                st.error("コンタクト登録に失敗しました")
                return
            action = "更新" if eid else "新規作成"
            st.success(f"✅ コンタクト{action} (ID:{cid})")

            # アライアンス紐付け
            if alliance_id:
                ok2 = assoc_contact_alliance(token, cid, alliance_id)
                st.success("✅ アライアンス紐付け完了") if ok2 else st.warning("⚠️ アライアンス紐付け失敗")

            # 取引作成
            suisen_ms = ms(date.today())
            for i, d in enumerate(deals_in):
                if not d["company"]: continue

                co_res  = search(token, "companies", d["company"])
                job_res = search(token, "p243432503_job", d["company"])
                co_id  = co_res[0]["id"]  if co_res  else None
                job_id = job_res[0]["id"] if job_res else None

                if co_id:  st.info(f"🏢 {co_res[0]['properties'].get('name',d['company'])}")
                if job_id: st.info(f"📄 求人紐付け: {job_res[0]['properties'].get('name','')}")

                parts = [d["company"], d["location"]]
                if d["position"]: parts.append(d["position"])
                deal_name = "/".join(parts)

                dr = make_deal(token, deal_name, cid, co_id, alliance_id, job_id, oid, suisen_ms)
                did = dr.get("id")
                if did:
                    url = f"https://app.hubspot.com/contacts/{PORTAL_ID}/record/0-3/{did}"
                    st.success(f"✅ 取引: [{deal_name}]({url})")
                else:
                    st.error(f"取引{i+1}エラー: {dr}")

            st.link_button("🔗 コンタクトをHubSpotで確認",
                          f"https://app.hubspot.com/contacts/{PORTAL_ID}/record/0-1/{cid}")

if __name__ == "__main__":
    main()
