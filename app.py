# app.py
import streamlit as st
import pandas as pd
import numpy as np
from supabase import create_client, Client
from datetime import datetime, date
import plotly.express as px
import io
import json

# ---------------------------- 页面配置 ----------------------------
st.set_page_config(page_title="NPI 生产进度与物料管理系统", layout="wide", initial_sidebar_state="expanded")

# ---------------------------- 自定义 CSS (Bento Grid 风格) ----------------------------
st.markdown("""
<style>
    .stApp { background-color: #f8fafc; }
    .main > div { border-radius: 24px; }
    [data-testid="stSidebar"] {
        background-color: #ffffff;
        border-radius: 0 24px 24px 0;
        box-shadow: 4px 0 12px rgba(0,0,0,0.05);
    }
    .stDataFrame, .stPlotlyChart, .stMarkdown, .stAlert, .stForm {
        background: white;
        border-radius: 20px;
        padding: 1rem;
        box-shadow: 0 8px 20px rgba(0,0,0,0.03), 0 2px 6px rgba(0,0,0,0.05);
        margin-bottom: 1rem;
        border: 1px solid #eef2f6;
    }
    .stButton button {
        border-radius: 40px;
        background-color: #3b82f6;
        color: white;
        font-weight: 500;
        transition: all 0.2s;
    }
    .stButton button:hover { background-color: #2563eb; transform: scale(1.02); }
    h1, h2, h3 { font-weight: 600; letter-spacing: -0.02em; }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #f1f5f9;
        border-radius: 60px;
        padding: 6px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 40px;
        padding: 6px 20px;
        background-color: transparent;
    }
    .stTabs [aria-selected="true"] {
        background-color: white;
        box-shadow: 0 2px 6px rgba(0,0,0,0.05);
    }
    .metric-card {
        background: white;
        border-radius: 24px;
        padding: 1rem 1.2rem;
        box-shadow: 0 8px 20px rgba(0,0,0,0.03);
        border: 1px solid #eef2f6;
        text-align: center;
    }
    .metric-card h3 { margin: 0; font-size: 2rem; font-weight: 700; color: #1e293b; }
    .metric-card p { margin: 0; color: #64748b; font-size: 0.9rem; }
</style>
""", unsafe_allow_html=True)

# ---------------------------- Supabase 初始化 ----------------------------
@st.cache_resource
def init_supabase():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = init_supabase()

# ---------------------------- 数据加载与处理 ----------------------------
@st.cache_data(ttl=300)
def load_jobs():
    try:
        response = supabase.table('jobs').select('*').order('need_by_date').execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"加载 jobs 失败: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_materials():
    try:
        response = supabase.table('materials').select('*').order('material_code').execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"加载 materials 失败: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_allocations():
    try:
        response = supabase.table('material_allocations').select('*, jobs(need_by_date)').execute()
        df = pd.DataFrame(response.data)
        if not df.empty and 'jobs' in df.columns:
            df['need_by_date'] = df['jobs'].apply(lambda x: x.get('need_by_date') if isinstance(x, dict) else None)
        return df
    except Exception as e:
        st.error(f"加载 allocations 失败: {e}")
        return pd.DataFrame()

def load_usage_log():
    try:
        response = supabase.table('material_usage_log').select('*').order('usage_date', desc=True).execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        return pd.DataFrame()

def import_excel_data(uploaded_file):
    """解析上传的 Excel 并导入 jobs 表"""
    df_raw = pd.read_excel(uploaded_file, sheet_name="JobStatusByCust", header=3)
    df_raw.columns = df_raw.columns.str.strip()
    col_map = {
        'Part Num': 'part_num', 'Revision': 'revision', 'Cust Part Num': 'cust_part_num',
        'Part Image': 'part_image', 'PONum-POLine': 'po_num_polines', 'Job Num': 'job_num',
        'Job Creation Date': 'job_creation_date', 'Customer Code': 'customer_code',
        'Order Date': 'order_date', 'Exwork Date': 'exwork_date', 'Reschedule': 'reschedule',
        'Need By Date': 'need_by_date', 'Prev Need By Date': 'prev_need_by_date',
        'Initial Need By': 'initial_need_by', 'Prod Commit Delivery Date': 'prod_commit_delivery_date',
        'Status': 'status', 'Order Type Category': 'order_type_category', 'Order Type': 'order_type',
        'Assign Engineer': 'assign_engineer', 'PO Qty': 'po_qty', 'Balance Qty': 'balance_qty'
    }
    existing_cols = {k: v for k, v in col_map.items() if k in df_raw.columns}
    df = df_raw[list(existing_cols.keys())].rename(columns=existing_cols)
    for col in ['part_num', 'revision', 'cust_part_num']:
        if col in df.columns:
            df[col] = df[col].ffill()
    df = df.dropna(subset=['job_num'])
    df = df[df['job_num'] != 'No Job']
    date_cols = ['job_creation_date', 'order_date', 'exwork_date', 'need_by_date',
                 'prev_need_by_date', 'initial_need_by', 'prod_commit_delivery_date']
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors='coerce').dt.date
            df[col] = df[col].apply(lambda x: x.isoformat() if pd.notnull(x) else None)
    numeric_cols = ['po_qty', 'balance_qty']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    existing_jobs = load_jobs()
    if not existing_jobs.empty:
        status_dict = dict(zip(existing_jobs['job_num'], existing_jobs['production_status']))
        df['production_status'] = df['job_num'].map(status_dict).fillna('Not Started')
    else:
        df['production_status'] = 'Not Started'
    for _, row in df.iterrows():
        data = row.to_dict()
        data = {k: (None if pd.isna(v) else v) for k, v in data.items()}
        for key, value in data.items():
            if isinstance(value, (pd.Timestamp, date, datetime)):
                data[key] = value.isoformat()
            elif isinstance(value, np.generic):
                data[key] = value.item()
        supabase.table('jobs').upsert(data, on_conflict='job_num').execute()
    st.success("Excel 数据导入/更新成功！")
    st.rerun()

def update_job_status(job_num, new_status):
    supabase.table('jobs').update({'production_status': new_status, 'last_updated': datetime.now().isoformat()}).eq('job_num', job_num).execute()

def add_material(material_code, total_qty, safety_stock=0, unit='pcs'):
    existing = supabase.table('materials').select('material_code').eq('material_code', material_code).execute()
    if len(existing.data) > 0:
        st.warning("物料代码已存在，请使用更新功能")
        return False
    data = {
        'material_code': material_code, 'total_quantity': total_qty, 'used_quantity': 0,
        'remaining_quantity': total_qty, 'safety_stock': safety_stock, 'unit': unit
    }
    supabase.table('materials').insert(data).execute()
    return True

def update_material_qty(material_code, additional_qty):
    mat = supabase.table('materials').select('total_quantity', 'used_quantity').eq('material_code', material_code).execute()
    if not mat.data:
        return False
    current_total = mat.data[0]['total_quantity']
    new_total = current_total + additional_qty
    if new_total < 0:
        st.error("库存不能为负数")
        return False
    remaining = new_total - mat.data[0]['used_quantity']
    supabase.table('materials').update({
        'total_quantity': new_total, 'remaining_quantity': remaining, 'last_updated': datetime.now().isoformat()
    }).eq('material_code', material_code).execute()
    return True

def allocate_material_to_job(material_code, job_num, allocated_qty):
    mat = supabase.table('materials').select('remaining_quantity').eq('material_code', material_code).execute()
    if not mat.data or mat.data[0]['remaining_quantity'] < allocated_qty:
        st.error(f"物料 {material_code} 剩余库存不足，无法分配 {allocated_qty}")
        return False
    exist = supabase.table('material_allocations').select('id').eq('material_code', material_code).eq('job_num', job_num).execute()
    if len(exist.data) > 0:
        alloc = supabase.table('material_allocations').select('allocated_qty', 'remaining_qty').eq('material_code', material_code).eq('job_num', job_num).execute()
        new_alloc = alloc.data[0]['allocated_qty'] + allocated_qty
        new_remain = alloc.data[0]['remaining_qty'] + allocated_qty
        supabase.table('material_allocations').update({'allocated_qty': new_alloc, 'remaining_qty': new_remain}).eq('material_code', material_code).eq('job_num', job_num).execute()
    else:
        job = supabase.table('jobs').select('need_by_date').eq('job_num', job_num).execute()
        need_date = job.data[0]['need_by_date'] if job.data else None
        supabase.table('material_allocations').insert({
            'material_code': material_code, 'job_num': job_num, 'allocated_qty': allocated_qty,
            'used_qty': 0, 'remaining_qty': allocated_qty, 'need_by_date': need_date
        }).execute()
    new_remain_mat = mat.data[0]['remaining_quantity'] - allocated_qty
    supabase.table('materials').update({'remaining_quantity': new_remain_mat}).eq('material_code', material_code).execute()
    return True

def consume_material(material_code, job_num, quantity_used, usage_date, remarks=""):
    alloc = supabase.table('material_allocations').select('id', 'remaining_qty', 'used_qty').eq('material_code', material_code).eq('job_num', job_num).execute()
    if not alloc.data or alloc.data[0]['remaining_qty'] < quantity_used:
        st.error(f"物料 {material_code} 针对 Job {job_num} 的剩余分配量不足")
        return False
    alloc_id = alloc.data[0]['id']
    new_used = alloc.data[0]['used_qty'] + quantity_used
    new_remain = alloc.data[0]['remaining_qty'] - quantity_used
    supabase.table('material_allocations').update({'used_qty': new_used, 'remaining_qty': new_remain}).eq('id', alloc_id).execute()
    mat = supabase.table('materials').select('used_quantity', 'total_quantity').eq('material_code', material_code).execute()
    new_total_used = mat.data[0]['used_quantity'] + quantity_used
    new_remaining_mat = mat.data[0]['total_quantity'] - new_total_used
    supabase.table('materials').update({'used_quantity': new_total_used, 'remaining_quantity': new_remaining_mat}).eq('material_code', material_code).execute()
    supabase.table('material_usage_log').insert({
        'material_code': material_code, 'job_num': job_num, 'quantity_used': quantity_used,
        'usage_date': usage_date.isoformat() if isinstance(usage_date, (date, datetime)) else usage_date,
        'remarks': remarks
    }).execute()
    return True

# ---------------------------- 主 UI ----------------------------
def main():
    st.title("📦 NPI 生产进度 & 物料协同系统")
    st.caption("Bento 风格 · 实时协作 · 支持 Sales / Production / Purchaser")

    role = st.sidebar.selectbox("👤 您的角色", ["Sales (查看进度)", "Production (更新生产状态)", "Purchaser (物料管理)", "Admin (全部权限)"])
    st.sidebar.markdown("---")
    if role == "Admin (全部权限)":
        with st.sidebar.expander("📤 导入 Excel 数据 (初始化/同步)"):
            uploaded_file = st.file_uploader("上传 JobStatus-test.xlsx", type=["xlsx"])
            if uploaded_file:
                if st.button("开始导入/更新"):
                    import_excel_data(uploaded_file)
    if st.sidebar.button("🔄 刷新数据"):
        st.cache_data.clear()
        st.rerun()

    df_jobs = load_jobs()
    df_materials = load_materials()
    df_alloc = load_allocations()
    df_usage = load_usage_log()

    if not df_jobs.empty:
        total_jobs = len(df_jobs)
        completed = df_jobs['production_status'].eq('Completed').sum()
        pending = total_jobs - completed
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f'<div class="metric-card"><h3>{total_jobs}</h3><p>总 NPI 项目</p></div>', unsafe_allow_html=True)
        with col2:
            st.markdown(f'<div class="metric-card"><h3>{completed}</h3><p>已完成</p></div>', unsafe_allow_html=True)
        with col3:
            st.markdown(f'<div class="metric-card"><h3>{pending}</h3><p>进行中</p></div>', unsafe_allow_html=True)
    st.markdown("---")

    st.header("📋 NPI 项目进度看板")
    if df_jobs.empty:
        st.info("暂无 Job 数据，请使用 Admin 角色导入 Excel 文件。")
    else:
        if role == "Production (更新生产状态)":
            df_display = df_jobs[df_jobs['production_status'] != 'Completed'].copy()
            st.subheader(f"🔧 未完成生产任务 ({len(df_display)} 项)")
        else:
            df_display = df_jobs.copy()
        def status_color(s):
            return 'background-color: #9CCC65' if s == 'Completed' else 'background-color: #FFCC80'
        styled = df_display[['job_num', 'part_num', 'cust_part_num', 'need_by_date', 'assign_engineer', 'production_status', 'status']].rename(columns={
            'job_num': 'Job编号', 'part_num': '部件号', 'cust_part_num': '客户部件号', 'need_by_date': '需求日期',
            'assign_engineer': '工程师', 'production_status': '生产状态', 'status': '订单状态'
        })
        # 修复：applymap -> map
        st.dataframe(styled.style.map(status_color, subset=['生产状态']), use_container_width=True)

        if role in ["Production (更新生产状态)", "Admin (全部权限)"]:
            st.subheader("✅ 生产完成确认")
            incomplete_jobs = df_jobs[df_jobs['production_status'] != 'Completed']['job_num'].tolist()
            if incomplete_jobs:
                selected_job = st.selectbox("选择已完成的 Job 编号", incomplete_jobs)
                if st.button("标记为已完成", key="complete_job"):
                    update_job_status(selected_job, "Completed")
                    st.success(f"Job {selected_job} 已完成！")
                    st.rerun()
            else:
                st.success("🎉 所有 Job 都已完成！")
        if role == "Sales (查看进度)":
            progress = df_jobs['production_status'].value_counts()
            fig = px.pie(values=progress.values, names=progress.index, title="整体生产完成进度")
            st.plotly_chart(fig, use_container_width=True)

    st.header("🧾 物料管理看板 (Purchaser & Production)")
    tab1, tab2, tab3, tab4 = st.tabs(["📦 物料库存", "📌 物料分配至 Job", "⚙️ 生产领料", "📜 使用记录"])

    with tab1:
        st.subheader("当前物料库存")
        if not df_materials.empty:
            def color_stock(row):
                if row['remaining_quantity'] < row['safety_stock']:
                    return ['background-color: #FFCDD2'] * len(row)
                return [''] * len(row)
            styled_mat = df_materials[['material_code', 'total_quantity', 'used_quantity', 'remaining_quantity', 'safety_stock', 'unit']].rename(columns={
                'material_code': '物料代码', 'total_quantity': '总采购', 'used_quantity': '已用', 'remaining_quantity': '剩余', 'safety_stock': '安全库存', 'unit': '单位'
            })
            # 修复：applymap -> map (这里使用 apply 逐行染色，无需改动)
            st.dataframe(styled_mat.style.apply(color_stock, axis=1), use_container_width=True)
        else:
            st.info("暂无物料数据，请添加新物料。")
        st.subheader("➕ 新增物料 / 调整库存")
        with st.form("add_material_form"):
            mat_code = st.text_input("物料代码 (唯一)", key="mat_code")
            mat_qty = st.number_input("当前总数量", min_value=0.0, step=1.0)
            safety = st.number_input("安全库存阈值", min_value=0.0, step=1.0, value=0.0)
            unit = st.text_input("单位", value="pcs")
            submitted = st.form_submit_button("添加物料")
            if submitted and mat_code:
                if add_material(mat_code, mat_qty, safety, unit):
                    st.success(f"物料 {mat_code} 添加成功")
                    st.rerun()
        with st.form("update_stock_form"):
            mat_list = df_materials['material_code'].tolist() if not df_materials.empty else []
            sel_mat = st.selectbox("选择现有物料", mat_list) if mat_list else st.text_input("物料代码")
            adjust_qty = st.number_input("调整数量 (正数为增加，负数为减少)", step=1.0)
            upd_submit = st.form_submit_button("调整库存")
            if upd_submit and sel_mat:
                if update_material_qty(sel_mat, adjust_qty):
                    st.success(f"物料 {sel_mat} 库存已调整")
                    st.rerun()

    with tab2:
        st.subheader("分配物料到具体 NPI Job (让物料覆盖到 Job)")
        if df_jobs.empty or df_materials.empty:
            st.warning("请确保已导入 Job 数据且已添加物料")
        else:
            col1, col2 = st.columns(2)
            with col1:
                mat_code_alloc = st.selectbox("选择物料", df_materials['material_code'].tolist(), key="alloc_mat")
            with col2:
                job_alloc = st.selectbox("选择 Job 编号", df_jobs['job_num'].tolist(), key="alloc_job")
            alloc_qty = st.number_input("分配数量", min_value=0.01, step=1.0)
            if st.button("执行分配"):
                if allocate_material_to_job(mat_code_alloc, job_alloc, alloc_qty):
                    st.success(f"已将 {alloc_qty} 个 {mat_code_alloc} 分配给 Job {job_alloc}")
                    st.rerun()
        st.subheader("现有物料分配情况 (覆盖关系)")
        if not df_alloc.empty:
            df_alloc_display = df_alloc[['material_code', 'job_num', 'allocated_qty', 'used_qty', 'remaining_qty', 'need_by_date']].rename(columns={
                'material_code': '物料代码', 'job_num': 'Job编号', 'allocated_qty': '分配总量', 'used_qty': '已使用', 'remaining_qty': '剩余可领', 'need_by_date': '需求日期'
            })
            st.dataframe(df_alloc_display, use_container_width=True)
        else:
            st.info("暂无分配记录，物料尚未覆盖任何 Job。")

    with tab3:
        st.subheader("生产领料 (消耗物料)")
        if not df_alloc.empty:
            available = df_alloc[df_alloc['remaining_qty'] > 0][['material_code', 'job_num', 'remaining_qty']]
            if available.empty:
                st.info("没有可领料的分配记录，请先分配物料到 Job")
            else:
                selected = st.selectbox("选择物料-Job 组合", available.apply(lambda x: f"{x['material_code']} -> Job {x['job_num']} (剩余 {x['remaining_qty']})", axis=1).tolist())
                mat_code_use = selected.split(" -> ")[0]
                job_num_use = selected.split("Job ")[1].split(" (剩余")[0]
                qty_use = st.number_input("领料数量", min_value=0.01, step=1.0, max_value=float(available[available['material_code']==mat_code_use]['remaining_qty'].values[0]))
                use_date = st.date_input("使用日期", datetime.now().date())
                remarks = st.text_input("备注")
                if st.button("确认领料"):
                    if consume_material(mat_code_use, job_num_use, qty_use, use_date, remarks):
                        st.success(f"已领用 {qty_use} 个 {mat_code_use} 用于 Job {job_num_use}")
                        st.rerun()
        else:
            st.info("请先在【物料分配至Job】中创建分配记录")

    with tab4:
        st.subheader("物料使用历史记录")
        if not df_usage.empty:
            st.dataframe(df_usage[['material_code', 'job_num', 'quantity_used', 'usage_date', 'remarks']].rename(columns={
                'material_code': '物料代码', 'job_num': 'Job编号', 'quantity_used': '用量', 'usage_date': '领用日期', 'remarks': '备注'
            }), use_container_width=True)
        else:
            st.info("暂无领料记录")

    st.sidebar.markdown("### ⚠️ 物料预警")
    if not df_materials.empty:
        low_stock = df_materials[df_materials['remaining_quantity'] < df_materials['safety_stock']]
        if not low_stock.empty:
            st.sidebar.error(f"🔴 {len(low_stock)} 种物料低于安全库存")
            for _, row in low_stock.iterrows():
                st.sidebar.write(f"- {row['material_code']} 剩余 {row['remaining_quantity']} < 安全库存 {row['safety_stock']}")
        else:
            st.sidebar.success("所有物料库存充足")
    else:
        st.sidebar.info("暂无物料数据")

if __name__ == "__main__":
    main()
