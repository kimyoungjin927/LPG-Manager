import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from datetime import datetime, date
import io
import os

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
    return create_engine(
        url_obj,
        connect_args={"sslmode": "require"},   # ◀ 바로 이 자리에 들어갑니다!
        pool_pre_ping=True
    )

engine = get_engine()


def init_initial_customers():
    with engine.begin() as conn:
        res = conn.execute(text("SELECT COUNT(*) FROM customers")).scalar()
        if res == 0:
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
                    text("INSERT INTO customers (name, pressure, tank_kg, tank_count, default_supply, custom_factor, manager_name) VALUES (:n, :p, :kg, :cnt, :sup, :cf, :mg) ON CONFLICT (name) DO NOTHING"),
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
        if pd.notna(c_info["custom_factor"]) and c_info["custom_factor"] > 0:
            factor = float(c_info["custom_factor"])
        else:
            factor = f_25 if c_info["pressure"] == "25kPa" else f_28

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
                "ID": row["id"], "방문일자": row["visit_date"], "작업구분": row["work_type"],
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

tab1, tab2, tab3, tab4 = st.tabs(["📱 현장 입력", "📊 거래처 현황", "📅 월간 정산표", "⚙️ 설정"])

with tab1:
    st.subheader("📱 현장 검침 및 가스통 교체 입력")
    work_mode = st.radio("작업 유형", ["🔍 중간검침 (계량기만)", "🔄 가스통 교체 (계량기+통수+잔량)"], horizontal=True)
    staff_list = staff_df["name"].tolist() if not staff_df.empty else ["미등록직원"]
    cust_list = customers_df["name"].tolist() if not customers_df.empty else ["거래처없음"]

    with st.form("field_input_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        visit_dt = c1.date_input("방문 일자", value=date.today())
        selected_cust = c1.selectbox("거래처 선택 (상호 검색 가능)", cust_list)
        selected_staff = c1.selectbox("담당 직원", staff_list)

        meter_val = c2.number_input("현재 계량기 (루베)", min_value=0.0, step=0.1, format="%.1f")
        if "가스통 교체" in work_mode:
            supply_cnt = c2.number_input("교체 통수", min_value=1, max_value=20, value=2, step=1)
            actual_rem_val = c2.number_input("교체 후 총 잔량 (kg)", min_value=0.0, step=1.0, format="%.1f")
        else:
            supply_cnt, actual_rem_val = 0, None

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
                st.success(f"[{selected_cust}] 저장 완료!")
                st.rerun()

    if not calc_df.empty:
        st.dataframe(calc_df[["ID", "방문일자", "작업구분", "거래처명", "현재계량기", "환산사용kg", "교체통수", "계산잔량kg", "검침오차kg", "담당자"]], use_container_width=True, hide_index=True)
with tab2:
    st.subheader("📊 거래처별 현재 예상 잔량 및 오차 현황")

    # 담당 직원 필터 드롭다운
    staff_filter_opts = ["전체 보기"] + (staff_df["name"].tolist() if not staff_df.empty else []) + ["미지정"]
    sel_mgr = st.selectbox("👤 담당 직원 선택 (선택한 직원의 담당 거래처만 조회)", staff_filter_opts)

    summary_rows = []
    for _, c_row in customers_df.iterrows():
        cname = c_row["name"]
        mgr_name = str(c_row["manager_name"]) if pd.notna(c_row.get("manager_name")) and str(c_row.get("manager_name")).strip() else "미지정"

        # 선택한 담당 직원 필터 적용
        if sel_mgr != "전체 보기" and mgr_name != sel_mgr:
            continue

        c_logs = calc_df[calc_df["거래처명"] == cname] if not calc_df.empty else pd.DataFrame()
        if not c_logs.empty:
            latest = c_logs.iloc
            last_date, last_meter, est_remain = latest["방문일자"], latest["현재계량기"], latest["계산잔량kg"]
            valid_err = c_logs.dropna(subset=["검침오차kg"])
            last_error = valid_err.iloc["검침오차kg"] if not valid_err.empty else 0.0
        else:
            last_date, last_meter, est_remain, last_error = "-", 0.0, 0.0, 0.0

        status = "🚨 오차경고" if last_error <= err_limit else ("⚠️ 배달임박" if (est_remain > 0 and est_remain <= c_row["tank_kg"] * 0.6) else "✅ 정상")
        summary_rows.append({
            "상태": status,
            "담당직원": mgr_name,
            "거래처명": cname,
            "압력": c_row["pressure"],
            "구성": f"{c_row['tank_kg']}×{c_row['tank_count']}",
            "최근방문": last_date,
            "최신계량기": last_meter,
            "예상잔량(kg)": est_remain,
            "최근오차(kg)": last_error
        })

    sum_df = pd.DataFrame(summary_rows)
    if not sum_df.empty:
        m1, m2, m3 = st.columns(3)
        m1.metric("조회된 거래처", f"{len(sum_df)} 곳")
        m2.metric("⚠️ 배달임박", f"{len(sum_df[sum_df['상태'].str.contains('배달임박')])} 곳")
        m3.metric("🚨 오차경고", f"{len(sum_df[sum_df['상태'].str.contains('오차경고')])} 곳")
        st.dataframe(sum_df, use_container_width=True, hide_index=True)
    else:
        st.info(f"[{sel_mgr}] 담당으로 배정된 거래처가 아직 없습니다. 관리자 탭에서 거래처별 담당직원을 배정해 주세요.")
        st.divider()
        st.subheader("3️⃣ 거래처 등록 / 기존 거래처 불러와서 수정")
        cust_options = ["➕ 신규 거래처 직접 입력"] + (customers_df["name"].tolist() if not customers_df.empty else [])
        selected_load_cust = st.selectbox("대상 선택 (기존 거래처를 고르면 아래 칸에 자동 입력됩니다)", cust_options)

        mgr_choices = ["미지정"] + (staff_df["name"].tolist() if not staff_df.empty else [])

        if selected_load_cust != "➕ 신규 거래처 직접 입력":
            c_info = customers_df[customers_df["name"] == selected_load_cust].iloc
            def_name = str(c_info["name"])
            def_press_idx = 0 if c_info["pressure"] == "2.8kPa" else 1
            def_tkg_idx = 0 if int(c_info["tank_kg"]) == 20 else 1
            def_tcnt = int(c_info["tank_count"])
            def_cf = float(c_info["custom_factor"]) if pd.notna(c_info["custom_factor"]) else 0.0
            cur_mgr = str(c_info["manager_name"]) if pd.notna(c_info.get("manager_name")) else "미지정"
            def_mgr_idx = mgr_choices.index(cur_mgr) if cur_mgr in mgr_choices else 0

            c_logs = calc_df[calc_df["거래처명"] == selected_load_cust] if not calc_df.empty else pd.DataFrame()
            if not c_logs.empty:
                def_meter = float(c_logs.iloc["현재계량기"])
                def_remain = float(c_logs.iloc["계산잔량kg"])
            else:
                def_meter = 0.0
                def_remain = float(int(c_info["tank_kg"]) * int(c_info["tank_count"]))
        else:
            def_name, def_press_idx, def_tkg_idx, def_tcnt, def_cf, def_mgr_idx, def_meter, def_remain = "", 0, 1, 2, 0.0, 0, 0.0, 0.0

        with st.form("add_or_edit_cust"):
            r1_c1, r1_c2, r1_c3 = st.columns(3)
            cname = r1_c1.text_input("거래처명 (상호)", value=def_name)
            cmgr = r1_c2.selectbox("담당 직원 배정", mgr_choices, index=def_mgr_idx)
            cpress = r1_c3.selectbox("압력 설정", ["2.8kPa", "25kPa"], index=def_press_idx)

            r2_c1, r2_c2, r2_c3 = st.columns(3)
            ctkg = r2_c1.selectbox("용기 규격 (kg)", (20, 50), index=def_tkg_idx)
            ctcnt = r2_c2.number_input("설치 통수", min_value=1, max_value=50, value=def_tcnt)
            ccf = r2_c3.number_input("개별 보정계수 (0=공통적용)", min_value=0.0, step=0.01, value=def_cf, format="%.2f")

            st.markdown("---")
            save_init_log = st.checkbox("계량기 / 잔량 기준값 함께 저장 (신규 등록 또는 기준 재세팅 시 체크)", value=(selected_load_cust == "➕ 신규 거래처 직접 입력"))
            r3_c1, r3_c2, r3_c3 = st.columns(3)
            idate = r3_c1.date_input("기준 일자", value=date.today())
            imeter = r3_c2.number_input("기준 계량기 (루베)", min_value=0.0, step=0.1, value=def_meter, format="%.1f")
            iremain = r3_c3.number_input("기준 잔량 (kg)", min_value=0.0, step=1.0, value=def_remain, format="%.1f")

            if st.form_submit_button("💾 거래처 정보 저장 (등록 / 수정)", type="primary", use_container_width=True):
                clean_cname = cname.strip()
                if not clean_cname:
                    st.error("거래처명을 입력하세요.")
                else:
                    final_cf = ccf if ccf > 0 else None
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
                                        VALUES (:vd,:cn,'초기세팅',:mr,0,:ar,'관리자','기준값 세팅/수정',:ca)"""),
                                {"vd": idate.strftime("%Y-%m-%d"), "cn": clean_cname, "mr": imeter, "ar": iremain, "ca": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                            )
                    st.success(f"[{clean_cname}] 거래처 설정 및 담당직원({cmgr}) 배정이 저장되었습니다!")
                    st.rerun()
