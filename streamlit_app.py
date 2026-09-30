import streamlit as st
import pandas as pd
import fitz
import re
from datetime import datetime

st.set_page_config(
    page_title="Tax Square PDF to QuickBooks Converter",
    page_icon="📄",
    layout="wide"
)

st.title("PDF to QuickBooks Converter")
st.write("Convert TD bank PDF statements into QuickBooks-ready files.")

st.divider()


def money_to_float(value):
    return float(value.replace(",", ""))


def extract_td_statement(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    text = ""
    for page in doc:
        text += page.get_text() + "\n"

    # Statement year
    year_match = re.search(
        r'APR\s+\d{1,2}/(\d{2})\s*-\s*MAY\s+\d{1,2}/(\d{2})',
        text,
        re.IGNORECASE
    )

    if year_match:
        statement_year = 2000 + int(year_match.group(2))
    else:
        statement_year = datetime.now().year

    # TD statement control totals
    credit_summary = re.search(
        r'Credits\s+(\d+)\s+([\d,]+\.\d{2})',
        text,
        re.IGNORECASE
    )

    debit_summary = re.search(
        r'Debits\s+(\d+)\s+([\d,]+\.\d{2})',
        text,
        re.IGNORECASE
    )

    expected_credit_count = (
        int(credit_summary.group(1)) if credit_summary else None
    )

    expected_credit_total = (
        money_to_float(credit_summary.group(2))
        if credit_summary else None
    )

    expected_debit_count = (
        int(debit_summary.group(1)) if debit_summary else None
    )

    expected_debit_total = (
        money_to_float(debit_summary.group(2))
        if debit_summary else None
    )

    transactions = []

    # Rules for this TD Business Chequing format.
    # True = debit. False = credit.
    debit_prefixes = (
        "TFR-TO",
        "TD BUS CREDIT INS",
        "TD VISA",
        "MONTHLY PLAN FEE",
        "BUS LINE FEE",
        "OVERDRAFT INTEREST"
    )

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    transaction_pattern = re.compile(
        r'^(.*?)\s+([\d,]+\.\d{2})\s+'
        r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)'
        r'(\d{2})(?:\s+[\d,]+\.\d{2}OD?)?$',
        re.IGNORECASE
    )

    for line in lines:

        if line.upper().startswith("BALANCE FORWARD"):
            continue

        match = transaction_pattern.match(line)

        if not match:
            continue

        description = match.group(1).strip()
        amount = money_to_float(match.group(2))
        month = match.group(3).upper()
        day = int(match.group(4))

        # Exclude statement summary lines
        if description.upper() in ("CREDITS", "DEBITS"):
            continue

        date_string = f"{month} {day:02d} {statement_year}"
        transaction_date = datetime.strptime(
            date_string,
            "%b %d %Y"
        ).strftime("%Y-%m-%d")

        description_upper = description.upper()

        # TD E-TRANSFER entries in this statement:
        # SEND E-TFR = credit
        # ordinary E-TRANSFER = debit
        if description_upper.startswith("SEND E-TFR"):
            is_debit = False

        elif description_upper.startswith("E-TRANSFER"):
            is_debit = True

        elif any(
            prefix in description_upper
            for prefix in debit_prefixes
        ):
            is_debit = True

        else:
            # TFR-TO entries in this TD format are debit
            if "TFR-TO" in description_upper:
                is_debit = True
            else:
                # Unknown transactions remain unclassified
                is_debit = None

        if is_debit is True:
            debit = amount
            credit = 0.00

        elif is_debit is False:
            debit = 0.00
            credit = amount

        else:
            debit = 0.00
            credit = 0.00

        transactions.append({
            "Date": transaction_date,
            "Description": description,
            "Debit": debit,
            "Credit": credit,
            "Original Amount": amount
        })

    df = pd.DataFrame(transactions)

    return {
        "transactions": df,
        "expected_debit_count": expected_debit_count,
        "expected_debit_total": expected_debit_total,
        "expected_credit_count": expected_credit_count,
        "expected_credit_total": expected_credit_total
    }


col1, col2 = st.columns(2)

with col1:
    bank = st.selectbox(
        "Bank",
        [
            "Select Bank",
            "TD Canada Trust"
        ]
    )

with col2:
    account_type = st.selectbox(
        "Account Type",
        [
            "Business Chequing"
        ]
    )


uploaded_file = st.file_uploader(
    "Upload TD PDF Bank Statement",
    type=["pdf"]
)


if uploaded_file is not None:

    st.success(f"Uploaded: {uploaded_file.name}")

    if bank != "TD Canada Trust":
        st.warning("Please select TD Canada Trust.")

    elif st.button("Process Statement", type="primary"):

        try:

            result = extract_td_statement(
                uploaded_file.getvalue()
            )

            st.session_state["td_result"] = result

        except Exception as e:

            st.error(
                "The statement could not be processed."
            )

            st.exception(e)


if "td_result" in st.session_state:

    result = st.session_state["td_result"]
    df = result["transactions"]

    st.divider()
    st.subheader("Transaction Review")

    if df.empty:

        st.error(
            "No transactions were detected. "
            "The TD statement format may be different."
        )

    else:

        edited_df = st.data_editor(
            df[[
                "Date",
                "Description",
                "Debit",
                "Credit"
            ]],
            num_rows="dynamic",
            use_container_width=True
        )

        debit_total = round(
            edited_df["Debit"].sum(), 2
        )

        credit_total = round(
            edited_df["Credit"].sum(), 2
        )

        debit_count = int(
            (edited_df["Debit"] > 0).sum()
        )

        credit_count = int(
            (edited_df["Credit"] > 0).sum()
        )

        st.subheader("Statement Control")

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Transactions Extracted",
            len(edited_df)
        )

        col2.metric(
            "Total Debits",
            f"${debit_total:,.2f}"
        )

        col3.metric(
            "Total Credits",
            f"${credit_total:,.2f}"
        )

        expected_debit_count = result[
            "expected_debit_count"
        ]

        expected_debit_total = result[
            "expected_debit_total"
        ]

        expected_credit_count = result[
            "expected_credit_count"
        ]

        expected_credit_total = result[
            "expected_credit_total"
        ]

        if (
            expected_debit_count is not None
            and expected_credit_count is not None
        ):

            debit_match = (
                debit_count == expected_debit_count
                and abs(
                    debit_total - expected_debit_total
                ) < 0.01
            )

            credit_match = (
                credit_count == expected_credit_count
                and abs(
                    credit_total - expected_credit_total
                ) < 0.01
            )

            st.write(
                f"TD Statement Debits: "
                f"{expected_debit_count} transactions, "
                f"${expected_debit_total:,.2f}"
            )

            st.write(
                f"TD Statement Credits: "
                f"{expected_credit_count} transactions, "
                f"${expected_credit_total:,.2f}"
            )

            if debit_match and credit_match:

                st.success(
                    "✓ STATEMENT RECONCILED"
                )

            else:

                st.error(
                    "⚠ STATEMENT DOES NOT RECONCILE"
                )

                st.write(
                    "Review the extracted transactions "
                    "before importing into QuickBooks."
                )

        st.divider()

        csv = edited_df.to_csv(
            index=False
        ).encode("utf-8")

        st.download_button(
            "Download QuickBooks CSV",
            csv,
            "td_quickbooks_transactions.csv",
            "text/csv"
        )


st.divider()
st.caption("Tax Square Professional Corporation")
