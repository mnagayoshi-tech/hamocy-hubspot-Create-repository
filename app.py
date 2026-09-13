import streamlit as st
import requests
from datetime import date, datetime, timezone
import json, base64

st.set_page_config(page_title="Hamocy 候補者登録", page_icon="🏢", layout="centered")

PORTAL_ID              = "243432503"
PIPELINE               = "default"
DEAL_STAGE             = "appointmentscheduled"
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

PROMPT = """以下の履歴書・候補者情報から各項目をJSONで返してください。不明はnull。

{
  "lastname":  "姓（漢字）",
  "firstname": "名（漢字）",
  "furigana":  "フリガナ（カタカナ、姓名スペース区切り）",
  "phone":     "携帯電話番号（数字のみ、ハイフンなし）",
  "email":     "メールアドレス",
  "state":     "現住所の都道府県（例：東京都、神奈川県）",
  "birthdate": "生年月日（YYYY-MM-DD形式）",
  "gakureki":  "最終学歴（大卒/大学院卒/短大卒/専門卒/高卒/中卒 のいずれか）",
  "syusshin":  "最終学歴の学校名",
  "genshoku":  "現在または直近の在籍企業名のみ（役職・部署名は含めない）",
  "keiken":    "正社員・契約社員としての勤務社数（数字のみ、アルバイトは除く、個人事業主は除く）"
}

JSONのみ返してください。コードブロック不要。"""

# ── ユーティリティ ─────────────────────────────────────────
def ms(d: date) -> str:
    return str(int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()*1000))

def calc_age(bd: date) -> int:
    t = date.today()
    return t.year - bd.year - ((t.month, t.day) < (bd.month, bd.day))

def hdr(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# ── API ────────────────────────────────────────────────────
def extract_info(content_blocks, api_key):
    r = requests.post("https://api.anthropic.com/v1/messages",
        json={"model":"claude-sonnet-4-6","max_tokens":1000,
              "messages":[{"role":"user","content": content_blocks + [{"type":"text","text":PROMPT}]}]},
        headers={"x-api-key":api_key,"anthropic-version":"2023-06-01","Content-Type":"application/json"})
    if r.ok:
        txt = r.json()["content"][0]["text"].strip().replace("```json","").replace("```","").strip()
        try: return json.loads(txt)
        except: return {}
    return {}

def get_owners(token):
    r = requests.get("https://api.hubapi.com/crm/v3/owners", headers=hdr(token))
    return r.json().get("results",[]) if r.ok else []

def find_owner_id(owners, email):
    for o in owners:
        if o.get("email","").lower() == email.lower(): return str(o["id"])
    return "162107431"

def hs_search(token, obj, keyword, props=["name","hs_object_id"], limit=5):
    r = requests.post(f"https://api.hubapi.com/crm/v3/objects/{obj}/search",
        json={"query": keyword, "properties": props, "limit": limit},
        headers=hdr(token))
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

def make_deal(token, name, cid, company_id, alliance_id, job_id, oid):
    assocs = []
    if cid:        assocs.append({"to":{"id":cid},        "types":[{"associationCategory":"HUBSPOT_DEFINED","associationTypeId":3}]})
    if company_id: assocs.append({"to":{"id":company_id}, "types":[{"associationCategory":"HUBSPOT_DEFINED","associationTypeId":5}]})
    if alliance_id:assocs.append({"to":{"id":alliance_id},"types":[{"associationCategory":"USER_DEFINED","associationTypeId":DEAL_TO_ALLIANCE_ID}]})
    if job_id:     assocs.append({"to":{"id":job_id},     "types":[{"associationCategory":"USER_DEFINED","associationTypeId":DEAL_TO_JOB_ID}]})
    r = requests.post("https://api.hubapi.com/crm/v4/objects/deals", headers=hdr(token),
        json={"properties":{"dealname":name,"pipeline":PIPELINE,"dealstage":DEAL_STAGE,
              "hubspot_owner_id":oid,"shiboudo":"第一志望群",
              "qiu_zhi_zhe_shi_dianno_song_zhu_mei":"竹","suisen":ms(date.today())},
              "associations":assocs})
    return r.json()

# ── メイン ────────────────────────────────────────────────
def main():
    st.title("🏢 Hamocy 候補者登録")

    # セッション初期化
    for key in ["extracted","job_candidates","owner_id"]:
        if key not in st.session_state:
            st.session_state[key] = {} if key != "owner_id" else "162107431"

    # ── サイドバー ──────────────────────────────────────
    with st.sidebar:
        st.header("⚙️ 設定")
        token   = st.secrets.get("HUBSPOT_TOKEN","")   or st.text_input("HubSpot Token", type="password")
        api_key = st.secrets.get("ANTHROPIC_API_KEY","") or st.text_input("Anthropic API Key", type="password")

        # メアドはセッション保持
        if "user_email" not in st.session_state:
            st.session_state.user_email = ""
        email_input = st.text_input("担当者メール", value=st.session_state.user_email,
                                    placeholder="m.nagayoshi@hamocy.com")
        if email_input != st.session_state.user_email:
            st.session_state.user_email = email_input
            if token:
                st.session_state.owner_id = find_owner_id(get_owners(token), email_input)

        if st.session_state.user_email:
            st.caption(f"担当者ID: {st.session_state.owner_id}")

    if not token:
        st.info("サイドバーにTokenを入力してください")
        return

    oid = st.session_state.owner_id

    # ── 入力方法 ──────────────────────────────────────
    st.subheader("📥 候補者情報")
    method = st.radio("入力方法", ["📄 PDFアップロード","📝 テキスト貼り付け"], horizontal=True)

    input_ready = False
    if method == "📄 PDFアップロード":
        f = st.file_uploader("履歴書PDFをドラッグ＆ドロップ", type=["pdf"], label_visibility="collapsed")
        if f:
            st.session_state["_pdf_bytes"] = f.read()
            input_ready = True
    else:
        txt = st.text_area("候補者情報を貼り付け", height=180, placeholder="氏名、生年月日、連絡先、学歴・職歴など...")
        if txt:
            st.session_state["_paste_text"] = txt
            input_ready = True

    st.divider()

    # ── アライアンス ──────────────────────────────────
    st.subheader("🤝 アライアンス先")
    alliance_input = st.text_input("アライアンス名（部分入力でOK）",
                                   placeholder="NowYouSee / インバウンドテクノロジー など")

    st.divider()

    # ── 取引 ─────────────────────────────────────────
    st.subheader("📋 取引")
    num = st.number_input("取引数", min_value=1, max_value=8, value=1)
    deals_in = []
    for i in range(int(num)):
        cols = st.columns([3,2,2])
        with cols[0]: co  = st.text_input(f"会社名 {i+1}（部分入力でOK）", key=f"co_{i}")
        with cols[1]: loc = st.selectbox(f"勤務地 {i+1}", PREFS, key=f"loc_{i}")
        with cols[2]: pos = st.text_input(f"ポジション名 {i+1}", placeholder="営業職/出張 など", key=f"pos_{i}")
        deals_in.append({"company":co,"location":loc,"position":pos})

    st.divider()

    # ── STEP1: 求人を検索 ────────────────────────────
    if st.button("🔍 求人を検索して確認", use_container_width=True):
        if not input_ready:
            st.error("候補者情報を入力してください")
        else:
            with st.spinner("情報を読み取り中..."):
                # AI抽出
                if method == "📄 PDFアップロード":
                    b64 = base64.standard_b64encode(st.session_state["_pdf_bytes"]).decode()
                    blocks = [{"type":"document","source":{"type":"base64","media_type":"application/pdf","data":b64}}]
                else:
                    blocks = [{"type":"text","text":st.session_state["_paste_text"]}]
                st.session_state.extracted = extract_info(blocks, api_key)

            with st.spinner("求人を検索中..."):
                # 各取引の求人候補を取得
                candidates = {}
                for i, d in enumerate(deals_in):
                    if d["company"]:
                        jobs = hs_search(token, "p243432503_job", d["company"])
                        candidates[i] = jobs
                st.session_state.job_candidates = candidates
                st.session_state.deals_snapshot = deals_in
            st.success("✅ 求人候補を取得しました。下で確認・選択してください")

    # ── 求人選択UI ───────────────────────────────────
    if st.session_state.get("job_candidates") and st.session_state.get("extracted"):
        st.subheader("📄 求人の確認・選択")
        selected_jobs = {}
        for i, d in enumerate(st.session_state.get("deals_snapshot", deals_in)):
            if not d["company"]: continue
            cands = st.session_state.job_candidates.get(i, [])
            st.markdown(f"**取引 {i+1}: {d['company']}**")
            if cands:
                options = {"紐付けなし": None}
                options.update({c["properties"].get("name","(名称なし)"): c["id"] for c in cands})
                sel = st.selectbox(f"求人を選択", list(options.keys()), key=f"job_sel_{i}")
                selected_jobs[i] = options[sel]
            else:
                st.caption("　→ 求人が見つかりませんでした（紐付けなし）")
                selected_jobs[i] = None

        ex = st.session_state.extracted
        with st.expander("📋 読み取り内容", expanded=False):
            st.json(ex)

        st.divider()

        # ── STEP2: 登録実行 ──────────────────────────
        if st.button("✅ 登録実行", type="primary", use_container_width=True):
            ex = st.session_state.extracted
            ln = ex.get("lastname","")
            fn = ex.get("firstname","")
            if not ln or not fn:
                st.error("氏名が読み取れませんでした")
                return

            with st.spinner("HubSpotに登録中..."):

                # 生年月日・年齢
                bd_str = ex.get("birthdate")
                try:   bd = date.fromisoformat(bd_str)
                except: bd = None
                age_val = str(calc_age(bd)) if bd else ""

                # 重複チェック
                existing = hs_search(token,"contacts",f"{ln} {fn}",["firstname","lastname","email"])
                eid = existing[0]["id"] if existing else None
                if eid: st.warning(f"⚠️ 既存コンタクト (ID:{eid}) → 更新します")

                # アライアンス
                alliance_id, alliance_name = None, alliance_input
                if alliance_input:
                    ar = hs_search(token,"p243432503_alliance", alliance_input, limit=3)
                    if ar:
                        # 部分一致で最も近いものを選択
                        best = min(ar, key=lambda x: abs(len(x["properties"].get("name","")) - len(alliance_input)))
                        alliance_id   = best["id"]
                        alliance_name = best["properties"].get("name", alliance_input)
                        st.info(f"🤝 アライアンス: {alliance_name}")

                # 希望勤務地 = 取引1の勤務地
                kibou = (st.session_state.deals_snapshot or deals_in)[0]["location"] if deals_in else "東京"

                keiken_num = ex.get("keiken") or 1
                try: keiken_num = int(str(keiken_num))
                except: keiken_num = 1

                props = {
                    "lastname":         ln,
                    "firstname":        fn,
                    "furigana":         ex.get("furigana") or "",
                    "mobilephone":      ex.get("phone") or "",
                    "email":            ex.get("email") or "",
                    "state":            ex.get("state") or "",
                    "seinengappi":      ms(bd) if bd else "",
                    "date_of_birth":    ms(bd) if bd else "",
                    "age":              age_val,
                    "saisyuu_gakureki": ex.get("gakureki") or "",
                    "syusshin":         ex.get("syusshin") or "",
                    "genshoku":         ex.get("genshoku") or "",
                    "keiken_syasuu":    f"{keiken_num}社",
                    "kiboukinmuchi":    kibou,
                    "ryunyu_chanel":    "アライアンス",
                    "oubobi":           ms(date.today()),
                    "hs_lead_status":   "推薦",
                    "rank":             "D",
                    "hubspot_owner_id": oid,
                    "alaiancekigyou":   alliance_name,
                }
                props = {k:v for k,v in props.items() if v}

                cid, ok = upsert_contact(token, props, eid)
                if not cid:
                    st.error("コンタクト登録に失敗しました")
                    return

                action = "更新" if eid else "新規作成"
                st.success(f"✅ コンタクト{action} (ID:{cid})")

                if alliance_id:
                    ok2 = assoc_contact_alliance(token, cid, alliance_id)
                    st.success("✅ アライアンス紐付け完了") if ok2 else st.warning("⚠️ アライアンス紐付け失敗")

                # 取引作成
                snap = st.session_state.get("deals_snapshot", deals_in)
                for i, d in enumerate(snap):
                    if not d["company"]: continue

                    co_res  = hs_search(token,"companies", d["company"])
                    co_id   = co_res[0]["id"] if co_res else None
                    job_id  = selected_jobs.get(i)

                    if co_id:  st.info(f"🏢 {co_res[0]['properties'].get('name', d['company'])}")
                    if job_id: st.info(f"📄 求人紐付け済み")

                    parts = [d["company"], d["location"]]
                    if d["position"]: parts.append(d["position"])
                    deal_name = "/".join(parts)

                    dr  = make_deal(token, deal_name, cid, co_id, alliance_id, job_id, oid)
                    did = dr.get("id")
                    if did:
                        url = f"https://app.hubspot.com/contacts/{PORTAL_ID}/record/0-3/{did}"
                        st.success(f"✅ 取引: [{deal_name}]({url})")
                    else:
                        st.error(f"取引{i+1}エラー: {dr}")

                st.link_button("🔗 コンタクトをHubSpotで確認",
                               f"https://app.hubspot.com/contacts/{PORTAL_ID}/record/0-1/{cid}")

                # セッションリセット
                st.session_state.extracted      = {}
                st.session_state.job_candidates = {}

if __name__ == "__main__":
    main()
