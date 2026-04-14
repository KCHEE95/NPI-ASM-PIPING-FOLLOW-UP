# app.py
import streamlit as st
import pandas as pd
import numpy as np
from supabase import create_client, Client
from datetime import datetime, date
import plotly.express as px
import io
import json

# ---------------------------- Page config ----------------------------
st.set_page_config(page_title="NPI Production & Material System", layout="wide", initial_sidebar_state="expanded")

# ---------------------------- Custom CSS (Bento Grid style) ----------------------------
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

# ---------------------------- Supabase initialization ----------------------------
@st.cache_resource
def init_supabase():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase = init_supabase()

# ---------------------------- Data loading functions ----------------------------
@st.cache_data(ttl=300)
def load_jobs():
    try:
        response = supabase.table('jobs').select('*').order('need_by_date').execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Failed to load jobs: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_materials():
    try:
        response = supabase.table('materials').select('*').order('material_code').execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        st.error(f"Failed to load materials: {e}")
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
        st.error(f"Failed to load allocations: {e}")
        return pd.DataFrame()

def load_usage_log():
    try:
        response = supabase.table('material_usage_log').select('*').order('usage_date', desc=True).execute()
        return pd.DataFrame(response.data)
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_part_images():
    """Return dict {part_num: image_url}"""
    try:
        response = supabase.table('part_images').select('part_num, image_url').execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            return dict(zip(df['part_num'], df['image_url']))
        return {}
    except Exception as e:
        st.error(f"Failed to load part images: {e}")
        return {}

def import_excel_data(uploaded_file):
    """Parse uploaded Excel and import into jobs table"""
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
    st.success("Excel data imported/updated successfully!")
    st.rerun()

def update_job_status(job_num, new_status):
    supabase.table('jobs').update({'production_status': new_status, 'last_updated': datetime.now().isoformat()}).eq('job_num', job_num).execute()

def add_material(material_code, total_qty, safety_stock=0, unit='pcs'):
    existing = supabase.table('materials').select('material_code').eq('material_code', material_code).execute()
    if len(existing.data) > 0:
        st.warning("Material code already exists. Use update instead.")
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
        st.error("Stock cannot be negative")
        return False
    remaining = new_total - mat.data[0]['used_quantity']
    supabase.table('materials').update({
        'total_quantity': new_total, 'remaining_quantity': remaining, 'last_updated': datetime.now().isoformat()
    }).eq('material_code', material_code).execute()
    return True

def allocate_material_to_job(material_code, job_num, allocated_qty):
    mat = supabase.table('materials').select('remaining_quantity').eq('material_code', material_code).execute()
    if not mat.data or mat.data[0]['remaining_quantity'] < allocated_qty:
        st.error(f"Insufficient remaining stock for material {material_code} to allocate {allocated_qty}")
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
        st.error(f"Insufficient allocated material {material_code} for Job {job_num}")
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

def upload_part_image(part_num, image_file):
    """Upload image to Supabase Storage and save URL to part_images table"""
    if not image_file:
        return False
    # Generate unique file name
    ext = image_file.name.split('.')[-1]
    file_path = f"{part_num}_{datetime.now().timestamp()}.{ext}"
    # Upload to bucket 'part-images'
    try:
        res = supabase.storage.from_("part-images").upload(file_path, image_file.getvalue())
        if res:
            # Get public URL
            public_url = supabase.storage.from_("part-images").get_public_url(file_path)
            # Upsert into part_images table
            supabase.table('part_images').upsert({
                'part_num': part_num,
                'image_url': public_url,
                'updated_at': datetime.now().isoformat()
            }).execute()
            return True
    except Exception as e:
        st.error(f"Upload failed: {e}")
        return False
    return False

# ---------------------------- Main UI ----------------------------
def main():
    st.title("📦 NPI Production & Material Tracking System")
    st.caption("Bento style · Real-time collaboration · Sales / Production / Purchaser")

    role = st.sidebar.selectbox("👤 Your Role", ["Sales (View Progress)", "Production (Update Status)", "Purchaser (Material Management)", "Admin (Full Access)"])
    st.sidebar.markdown("---")

    # Admin functions
    if role == "Admin (Full Access)":
        with st.sidebar.expander("📤 Import Excel Data (Initial/Sync)"):
            uploaded_file = st.file_uploader("Upload JobStatus-test.xlsx", type=["xlsx"])
            if uploaded_file and st.button("Start Import/Update"):
                import_excel_data(uploaded_file)
        with st.sidebar.expander("🖼️ Upload Part Images (Admin)"):
            # Get unique part numbers from jobs
            df_jobs_temp = load_jobs()
            if not df_jobs_temp.empty:
                part_nums = sorted(df_jobs_temp['part_num'].dropna().unique())
                selected_part = st.selectbox("Select Part Number", part_nums)
                uploaded_img = st.file_uploader("Choose image", type=["jpg", "jpeg", "png", "gif"])
                if uploaded_img and st.button("Upload Image"):
                    if upload_part_image(selected_part, uploaded_img):
                        st.success(f"Image for {selected_part} uploaded successfully!")
                        st.cache_data.clear()
                        st.rerun()
            else:
                st.info("No part numbers found. Please import Excel first.")
    if st.sidebar.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()

    # Load all data
    df_jobs = load_jobs()
    df_materials = load_materials()
    df_alloc = load_allocations()
    df_usage = load_usage_log()
    part_images_dict = load_part_images()

    # KPI cards
    if not df_jobs.empty:
        total_jobs = len(df_jobs)
        completed = df_jobs['production_status'].eq('Completed').sum()
        pending = total_jobs - completed
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f'<div class="metric-card"><h3>{total_jobs}</h3><p>Total NPI Jobs</p></div>', unsafe_allow_html=True)
        with col2:
            st.markdown(f'<div class="metric-card"><h3>{completed}</h3><p>Completed</p></div>', unsafe_allow_html=True)
        with col3:
            st.markdown(f'<div class="metric-card"><h3>{pending}</h3><p>In Progress</p></div>', unsafe_allow_html=True)
    st.markdown("---")

    # ========================= Job Progress Dashboard =========================
    st.header("📋 NPI Job Progress Dashboard")
    if df_jobs.empty:
        st.info("No job data available. Use Admin role to import Excel file.")
    else:
        if role == "Production (Update Status)":
            df_display = df_jobs[df_jobs['production_status'] != 'Completed'].copy()
            st.subheader(f"🔧 Pending Production Tasks ({len(df_display)} items)")
        else:
            df_display = df_jobs.copy()

        # Prepare display dataframe with image column
        df_display['image_url'] = df_display['part_num'].map(part_images_dict).fillna("")
        # Select columns: Job Num, Part Num, Customer Part Num, Exwork Date, PO Qty, Need By Date, Status, Production Status, Image
        display_cols = ['job_num', 'part_num', 'cust_part_num', 'exwork_date', 'po_qty', 'need_by_date', 'status', 'production_status', 'image_url']
        # Ensure columns exist
        for col in display_cols:
            if col not in df_display.columns:
                df_display[col] = ""
        df_display = df_display[display_cols].rename(columns={
            'job_num': 'Job Number', 'part_num': 'Part Number', 'cust_part_num': 'Customer Part Number',
            'exwork_date': 'Exwork Date', 'po_qty': 'PO Qty', 'need_by_date': 'Need By Date',
            'status': 'Order Status', 'production_status': 'Production Status', 'image_url': 'Image'
        })

        # Color mapping for production status
        def status_color(val):
            if val == 'Completed':
                return 'background-color: #9CCC65'
            else:
                return 'background-color: #FFCC80'

        # Apply styling to the 'Production Status' column only
        styled_df = df_display.style.map(status_color, subset=['Production Status'])

        # Use column_config to display images
        column_config = {
            "Image": st.column_config.ImageColumn("Part Image", help="Part photo", width="small"),
            "Job Number": st.column_config.TextColumn("Job Number"),
            "Part Number": st.column_config.TextColumn("Part Number"),
            "Customer Part Number": st.column_config.TextColumn("Customer Part Number"),
            "Exwork Date": st.column_config.DateColumn("Exwork Date"),
            "PO Qty": st.column_config.NumberColumn("PO Qty"),
            "Need By Date": st.column_config.DateColumn("Need By Date"),
            "Order Status": st.column_config.TextColumn("Order Status"),
            "Production Status": st.column_config.TextColumn("Production Status"),
        }

        st.dataframe(styled_df, column_config=column_config, use_container_width=True, height=400)

        # Production completion section
        if role in ["Production (Update Status)", "Admin (Full Access)"]:
            st.subheader("✅ Mark Job as Completed")
            incomplete_jobs = df_jobs[df_jobs['production_status'] != 'Completed']['job_num'].tolist()
            if incomplete_jobs:
                selected_job = st.selectbox("Select completed Job Number", incomplete_jobs)
                if st.button("Mark as Completed", key="complete_job"):
                    update_job_status(selected_job, "Completed")
                    st.success(f"Job {selected_job} marked as completed!")
                    st.rerun()
            else:
                st.success("🎉 All jobs are completed!")

        if role == "Sales (View Progress)":
            progress = df_jobs['production_status'].value_counts()
            fig = px.pie(values=progress.values, names=progress.index, title="Overall Production Progress")
            st.plotly_chart(fig, use_container_width=True)

    # ========================= Material Management Board =========================
    st.header("🧾 Material Management Board (Purchaser & Production)")
    tab1, tab2, tab3, tab4 = st.tabs(["📦 Material Stock", "📌 Allocate Material to Job", "⚙️ Production Pick", "📜 Usage Log"])

    with tab1:
        st.subheader("Current Material Stock")
        if not df_materials.empty:
            def color_stock(row):
                if row['remaining_quantity'] < row['safety_stock']:
                    return ['background-color: #FFCDD2'] * len(row)
                return [''] * len(row)
            styled_mat = df_materials[['material_code', 'total_quantity', 'used_quantity', 'remaining_quantity', 'safety_stock', 'unit']].rename(columns={
                'material_code': 'Material Code', 'total_quantity': 'Total Qty', 'used_quantity': 'Used', 'remaining_quantity': 'Remaining', 'safety_stock': 'Safety Stock', 'unit': 'Unit'
            })
            st.dataframe(styled_mat.style.apply(color_stock, axis=1), use_container_width=True)
        else:
            st.info("No material data. Please add new materials.")
        st.subheader("➕ Add New Material / Adjust Stock")
        with st.form("add_material_form"):
            mat_code = st.text_input("Material Code (unique)", key="mat_code")
            mat_qty = st.number_input("Current total quantity", min_value=0.0, step=1.0)
            safety = st.number_input("Safety stock threshold", min_value=0.0, step=1.0, value=0.0)
            unit = st.text_input("Unit", value="pcs")
            submitted = st.form_submit_button("Add Material")
            if submitted and mat_code:
                if add_material(mat_code, mat_qty, safety, unit):
                    st.success(f"Material {mat_code} added successfully")
                    st.rerun()
        with st.form("update_stock_form"):
            mat_list = df_materials['material_code'].tolist() if not df_materials.empty else []
            sel_mat = st.selectbox("Select existing material", mat_list) if mat_list else st.text_input("Material Code")
            adjust_qty = st.number_input("Adjust quantity (positive to add, negative to deduct)", step=1.0)
            upd_submit = st.form_submit_button("Adjust Stock")
            if upd_submit and sel_mat:
                if update_material_qty(sel_mat, adjust_qty):
                    st.success(f"Material {sel_mat} stock adjusted")
                    st.rerun()

    with tab2:
        st.subheader("Allocate Material to NPI Job")
        if df_jobs.empty or df_materials.empty:
            st.warning("Please ensure jobs and materials are loaded.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                mat_code_alloc = st.selectbox("Select Material", df_materials['material_code'].tolist(), key="alloc_mat")
            with col2:
                job_alloc = st.selectbox("Select Job Number", df_jobs['job_num'].tolist(), key="alloc_job")
            alloc_qty = st.number_input("Allocation Quantity", min_value=0.01, step=1.0)
            if st.button("Execute Allocation"):
                if allocate_material_to_job(mat_code_alloc, job_alloc, alloc_qty):
                    st.success(f"Allocated {alloc_qty} of {mat_code_alloc} to Job {job_alloc}")
                    st.rerun()
        st.subheader("Current Material Allocations")
        if not df_alloc.empty:
            df_alloc_display = df_alloc[['material_code', 'job_num', 'allocated_qty', 'used_qty', 'remaining_qty', 'need_by_date']].rename(columns={
                'material_code': 'Material Code', 'job_num': 'Job Number', 'allocated_qty': 'Allocated', 'used_qty': 'Used', 'remaining_qty': 'Remaining', 'need_by_date': 'Need By Date'
            })
            st.dataframe(df_alloc_display, use_container_width=True)
        else:
            st.info("No allocations yet.")

    with tab3:
        st.subheader("Production Pick (Consume Material)")
        if not df_alloc.empty:
            available = df_alloc[df_alloc['remaining_qty'] > 0][['material_code', 'job_num', 'remaining_qty']]
            if available.empty:
                st.info("No allocatable materials left.")
            else:
                selected = st.selectbox("Select Material-Job combo", available.apply(lambda x: f"{x['material_code']} -> Job {x['job_num']} (Remaining {x['remaining_qty']})", axis=1).tolist())
                mat_code_use = selected.split(" -> ")[0]
                job_num_use = selected.split("Job ")[1].split(" (Remaining")[0]
                qty_use = st.number_input("Pick quantity", min_value=0.01, step=1.0, max_value=float(available[available['material_code']==mat_code_use]['remaining_qty'].values[0]))
                use_date = st.date_input("Usage date", datetime.now().date())
                remarks = st.text_input("Remarks")
                if st.button("Confirm Pick"):
                    if consume_material(mat_code_use, job_num_use, qty_use, use_date, remarks):
                        st.success(f"Consumed {qty_use} of {mat_code_use} for Job {job_num_use}")
                        st.rerun()
        else:
            st.info("Please create material allocations first.")

    with tab4:
        st.subheader("Material Usage History")
        if not df_usage.empty:
            st.dataframe(df_usage[['material_code', 'job_num', 'quantity_used', 'usage_date', 'remarks']].rename(columns={
                'material_code': 'Material Code', 'job_num': 'Job Number', 'quantity_used': 'Qty Used', 'usage_date': 'Usage Date', 'remarks': 'Remarks'
            }), use_container_width=True)
        else:
            st.info("No usage records yet.")

    st.sidebar.markdown("### ⚠️ Material Alert")
    if not df_materials.empty:
        low_stock = df_materials[df_materials['remaining_quantity'] < df_materials['safety_stock']]
        if not low_stock.empty:
            st.sidebar.error(f"🔴 {len(low_stock)} material(s) below safety stock")
            for _, row in low_stock.iterrows():
                st.sidebar.write(f"- {row['material_code']}: Remaining {row['remaining_quantity']} < Safety {row['safety_stock']}")
        else:
            st.sidebar.success("All materials are sufficiently stocked")
    else:
        st.sidebar.info("No material data")

if __name__ == "__main__":
    main()
