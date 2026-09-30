import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Tax Square PDF to QuickBooks Converter",
    page_icon="📄",
    layout="wide"
)

st.title("PDF to QuickBooks Converter")
st.write("Convert bank and credit card PDF statements into QuickBooks-ready files.")

st.divider()

col1, col2 = st.columns(2)

with col1:
    bank = st.selectbox(
        "Bank",
        [
            "Select Bank",
            "TD Canada Trust",
            "RBC",
            "Scotiabank",
            "BMO",
            "CIBC",
            "Other"
        ]
    )

with col2:
    account_type = st.selectbox(
        "Account Type",
        [
            "Chequing",
            "Savings",
            "Credit Card"
        ]
    )

uploaded_file = st.file_uploader(
    "Upload PDF Bank Statement",
    type=["pdf"]
)

if uploaded_file is not None:

    st.success(f"Uploaded: {uploaded_file.name}")

    if st.button("Process Statement", type="primary"):

        st.session_state["processed"] = True

if st.session_state.get("processed"):

    st.subheader("Transaction Review")

    sample_data = {
        "Date": ["2026-09-01", "2026-09-03", "2026-09-05"],
        "Description": ["ROGERS", "CLIENT DEPOSIT", "COSTCO"],
        "Debit": [125.00, 0.00, 245.75],
        "Credit": [0.00, 2500.00, 0.00]
    }

    df = pd.DataFrame(sample_data)

    edited_df = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True
    )

    st.subheader("Statement Check")

    debit_total = edited_df["Debit"].sum()
    credit_total = edited_df["Credit"].sum()

    col1, col2, col3 = st.columns(3)

    col1.metric("Transactions", len(edited_df))
    col2.metric("Total Debits", f"${debit_total:,.2f}")
    col3.metric("Total Credits", f"${credit_total:,.2f}")

    st.divider()

    csv = edited_df.to_csv(index=False).encode("utf-8")

    st.download_button(
        "Download CSV",
        csv,
        "quickbooks_transactions.csv",
        "text/csv"
    )

st.divider()

st.caption("Tax Square Professional Corporation")
