import streamlit as st
import requests
from datetime import date, datetime, timezone
import json, base64

st.set_page_config(page_title="アライアンス先求職者登録", page_icon="🏢", layout="centered")

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

def hs_search(token, obj, keyword, props=["name","hs_object_id"], limit=100):
    r = requests.post(f"https://api.hubapi.com/crm/v3/objects/{obj}/search",
        json={"query": keyword, "properties": props, "limit": limit},
        headers=hdr(token))
    if not r.ok:
        st.warning(f"🔴 検索エラー [{obj}]: {r.status_code} - {r.text[:200]}")
        return []
    return r.json().get("results",[])

def search_by_tokens(token, obj, prop, keyword, props, limit=100):
    """キーワードをトークンに分割してCONTAINS_TOKENで検索し結果をマージ"""
    # 全角・半角スペースで分割、空文字除去
    tokens = [t for t in keyword.replace("　"," ").split() if t]
    if not tokens:
        return []
    seen = {}
    for tok in tokens:
        r = requests.post(f"https://api.hubapi.com/crm/v3/objects/{obj}/search",
            json={"filterGroups":[{"filters":[{"propertyName":prop,"operator":"CONTAINS_TOKEN","value":tok}]}],
                  "properties":props,"limit":limit},
            headers=hdr(token))
        if r.ok:
            for item in r.json().get("results",[]):
                cid = item["id"]
                if cid not in seen:
                    seen[cid] = {"item": item, "score": 0}
                seen[cid]["score"] += 1  # マッチしたトークン数をスコアに
    # スコア降順（多くのトークンにマッチしたものが上位）
    return [v["item"] for v in sorted(seen.values(), key=lambda x: -x["score"])]

def hs_search_alliance(token, keyword, limit=30):
    results = search_by_tokens(token, "p243432503_alliance", "name", keyword,
                               ["name","hs_object_id"], limit)
    if not results:
        # フォールバック: queryで再試行
        results = hs_search(token, "p243432503_alliance", keyword, ["name","hs_object_id"], limit)
    return results

def hs_search_job(token, keyword, limit=100):
    results = search_by_tokens(token, "p243432503_job", "job_name", keyword,
                               ["job_name","hs_object_id"], limit)
    if not results:
        # フォールバック: queryで再試行
        r2 = requests.post("https://api.hubapi.com/crm/v3/objects/p243432503_job/search",
            json={"query": keyword, "properties": ["job_name","hs_object_id"], "limit": limit},
            headers=hdr(token))
        if r2.ok:
            results = r2.json().get("results",[])
        else:
            st.warning(f"🔴 求人検索エラー: {r2.status_code}")
    return results

def upsert_contact(token, props, eid=None):
    if eid:
        r = requests.patch(f"https://api.hubapi.com/crm/v3/objects/contacts/{eid}",
            json={"properties":props}, headers=hdr(token))
        return (eid if r.ok else None), r.json()
    r = requests.post("https://api.hubapi.com/crm/v3/objects/contacts",
        json={"properties":props}, headers=hdr(token))
    d = r.json()
    return d.get("id"), d

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
    # セッション初期化
    for key in ["extracted","job_candidates","owner_id"]:
        if key not in st.session_state:
            st.session_state[key] = {} if key != "owner_id" else "162107431"
    if "selected_job_ids" not in st.session_state:
        st.session_state.selected_job_ids = {}
    if "job_search_cache" not in st.session_state:
        st.session_state.job_search_cache = {}

    # ── サイドバー ──────────────────────────────────────
    with st.sidebar:
        st.header("⚙️ 設定")
        token   = st.secrets.get("HUBSPOT_TOKEN","")   or st.text_input("HubSpot Token", type="password")
        api_key = st.secrets.get("ANTHROPIC_API_KEY","") or st.text_input("Anthropic API Key", type="password")

        OWNERS = {
            "服部 健大": "82268477",
            "平田 峻一": "160024984",
            "細川 理子": "165897133",
            "永芳 昌裕": "162107431",
        }
        # URLパラメータから担当者を取得（ブックマーク対応）
        params = st.query_params
        url_owner = params.get("owner", "")
        if "selected_owner" not in st.session_state:
            # URLパラメータに一致する担当者があれば自動選択
            st.session_state.selected_owner = url_owner if url_owner in OWNERS else list(OWNERS.keys())[0]

        owner_idx = list(OWNERS.keys()).index(st.session_state.selected_owner) \
                    if st.session_state.selected_owner in OWNERS else 0
        selected_owner = st.selectbox("担当者を選択", list(OWNERS.keys()),
                                      index=owner_idx, key="owner_select")
        st.session_state.selected_owner = selected_owner
        # URLパラメータを更新（ブックマーク用）
        st.query_params["owner"] = selected_owner
        oid = OWNERS[selected_owner]
        st.caption(f"担当者ID: {oid}")
        st.caption(f"🔖 このURLをブックマーク登録すると次回自動選択されます")

    # タイトル（サイドバー後に表示）
    st.title("🏢 アライアンス先求職者登録")
    st.markdown(f"<p style='color:#888;font-size:14px;margin-top:-12px;'>担当者：<strong style='color:#333;'>{selected_owner}</strong> で作成</p>",
                unsafe_allow_html=True)

    if not token:
        st.info("サイドバーにTokenを入力してください")
        return

    # ── 入力方法 ──────────────────────────────────────
    st.subheader("📥 候補者情報")
    method = st.radio("入力方法", ["📄 PDFアップロード","📝 テキスト貼り付け"], horizontal=True)

    input_ready = False
    if method == "📄 PDFアップロード":
        st.markdown("""
        <style>
        [data-testid="stFileUploader"] section {
            background: #f0f7ff;
            border: 2px dashed #4a9eff;
            border-radius: 12px;
            padding: 20px;
        }
        [data-testid="stFileUploader"] section > div {
            color: #4a9eff;
            font-weight: bold;
        }
        [data-testid="stFileUploader"] section p {
            color: #4a9eff !important;
        }
        [data-testid="stFileUploader"] button {
            display: none;
        }
        </style>
        <p style='color:#4a9eff;font-size:13px;margin:4px 0 2px 0;'>
        📎 履歴書PDFをドラッグ＆ドロップ、またはクリックしてファイルを選択
        </p>
        """, unsafe_allow_html=True)
        f = st.file_uploader("", type=["pdf"], label_visibility="collapsed")
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
    if "num_deals" not in st.session_state:
        st.session_state.num_deals = 1

    deals_in = []
    for i in range(st.session_state.num_deals):
        cols = st.columns([3,2,2])
        with cols[0]: co  = st.text_input(f"会社名 {i+1}（部分入力でOK）", key=f"co_{i}")
        with cols[1]: loc = st.selectbox(f"勤務地 {i+1}", PREFS, key=f"loc_{i}")
        with cols[2]: pos = st.text_input(f"ポジション名 {i+1}", placeholder="営業職/出張 など", key=f"pos_{i}")
        deals_in.append({"company":co,"location":loc,"position":pos})

    if st.button("＋ 取引を追加", key="add_deal"):
        st.session_state.num_deals += 1
        st.rerun()

    st.divider()

    # ── STEP1: 検索 ──────────────────────────────
    if st.button("🔍 アライアンス・求人を検索して確認", use_container_width=True):
        if not input_ready:
            st.error("候補者情報を入力してください")
        else:
            with st.spinner("情報を読み取り中..."):
                if method == "📄 PDFアップロード":
                    b64 = base64.standard_b64encode(st.session_state["_pdf_bytes"]).decode()
                    blocks = [{"type":"document","source":{"type":"base64","media_type":"application/pdf","data":b64}}]
                else:
                    blocks = [{"type":"text","text":st.session_state["_paste_text"]}]
                st.session_state.extracted = extract_info(blocks, api_key)

            with st.spinner("アライアンス・求人を検索中..."):
                # アライアンス: 記号・スペースを除去して検索精度向上
                def normalize(s):
                    return s.replace("・","").replace("　","").replace(" ","").replace("株式会社","").lower()
                al_norm = normalize(alliance_input) if alliance_input else ""
                al_results = hs_search_alliance(token, alliance_input) if alliance_input else []
                # 正規化した名前でソート
                if al_results:
                    al_results.sort(key=lambda c: 0 if normalize(c["properties"].get("name","")) == al_norm
                                    else (1 if al_norm in normalize(c["properties"].get("name","")) else 2))
                st.session_state.alliance_candidates = al_results
                # 求人: 会社名+勤務地+ポジションを全て含めて初期検索
                candidates = {}
                for i, d in enumerate(deals_in):
                    if d["company"]:
                        init_kw = " ".join(filter(None, [d["company"], d["location"], d["position"]]))
                        candidates[i] = hs_search_job(token, init_kw)
                st.session_state.job_candidates = candidates
                st.session_state.deals_snapshot = deals_in
            st.success("✅ 候補を取得しました。下で確認・選択してください")

    # ── 選択UI ───────────────────────────────────
    if st.session_state.get("extracted") and st.session_state.get("job_candidates") is not None:

        # アライアンス選択
        st.subheader("🤝 アライアンス先の確認・選択")
        alliance_cands = st.session_state.get("alliance_candidates", [])
        selected_alliance_id   = None
        selected_alliance_name = alliance_input

        if alliance_cands:
            al_options = {"紐付けなし": (None, alliance_input)}
            for c in alliance_cands:
                nm = c["properties"].get("name","(名称なし)")
                al_options[nm] = (c["id"], nm)
            keys = list(al_options.keys())
            # デフォルトは最も一致度が高いもの（2番目＝1番目の候補）
            default_idx = 1 if len(keys) > 1 else 0
            al_sel = st.selectbox(f"アライアンスを選択（{len(alliance_cands)}件）",
                                  keys, index=default_idx, key="alliance_sel")
            selected_alliance_id, selected_alliance_name = al_options[al_sel]
            if selected_alliance_id:
                st.caption(f"✅ 選択中: {al_sel}")
        elif alliance_input:
            st.caption("アライアンスが見つかりませんでした")

        st.divider()

        # 求人選択
        st.subheader("📄 求人の確認・選択")
        for i, d in enumerate(st.session_state.get("deals_snapshot", deals_in)):
            if not d["company"]: continue
            st.markdown(f"**取引 {i+1}: {d['company']}**")

            # 再検索フラグをセッションで管理
            resrch_flag_key = f"show_kw_{i}"
            if resrch_flag_key not in st.session_state:
                st.session_state[resrch_flag_key] = False

            # 初回は自動検索、再検索ボタンで検索欄を表示
            if i not in st.session_state.job_search_cache:
                init_kw = " ".join(filter(None, [d["company"], d["location"], d["position"]]))
                if init_kw:
                    results = hs_search_job(token, init_kw)
                    co_token = d["company"].lower()
                    tokens = [t.lower() for t in init_kw.replace("　"," ").split() if t]
                    def relevance(c, toks=tokens, co=co_token):
                        jn = c["properties"].get("job_name","").lower()
                        if co and co not in jn: return 1000
                        matched = sum(1 for t in toks if t in jn)
                        return -matched
                    st.session_state.job_search_cache[i] = sorted(results, key=relevance)
                else:
                    st.session_state.job_search_cache[i] = []

            cands = st.session_state.job_search_cache.get(i, [])

            # キーワード検索欄（再検索ボタンを押した時のみ表示）
            if st.session_state[resrch_flag_key]:
                kw_key = f"job_kw_{i}"
                if kw_key not in st.session_state:
                    st.session_state[kw_key] = " ".join(filter(None, [d["company"], d["location"], d["position"]]))
                kw = st.text_input("求人キーワード検索", key=kw_key)
                if st.button("🔍 この条件で検索", key=f"do_srch_{i}"):
                    pos_kw = d["position"].strip() if d["position"] else ""
                    loc_kw = d["location"].strip() if d["location"] else ""
                    combined_kw = " ".join(filter(None, [kw, loc_kw, pos_kw]))
                    if combined_kw:
                        results = hs_search_job(token, combined_kw)
                        co_token = d["company"].lower()
                        tokens2 = [t.lower() for t in combined_kw.replace("　"," ").split() if t]
                        def relevance2(c, toks=tokens2, co=co_token):
                            jn = c["properties"].get("job_name","").lower()
                            if co and co not in jn: return 1000
                            matched = sum(1 for t in toks if t in jn)
                            return -matched
                        st.session_state.job_search_cache[i] = sorted(results, key=relevance2)
                        st.session_state[resrch_flag_key] = False
                        st.rerun()

            if cands:
                opts = {"紐付けなし": None}
                opts.update({c["properties"].get("job_name","(名称なし)"): c["id"] for c in cands})
                keys = list(opts.keys())
                default_idx = 1 if len(keys) > 1 else 0
                sel_key = f"job_sel_{i}"
                # 目立つスタイルでselectbox表示
                st.markdown("<div style='background:#f0f7ff;border:1.5px solid #4a9eff;border-radius:8px;padding:8px 12px 4px 12px;margin:4px 0 8px 0;'>", unsafe_allow_html=True)
                sel = st.selectbox(f"🔖 求人を選択（{len(cands)}件ヒット）", keys,
                                   index=default_idx, key=sel_key)
                st.markdown("</div>", unsafe_allow_html=True)
                st.session_state.selected_job_ids[i] = opts.get(sel)
                if st.session_state.selected_job_ids[i]:
                    st.success(f"✅ {sel}")
                # 再検索ボタン
                if st.button("🔄 別の求人を探す", key=f"resrch_{i}"):
                    st.session_state[resrch_flag_key] = True
                    st.rerun()
            else:
                st.warning("求人が見つかりませんでした")
                st.session_state.selected_job_ids[i] = None
                if st.button("🔄 キーワードを変えて再検索", key=f"resrch_{i}"):
                    st.session_state[resrch_flag_key] = True
                    st.rerun()

        ex = st.session_state.extracted
        with st.expander("📋 読み取り内容", expanded=False):
            st.json(ex)

        st.divider()
        st.divider()

        # ── STEP2: 登録実行 ──────────────────────
        # 登録ボタン押下でフラグをセット
        if st.button("✅ 登録実行", type="primary", use_container_width=True):
            st.session_state.do_register   = True
            st.session_state.confirm_existing = None
            st.session_state.found_contact  = None
            st.rerun()

        # 登録フロー（ボタン外で実行）
        if st.session_state.get("do_register"):
            ex = st.session_state.extracted
            ln = ex.get("lastname","")
            fn = ex.get("firstname","")

            if not ln or not fn:
                st.error("氏名が読み取れませんでした")
                st.session_state.do_register = False
            else:
                # 既存コンタクト検索（未検索の場合のみ）
                if st.session_state.get("found_contact") is None and st.session_state.confirm_existing is None:
                    existing = hs_search(token,"contacts",f"{ln} {fn}",["firstname","lastname","email"])
                    if existing:
                        st.session_state.found_contact = existing[0]
                    else:
                        st.session_state.found_contact = False  # 見つからなかった

                # 確認ダイアログ
                fc = st.session_state.get("found_contact")
                if fc and st.session_state.confirm_existing is None:
                    ex_name  = f"{fc['properties'].get('lastname','')} {fc['properties'].get('firstname','')}".strip()
                    ex_email = fc['properties'].get('email','')
                    st.warning(f"⚠️ **{ex_name}**（{ex_email}）のコンタクトが見つかりました。")
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("✏️ 既存コンタクトを更新", use_container_width=True, type="primary"):
                            st.session_state.confirm_existing = "update"
                            st.rerun()
                    with col2:
                        if st.button("➕ 新規コンタクトとして作成", use_container_width=True):
                            st.session_state.confirm_existing = "new"
                            st.rerun()
                else:
                    # 確認済み or 既存なし → 登録実行
                    if st.session_state.confirm_existing == "update" and fc:
                        eid = fc["id"]
                    else:
                        eid = None

                    with st.spinner("HubSpotに登録中..."):
                        bd_str = ex.get("birthdate")
                        try:   bd = date.fromisoformat(bd_str)
                        except: bd = None
                        age_val = str(calc_age(bd)) if bd else ""

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
                            "alaiancekigyou":   selected_alliance_name,
                        }
                        props = {k:v for k,v in props.items() if v}

                        cid, ok = upsert_contact(token, props, eid)
                        if not cid:
                            st.error(f"コンタクト登録に失敗しました: {ok}")
                            st.json(props)
                        else:
                            action = "更新" if eid else "新規作成"
                            st.success(f"✅ コンタクト{action} (ID:{cid})")

                            if selected_alliance_id:
                                ok2 = assoc_contact_alliance(token, cid, selected_alliance_id)
                                if ok2:
                                    st.success("✅ コンタクト-アライアンス紐付け完了")
                                else:
                                    st.warning("⚠️ コンタクト-アライアンス紐付け失敗")

                            snap = st.session_state.get("deals_snapshot", deals_in)
                            for i, d in enumerate(snap):
                                if not d["company"]: continue
                                co_res = hs_search(token,"companies", d["company"])
                                co_id  = co_res[0]["id"] if co_res else None
                                job_id = st.session_state.selected_job_ids.get(i)

                                if job_id:
                                    cache = st.session_state.job_search_cache.get(i, [])
                                    job_name = next((c["properties"].get("job_name","") for c in cache if c["id"] == job_id), "")
                                    if job_name and "】" in job_name:
                                        bracket_end = job_name.index("】") + 1
                                        company_part = job_name[:bracket_end]
                                        position_part = job_name[bracket_end:].strip()
                                        deal_name = f"{company_part}{d['location']}_{position_part}"
                                    else:
                                        deal_name = job_name or "/".join(filter(None,[d["company"],d["location"],d["position"]]))
                                else:
                                    parts = [d["company"], d["location"]]
                                    if d["position"]: parts.append(d["position"])
                                    deal_name = "/".join(parts)

                                dr  = make_deal(token, deal_name, cid, co_id, selected_alliance_id, job_id, oid)
                                did = dr.get("id")
                                if did:
                                    url = f"https://app.hubspot.com/contacts/{PORTAL_ID}/record/0-3/{did}"
                                    st.success(f"✅ 取引: [{deal_name}]({url})")
                                else:
                                    st.error(f"取引{i+1}エラー: {dr}")

                            st.link_button("🔗 コンタクトをHubSpotで確認",
                                           f"https://app.hubspot.com/contacts/{PORTAL_ID}/record/0-1/{cid}")

                            # リセット
                            st.session_state.extracted           = {}
                            st.session_state.job_candidates      = {}
                            st.session_state.alliance_candidates = []
                            st.session_state.selected_job_ids   = {}
                            st.session_state.job_search_cache   = {}
                            st.session_state.num_deals          = 1
                            st.session_state.confirm_existing   = None
                            st.session_state.found_contact      = None
                            st.session_state.do_register        = False

if __name__ == "__main__":
    main()
