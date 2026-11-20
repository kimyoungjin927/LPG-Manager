import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from datetime import datetime, date
import io

st.set_page_config(page_title="LPG 공급·검침 통합관리", page_icon="🔥", layout="wide")

def get_engine():
    url_obj = URL.create(
        drivername="postgresql+psycopg2",
        username=st.secrets["DB_USER"],
        password=st.secrets["DB_PASS"],
        host=st.secrets["DB_HOST"],
        port=int(st.secrets["DB_PORT"]),
        database=st.secrets["DB_NAME"]
    )
    return create_engine(url_obj, connect_args={"sslmode": "require"}, pool_pre_ping=True)

engine = get_engine()

def init_initial_customers():
    with engine.begin() as conn:
        if conn.execute(text("SELECT COUNT(*) FROM customers")).scalar() == 0:
            initial_customers = [
                ("가마로통닭**", "25kPa", 50, 4, 2, None, "미지정"),
                ("거산푸드**", "25kPa", 50, 4, 2, None, "미지정"),
                ("갤러리카페어비움", "2.8kPa", 20, 4, 2, None, "미지정"),
                ("경남빌라나/B02", "2.8kPa", 50, 2, 1, None, "미지정"),
                ("고래떡볶이", "2.8kPa", 20, 4, 2, None, "미지정"),
                ("고향**(집합)", "25kPa", 50, 4, 2, None, "미지정"),
                ("군지앞읍행정복지센터", "25kPa", 50, 4, 2, None, "미지정"),
                ("괘랑4길16-23 A동(집합)", "25kPa", 50, 4, 2, None, "미지정"),
                ("괘랑4길16-23 B동", "2.8kPa", 50, 2, 1, None, "미지정"),
                ("괘랑4길16-25(최옥순)", "2.8kPa", 20, 6, 3, None, "미지정"),
                ("교통안전공단**", "2.8kPa", 50, 2, 1, None, "미지정"),
                ("구문천2길56-4", "2.8kPa", 20, 2, 1, None, "미지정"),
                ("구자승주택", "2.8kPa", 50, 2, 1, None, "미지정"),
                ("금송정**(집합)", "25kPa", 50, 6, 3, None, "미지정"),
                ("김가소채관**", "25kPa", 20, 4, 2, None, "미지정"),
                ("김가소채관2층", "2.8kPa", 20, 4, 2, None, "미지정"),
                ("김밥마을만두나라원곡", "25kPa", 50, 4, 2, None, "미지정"),
                ("꼼지네가든 1 **(집합)", "2.8kPa", 50, 2, 1, None, "미지정"),
                ("꼼지네가든 2 **(집합)", "2.8kPa", 20, 2, 1, None, "미지정"),
                ("내삼미동회관", "2.8kPa", 20, 2, 1, None, "미지정"),
                ("능평리주택(집합)", "25kPa", 50, 6, 3, None, "미지정"),
                ("당성로36-6", "2.8kPa", 50, 2, 1, None, "미지정"),
                ("대영산업**", "2.8kPa", 50, 2, 1, None, "미지정"),
                ("더본컴퍼니**", "25kPa", 50, 4, 2, None, "미지정"),
                ("도근만주택", "2.8kPa", 20, 2, 1, None, "미지정"),
                ("독산성로270번길64", "2.8kPa", 50, 2, 1, None, "미지정"),
            ]
            for name, press, kg, cnt, sup, cf, mgr in initial_customers:
                conn.execute(
                    text("INSERT INTO customers (name, pressure, tank_kg, tank_count, default_supply, custom_factor, manager_name) VALUES (:n,:p,:kg,:cnt,:sup,:cf,:mg) ON CONFLICT (name) DO NOTHING"),
                    {"n": name, "p": press, "kg": kg, "cnt": cnt, "sup": sup, "cf": cf, "mg": mgr}
                )

def get_data():
    with engine.connect() as conn:
        s_df = pd.read_sql(text("SELECT * FROM settings"), conn)
        c_df = pd.read_sql(text("SELECT * FROM customers ORDER BY name"), conn)
        l_df = pd.read_sql(text("SELECT * FROM logs ORDER BY visit_date ASC, id ASC"), conn)
        st_df = pd.read_sql(text("SELECT * FROM staff ORDER BY name"), conn)
    return s_df, c_df, l_df, st_df

def calculate_all_logs(settings_df, customers_df, logs_df):
    if logs_df.empty:
        return pd.DataFrame()
    settings = dict(zip(settings_df["key"], settings_df["value"]))
    f_28 = settings.get("factor_2_8kpa", 2.00)
    f_25 = settings.get("factor_25kpa", 2.50)
    cust_map = customers_df.set_index("name").to_dict("index")
    rows = []

    for cust_name, group in logs_df.groupby("customer_name", sort=False):
        c_info = cust_map.get(cust_name, {"pressure": "2.8kPa", "tank_kg": 50, "tank_count": 2, "custom_factor": None})
        factor = float(c_info["custom_factor"]) if (pd.notna(c_info["custom_factor"]) and c_info["custom_factor"] > 0) else (f_25 if c_info["pressure"] == "25kPa" else f_28)
        tank_kg = float(c_info["tank_kg"])
        prev_meter, prev_remain = None, None

        for _, row in group.iterrows():
            cur_meter = float(row["meter_reading"])
            sup_cnt = int(row["supply_count"])
            act_rem = float(row["actual_remain"]) if pd.notna(row["actual_remain"]) else None

            if prev_meter is None:
                used_m3, used_kg = 0.0, 0.0
                calc_remain = act_rem if act_rem is not None else (tank_kg * c_info["tank_count"])
                error_kg = 0.0 if act_rem is not None else None
            else:
                used_m3 = cur_meter - prev_meter
                used_kg = round(used_m3 * factor, 2)
                expected_remain = round(prev_remain + (sup_cnt * tank_kg) - used_kg, 2)
                calc_remain = act_rem if act_rem is not None else expected_remain
                error_kg = round(act_rem - expected_remain, 2) if act_rem is not None else None

            rows.append({
                "ID": row["id"], "방문일자": str(row["visit_date"]), "작업구분": row["work_type"],
                "거래처명": cust_name, "압력": c_info["pressure"], "적용계수": factor,
                "직전계량기": prev_meter if prev_meter is not None else cur_meter,
                "현재계량기": cur_meter, "사용루베": round(used_m3, 2), "환산사용kg": used_kg,
                "교체통수": sup_cnt, "공급kg": sup_cnt * tank_kg, "실제입력잔량kg": act_rem,
                "계산잔량kg": calc_remain, "검침오차kg": error_kg, "담당자": row["staff_name"], "메모": row["memo"]
            })
            prev_meter, prev_remain = cur_meter, calc_remain

    return pd.DataFrame(rows).sort_values(by=["방문일자", "ID"], ascending=[False, False])
init_initial_customers()
settings_df, customers_df, logs_df, staff_df = get_data()
calc_df = calculate_all_logs(settings_df, customers_df, logs_df)
err_limit = float(settings_df.set_index("key").loc["error_threshold", "value"])

st.title("🔥 LPG 공급·검침 통합관리 시스템")

tab1, tab2, tab3, tab4 = st.tabs(("📱 현장 입력", "📊 거래처 현황", "📅 월간 정산표", "⚙️ 관리자 전용"))

with tab1:
    st.subheader("📱 현장 검침 및 가스통 교체 입력")
    work_mode = st.radio("작업 유형", ("🔍 중간검침 (계량기만)", "🔄 가스통 교체 (계량기+통수+잔량)"), horizontal=True)
    staff_list = staff_df["name"].tolist() if not staff_df.empty else ["미등록직원"]
    cust_list = customers_df["name"].tolist() if not customers_df.empty else ["거래처없음"]

    # 폼 바깥에서 거래처를 먼저 선택해야 담당 직원이 즉시 자동으로 바뀜
    top_c1, top_c2 = st.columns(2)
    visit_dt = top_c1.date_input("방문 일자", value=date.today(), min_value=date(2020, 1, 1), max_value=date(2035, 12, 31))
    selected_cust = top_c2.selectbox("거래처 선택 (상호 검색 가능)", cust_list)

    # 선택한 거래처의 배정된 담당 직원 찾기
    assigned_mgr = "미지정"
    if not customers_df.empty and selected_cust in customers_df["name"].values:
        _, cust_row = next(customers_df[customers_df["name"] == selected_cust].iterrows())
        if pd.notna(cust_row.get("manager_name")):
            assigned_mgr = str(cust_row["manager_name"]).strip()

    default_staff_idx = staff_list.index(assigned_mgr) if assigned_mgr in staff_list else 0

    with st.form("field_input_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        selected_staff = c1.selectbox(
            f"담당 직원 (배정: {assigned_mgr})",
            staff_list,
            index=default_staff_idx,
            key=f"field_staff_{selected_cust}"
        )
        meter_val = c1.number_input("현재 계량기 (루베)", min_value=0.0, step=0.1, format="%.1f")

        if "가스통 교체" in work_mode:
            supply_cnt = c2.number_input("교체 통수", min_value=1, max_value=20, value=2, step=1)
            actual_rem_val = c2.number_input("교체 후 총 잔량 (kg)", min_value=0.0, step=1.0, format="%.1f")
        else:
            supply_cnt, actual_rem_val = 0, None
            c2.info("🔍 중간검침 모드: 계량기 숫자만 입력하면 남은 예상 잔량이 자동 계산됩니다.")

        memo_val = st.text_input("메모 (선택)")
        if st.form_submit_button("✅ 저장 및 자동 계산", use_container_width=True, type="primary"):
            if meter_val <= 0:
                st.error("계량기 숫자를 0보다 크게 입력하세요.")
            else:
                w_type = "가스교체" if "가스통 교체" in work_mode else "중간검침"
                with engine.begin() as conn:
                    conn.execute(
                        text("INSERT INTO logs (visit_date, customer_name, work_type, meter_reading, supply_count, actual_remain, staff_name, memo, created_at) VALUES (:vd,:cn,:wt,:mr,:sc,:ar,:sn,:mm,:ca)"),
                        {"vd": visit_dt.strftime("%Y-%m-%d"), "cn": selected_cust, "wt": w_type, "mr": meter_val, "sc": supply_cnt, "ar": actual_rem_val, "sn": selected_staff, "mm": memo_val, "ca": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                    )
                st.success(f"[{selected_cust}] 저장 완료! (담당: {selected_staff})")
                st.rerun()

    if not calc_df.empty:
        st.divider()
        st.caption("📋 최근 입력 내역 (오입력 삭제 시 왼쪽 `선택` 칸을 체크한 뒤 아래 삭제 버튼을 누르세요)")
        
        view_df = calc_df[["ID", "방문일자", "작업구분", "거래처명", "현재계량기", "환산사용kg", "교체통수", "계산잔량kg", "검침오차kg", "담당자"]].copy()
        view_df.insert(0, "선택", False)

        edited_view = st.data_editor(
            view_df,
            use_container_width=True,
            hide_index=True,
            disabled=["ID", "방문일자", "작업구분", "거래처명", "현재계량기", "환산사용kg", "교체통수", "계산잔량kg", "검침오차kg", "담당자"],
            column_config={
                "선택": st.column_config.CheckboxColumn("선택", default=False, width="small")
            },
            key="field_logs_editor"
        )

        selected_rows = edited_view[edited_view["선택"] == True]
        if not selected_rows.empty:
            if st.button(f"🗑️ 선택한 {len(selected_rows)}건 기록 즉시 삭제", type="primary", use_container_width=True):
                del_ids = selected_rows["ID"].astype(int).tolist()
                with engine.begin() as conn:
                    for did in del_ids:
                        conn.execute(text("DELETE FROM logs WHERE id=:id"), {"id": did})
                st.warning(f"선택한 {len(del_ids)}건의 입력 기록이 삭제되었습니다.")
                st.rerun()

with tab2:
    st.subheader("📊 거래처별 현재 예상 잔량 및 오차 현황")
    staff_filter_opts = ["전체 보기"] + (staff_df["name"].tolist() if not staff_df.empty else []) + ["미지정"]
    sel_mgr = st.selectbox("👤 담당 직원 선택 (선택한 직원의 담당 거래처만 조회)", staff_filter_opts)

    summary_rows = []
    for _, c_row in customers_df.iterrows():
        cname = c_row["name"]
        mgr_name = str(c_row["manager_name"]) if pd.notna(c_row.get("manager_name")) and str(c_row.get("manager_name")).strip() else "미지정"
        if sel_mgr != "전체 보기" and mgr_name != sel_mgr:
            continue

        c_logs = calc_df[calc_df["거래처명"] == cname] if not calc_df.empty else pd.DataFrame()
        if not c_logs.empty:
            _, latest = next(c_logs.iterrows())
            last_date, last_meter, est_remain = latest["방문일자"], latest["현재계량기"], latest["계산잔량kg"]
            valid_err = c_logs.dropna(subset=["검침오차kg"])
            last_error = next(valid_err.iterrows())[1]["검침오차kg"] if not valid_err.empty else 0.0
        else:
            last_date, last_meter, est_remain, last_error = "-", 0.0, 0.0, 0.0

        status = "🚨 오차경고" if last_error <= err_limit else ("⚠️ 배달임박" if (est_remain > 0 and est_remain <= c_row["tank_kg"] * 0.6) else "✅ 정상")
        summary_rows.append({"상태": status, "담당직원": mgr_name, "거래처명": cname, "압력": c_row["pressure"], "구성": f"{c_row['tank_kg']}×{c_row['tank_count']}", "최근방문": last_date, "최신계량기": last_meter, "예상잔량(kg)": est_remain, "최근오차(kg)": last_error})

    sum_df = pd.DataFrame(summary_rows)
    if not sum_df.empty:
        m1, m2, m3 = st.columns(3)
        m1.metric("조회된 거래처", f"{len(sum_df)} 곳")
        m2.metric("⚠️ 배달임박", f"{len(sum_df[sum_df['상태'].str.contains('배달임박')])} 곳")
        m3.metric("🚨 오차경고", f"{len(sum_df[sum_df['상태'].str.contains('오차경고')])} 곳")
        st.dataframe(sum_df, use_container_width=True, hide_index=True)
    else:
        st.info(f"[{sel_mgr}] 담당으로 배정된 거래처가 없습니다.")

with tab3:
    st.subheader("📅 월간 검침·잔량 현황표")
    now = datetime.now()
    y_col, m_col = st.columns(2)
    year_list = list(range(2025, 2031))
    default_y_idx = year_list.index(now.year) if now.year in year_list else 1
    sel_year = y_col.selectbox("조회 연도", year_list, index=default_y_idx, format_func=lambda x: f"{x}년")
    sel_month = m_col.selectbox("조회 월", list(range(1, 13)), index=now.month - 1, format_func=lambda x: f"{x}월")

    target_month = f"{sel_year}-{sel_month:02d}"
    st.caption(f"📌 **{sel_year}년 {sel_month}월** 전체 거래처 일자별 현황 (칸 표시: `계량기 / 계산잔량kg`)")

    month_logs = calc_df[calc_df["방문일자"].str.startswith(target_month)].copy() if not calc_df.empty else pd.DataFrame()
    monthly_matrix = []
    for _, c_row in customers_df.iterrows():
        cname = c_row["name"]
        row_dict = {"거래처명": cname, "압력": c_row["pressure"], "구성": f"{c_row['tank_kg']}×{c_row['tank_count']}"}
        for d in range(1, 32):
            row_dict[f"{d}일"] = ""
        c_m_logs = month_logs[month_logs["거래처명"] == cname] if not month_logs.empty else pd.DataFrame()
        if not c_m_logs.empty:
            for _, l_row in c_m_logs.sort_values("방문일자").iterrows():
                day_num = int(l_row["방문일자"][-2:])
                cell_txt = f"{int(l_row['현재계량기'])}/{int(l_row['계산잔량kg'])}"
                row_dict[f"{day_num}일"] = f"{row_dict[f'{day_num}일']} | {cell_txt}" if row_dict[f"{day_num}일"] else cell_txt
            row_dict["월사용(kg)"] = round(c_m_logs["환산사용kg"].sum(), 1)
            row_dict["월공급(kg)"] = round(c_m_logs["공급kg"].sum(), 1)
            row_dict["월오차(kg)"] = round(c_m_logs["검침오차kg"].dropna().sum(), 1)
        else:
            row_dict["월사용(kg)"], row_dict["월공급(kg)"], row_dict["월오차(kg)"] = 0.0, 0.0, 0.0
        monthly_matrix.append(row_dict)

    st.dataframe(pd.DataFrame(monthly_matrix), use_container_width=True, hide_index=True)
with tab4:
    st.subheader("🔒 관리자 전용 (공급정산 / 설정 / 삭제)")
    if "is_admin" not in st.session_state:
        st.session_state["is_admin"] = False

    if not st.session_state["is_admin"]:
        st.warning("공급(교체) 날짜 요약, 엑셀 정산 다운로드, 직원·거래처 관리, 계절 보정값은 관리자 비밀번호가 필요합니다.")
        pw_input = st.text_input("관리자 비밀번호 입력", type="password")
        if st.button("🔓 관리자 잠금 해제", type="primary", use_container_width=True):
            if pw_input == str(st.secrets.get("ADMIN_PASS", "1234")):
                st.session_state["is_admin"] = True
                st.rerun()
            else:
                st.error("비밀번호가 일치하지 않습니다.")
    else:
        col_top1, col_top2 = st.columns((3, 1))
        col_top1.success("✅ 관리자 모드로 인증되었습니다.")
        if col_top2.button("🔒 잠그기", use_container_width=True):
            st.session_state["is_admin"] = False
            st.rerun()

        st.divider()
        st.subheader("1️⃣ [관리자 전용] 월별 가스 공급(교체) 날짜 요약 & 엑셀")
        ay_col, am_col = st.columns(2)
        a_year = ay_col.selectbox("정산 연도", year_list, index=default_y_idx, format_func=lambda x: f"{x}년", key="admin_y")
        a_month = am_col.selectbox("정산 월", list(range(1, 13)), index=now.month - 1, format_func=lambda x: f"{x}월", key="admin_m")
        a_target = f"{a_year}-{a_month:02d}"

        a_logs = calc_df[calc_df["방문일자"].str.startswith(a_target)].copy() if not calc_df.empty else pd.DataFrame()
        sup_only = a_logs[a_logs["교체통수"] > 0].sort_values("방문일자") if not a_logs.empty else pd.DataFrame()

        supply_summary_rows = []
        for _, c_row in customers_df.iterrows():
            cname = c_row["name"]
            c_sup = sup_only[sup_only["거래처명"] == cname] if not sup_only.empty else pd.DataFrame()
            if not c_sup.empty:
                date_badges = [f"{r['방문일자'][5:]} ({int(r['교체통수'])}통)" for _, r in c_sup.iterrows()]
                supply_summary_rows.append({
                    "거래처명": cname, "압력": c_row["pressure"], "용기규격": f"{c_row['tank_kg']}kg",
                    "공급 횟수": f"{len(c_sup)}회", "총 공급통수": f"{int(c_sup['교체통수'].sum())}통",
                    "총 공급량(kg)": round(c_sup["공급kg"].sum(), 1),
                    "공급 날짜 상세 (월-일 및 통수)": "  /  ".join(date_badges)
                })
        sup_sum_df = pd.DataFrame(supply_summary_rows)

        if not sup_sum_df.empty:
            st.dataframe(sup_sum_df, use_container_width=True, hide_index=True)
            with st.expander(f"📝 {a_year}년 {a_month}월 공급(교체) 상세 건별 내역 보기"):
                st.dataframe(sup_only[["ID", "방문일자", "거래처명", "압력", "교체통수", "공급kg", "현재계량기", "실제입력잔량kg", "검침오차kg", "담당자", "메모"]], use_container_width=True, hide_index=True)
        else:
            st.info(f"{a_year}년 {a_month}월에는 가스통 공급(교체) 내역이 없습니다.")

        a_matrix_rows = []
        for _, c_row in customers_df.iterrows():
            cname = c_row["name"]
            r_dict = {"거래처명": cname, "압력": c_row["pressure"], "구성": f"{c_row['tank_kg']}×{c_row['tank_count']}"}
            for d in range(1, 32):
                r_dict[f"{d}일"] = ""
            c_m = a_logs[a_logs["거래처명"] == cname] if not a_logs.empty else pd.DataFrame()
            if not c_m.empty:
                for _, lr in c_m.sort_values("방문일자").iterrows():
                    dn = int(lr["방문일자"][-2:])
                    ct = f"{int(lr['현재계량기'])}/{int(lr['계산잔량kg'])}"
                    r_dict[f"{dn}일"] = f"{r_dict[f'{dn}일']} | {ct}" if r_dict[f"{dn}일"] else ct
                r_dict["월사용(kg)"] = round(c_m["환산사용kg"].sum(), 1)
                r_dict["월공급(kg)"] = round(c_m["공급kg"].sum(), 1)
                r_dict["월오차(kg)"] = round(c_m["검침오차kg"].dropna().sum(), 1)
            else:
                r_dict["월사용(kg)"], r_dict["월공급(kg)"], r_dict["월오차(kg)"] = 0.0, 0.0, 0.0
            a_matrix_rows.append(r_dict)
        a_matrix_df = pd.DataFrame(a_matrix_rows)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            if not sup_sum_df.empty:
                sup_sum_df.to_excel(writer, index=False, sheet_name=f"{a_month}월_공급날짜요약")
            a_matrix_df.to_excel(writer, index=False, sheet_name=f"{a_month}월_달력정산표")
            if not a_logs.empty:
                a_logs.to_excel(writer, index=False, sheet_name=f"{a_month}월_전체상세기록")
        st.download_button(
            label=f"📥 {a_year}년 {a_month}월 정산표 & 공급요약 엑셀(.xlsx) 다운로드",
            data=output.getvalue(), file_name=f"LPG_관리자정산_{a_target}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary", use_container_width=True
        )

        st.divider()
        st.subheader("2️⃣ 직원 등록 및 삭제")
        sc1, sc2 = st.columns(2)
        with sc1:
            with st.form("add_staff", clear_on_submit=True):
                st.markdown("**➕ 신규 직원 등록**")
                n_staff = st.text_input("직원 이름", placeholder="예: 홍길동")
                n_role = st.selectbox("직무 구분", ("현장기사", "사무관리"))
                if st.form_submit_button("직원 등록하기", type="primary", use_container_width=True) and n_staff.strip():
                    with engine.begin() as conn:
                        conn.execute(text("INSERT INTO staff VALUES (:n,:r,:d) ON CONFLICT (name) DO NOTHING"), {"n": n_staff.strip(), "r": n_role, "d": datetime.now().strftime("%Y-%m-%d")})
                    st.rerun()
        with sc2:
            with st.form("del_staff_form"):
                st.markdown("**🗑️ 기존 직원 삭제**")
                staff_opts = staff_df["name"].tolist() if not staff_df.empty else ["없음"]
                d_staff = st.selectbox("삭제할 직원 선택", staff_opts)
                st.text_input("안내", value="삭제해도 과거 검침 기록은 유지됩니다.", disabled=True)
                if st.form_submit_button("선택한 직원 삭제", use_container_width=True) and d_staff != "없음":
                    with engine.begin() as conn:
                        conn.execute(text("DELETE FROM staff WHERE name=:n"), {"n": d_staff})
                    st.rerun()
        st.divider()
        st.subheader("3️⃣ 거래처 등록 / 기존 거래처 불러와서 수정")
        s_map = settings_df.set_index("key")["value"].to_dict()
        sys_f28 = float(s_map.get("factor_2_8kpa", 2.00))
        sys_f25 = float(s_map.get("factor_25kpa", 2.50))

        cust_options = ["➕ 신규 거래처 직접 입력"] + (customers_df["name"].tolist() if not customers_df.empty else [])
        selected_load_cust = st.selectbox("대상 선택 (기존 거래처를 고르면 아래 칸에 자동 입력됩니다)", cust_options)
        mgr_choices = ["미지정"] + (staff_df["name"].tolist() if not staff_df.empty else [])

        if selected_load_cust != "➕ 신규 거래처 직접 입력":
            _, c_info = next(customers_df[customers_df["name"] == selected_load_cust].iterrows())
            def_name = str(c_info["name"])
            def_press = str(c_info["pressure"])
            def_press_idx = 0 if def_press == "2.8kPa" else 1
            def_tkg_idx = 0 if int(c_info["tank_kg"]) == 20 else 1
            def_tcnt = int(c_info["tank_count"])
            has_custom = pd.notna(c_info["custom_factor"]) and float(c_info["custom_factor"]) > 0
            def_custom_val = float(c_info["custom_factor"]) if has_custom else None
            cur_mgr = str(c_info["manager_name"]) if pd.notna(c_info.get("manager_name")) else "미지정"
            def_mgr_idx = mgr_choices.index(cur_mgr) if cur_mgr in mgr_choices else 0

            c_logs = calc_df[calc_df["거래처명"] == selected_load_cust] if not calc_df.empty else pd.DataFrame()
            if not c_logs.empty:
                _, first_log = next(c_logs.iterrows())
                def_meter = float(first_log["현재계량기"])
                def_remain = float(first_log["계산잔량kg"])
            else:
                def_meter = 0.0
                def_remain = float(int(c_info["tank_kg"]) * int(c_info["tank_count"]))
        else:
            def_name, def_press, def_press_idx, def_tkg_idx, def_tcnt, def_custom_val, def_mgr_idx, def_meter, def_remain = "", "2.8kPa", 0, 1, 2, None, 0, 0.0, 0.0

        r1_c1, r1_c2, r1_c3 = st.columns(3)
        cname = r1_c1.text_input("거래처명 (상호)", value=def_name, key=f"cname_{selected_load_cust}")
        cmgr = r1_c2.selectbox("담당 직원 배정", mgr_choices, index=def_mgr_idx, key=f"cmgr_{selected_load_cust}")
        cpress = r1_c3.selectbox("압력 설정 (변경 시 보정계수 자동입력)", ("2.8kPa", "25kPa"), index=def_press_idx, key=f"cpress_{selected_load_cust}")

        auto_factor = sys_f28 if cpress == "2.8kPa" else sys_f25
        display_factor = def_custom_val if (def_custom_val is not None and cpress == def_press) else auto_factor

        with st.form("add_or_edit_cust"):
            r2_c1, r2_c2, r2_c3 = st.columns(3)
            ctkg = r2_c1.selectbox("용기 규격 (kg)", (20, 50), index=def_tkg_idx)
            ctcnt = r2_c2.number_input("설치 통수", min_value=1, max_value=50, value=def_tcnt)
            ccf = r2_c3.number_input(f"적용 보정계수 ({cpress} 설정값: {auto_factor:.2f})", min_value=0.0, step=0.01, value=display_factor, format="%.2f")

            st.markdown("---")
            save_init_log = st.checkbox("초기 세팅 날짜 및 계량기·잔량 기록 함께 저장 (지난 기록 시작일 입력 시 체크)", value=(selected_load_cust == "➕ 신규 거래처 직접 입력"))
            r3_c1, r3_c2, r3_c3 = st.columns(3)
            idate = r3_c1.date_input("초기 세팅 날짜 (과거 날짜 선택 가능)", value=date.today(), min_value=date(2020, 1, 1), max_value=date(2035, 12, 31))
            imeter = r3_c2.number_input("기준 계량기 (루베)", min_value=0.0, step=0.1, value=def_meter, format="%.1f")
            iremain = r3_c3.number_input("기준 잔량 (kg)", min_value=0.0, step=1.0, value=def_remain, format="%.1f")

            if st.form_submit_button("💾 거래처 정보 및 시작 날짜 저장", type="primary", use_container_width=True):
                clean_cname = cname.strip()
                if not clean_cname:
                    st.error("거래처명을 입력하세요.")
                else:
                    final_cf = None if abs(ccf - auto_factor) < 0.001 else ccf
                    with engine.begin() as conn:
                        if selected_load_cust != "➕ 신규 거래처 직접 입력" and selected_load_cust != clean_cname:
                            conn.execute(text("DELETE FROM customers WHERE name=:old_n"), {"old_n": selected_load_cust})
                        conn.execute(
                            text("""INSERT INTO customers (name, pressure, tank_kg, tank_count, default_supply, custom_factor, manager_name)
                                    VALUES (:n,:p,:kg,:cnt,1,:cf,:mg)
                                    ON CONFLICT (name) DO UPDATE SET pressure=:p, tank_kg=:kg, tank_count=:cnt, custom_factor=:cf, manager_name=:mg"""),
                            {"n": clean_cname, "p": cpress, "kg": ctkg, "cnt": ctcnt, "cf": final_cf, "mg": cmgr}
                        )
                        if save_init_log:
                            conn.execute(
                                text("""INSERT INTO logs (visit_date, customer_name, work_type, meter_reading, supply_count, actual_remain, staff_name, memo, created_at)
                                        VALUES (:vd,:cn,'초기세팅',:mr,0,:ar,'관리자','초기 세팅',:ca)"""),
                                {"vd": idate.strftime("%Y-%m-%d"), "cn": clean_cname, "mr": imeter, "ar": iremain, "ca": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                            )
                    st.success(f"[{clean_cname}] 저장 완료! (세팅일: {idate.strftime('%Y-%m-%d')}, 압력: {cpress}, 계수: {ccf:.2f})")
                    st.rerun()

        if not customers_df.empty:
            with st.expander("🗑️ 기존 거래처 삭제하기"):
                del_c = st.selectbox("삭제할 거래처 선택", customers_df["name"].tolist())
                if st.button("선택한 거래처 영구 삭제", use_container_width=True):
                    with engine.begin() as conn:
                        conn.execute(text("DELETE FROM customers WHERE name=:n"), {"n": del_c})
                    st.warning(f"[{del_c}] 거래처가 삭제되었습니다.")
                    st.rerun()

        st.divider()
        st.subheader("4️⃣ 계절별(여름/겨울) 압력 보정값")
        with st.form("set_form"):
            b1, b2, b3 = st.columns(3)
            v28 = b1.number_input("2.8kPa 계수 (기본 2.00)", value=sys_f28, step=0.01, format="%.2f")
            v25 = b2.number_input("25kPa 계수 (기본 2.50)", value=sys_f25, step=0.01, format="%.2f")
            verr = b3.number_input("오차경고 기준 (kg)", value=float(s_map.get("error_threshold", -10.0)), step=1.0)
            if st.form_submit_button("💾 보정값 저장", type="primary", use_container_width=True):
                with engine.begin() as conn:
                    conn.execute(text("UPDATE settings SET value=:v WHERE key='factor_2_8kpa'"), {"v": v28})
                    conn.execute(text("UPDATE settings SET value=:v WHERE key='factor_25kpa'"), {"v": v25})
                    conn.execute(text("UPDATE settings SET value=:v WHERE key='error_threshold'"), {"v": verr})
                st.success("보정값이 저장되었습니다!")
                st.rerun()

        st.divider()
        st.subheader("5️⃣ 잘못 입력된 검침/교체 기록 삭제")
        if not calc_df.empty:
            with st.form("del_log_form"):
                del_log_id = st.number_input("삭제할 기록의 ID 번호", min_value=1, step=1)
                if st.form_submit_button("🗑️ 해당 ID 기록 삭제", use_container_width=True):
                    with engine.begin() as conn:
                        conn.execute(text("DELETE FROM logs WHERE id=:id"), {"id": int(del_log_id)})
                    st.warning(f"ID {del_log_id}번 기록이 삭제되었습니다.")
                    st.rerun()
