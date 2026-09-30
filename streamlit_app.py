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


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def clean_amount(value):
    if not value:
        return 0.0

    value = value.replace(",", "").replace("$", "").strip()

    try:
        return float(value)
    except ValueError:
        return 0.0


def extract_statement_year(text):

    match = re.search(
        r'([A-Z]{3})\s*(\d{1,2})/(\d{2})\s*-\s*'
        r'([A-Z]{3})\s*(\d{1,2})/(\d{2})',
        text,
        re.IGNORECASE
    )

    if match:
        return 2000 + int(match.group(6))

    return datetime.now().year


def get_td_control_totals(text):

    credit_match = re.search(
        r'Credits\s+(\d+)\s+([\d,]+\.\d{2})',
        text,
        re.IGNORECASE
    )

    debit_match = re.search(
        r'Debits\s+(\d+)\s+([\d,]+\.\d{2})',
        text,
        re.IGNORECASE
    )

    result = {
        "credit_count": None,
        "credit_total": None,
        "debit_count": None,
        "debit_total": None
    }

    if credit_match:
        result["credit_count"] = int(
            credit_match.group(1)
        )

        result["credit_total"] = clean_amount(
            credit_match.group(2)
        )

    if debit_match:
        result["debit_count"] = int(
            debit_match.group(1)
        )

        result["debit_total"] = clean_amount(
            debit_match.group(2)
        )

    return result


# --------------------------------------------------
# TD PDF EXTRACTION
# --------------------------------------------------

def extract_td_transactions(pdf_bytes):

    doc = fitz.open(
        stream=pdf_bytes,
        filetype="pdf"
    )

    all_transactions = []
    full_text = ""

    for page in doc:

        full_text += page.get_text() + "\n"

        words = page.get_text("words")

        rows = {}

        for word in words:

            x0, y0, x1, y1, text = word[:5]

            # Group words located on approximately
            # the same horizontal line.
            row_key = round(y0 / 3) * 3

            if row_key not in rows:
                rows[row_key] = []

            rows[row_key].append(
                {
                    "x": x0,
                    "text": text
                }
            )

        # ------------------------------------------
        # READ EACH TRANSACTION ROW
        # ------------------------------------------

        for y in sorted(rows.keys()):

            row_words = sorted(
                rows[y],
                key=lambda item: item["x"]
            )

            row_text = " ".join(
                item["text"]
                for item in row_words
            )

            # Find transaction date.
            date_match = re.search(
                r'\b'
                r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)'
                r'(\d{2})'
                r'\b',
                row_text,
                re.IGNORECASE
            )

            if not date_match:
                continue

            if "BALANCE FORWARD" in row_text.upper():
                continue

            month = date_match.group(1).upper()
            day = int(date_match.group(2))

            description_parts = []
            debit_parts = []
            credit_parts = []

            # --------------------------------------
            # TD COLUMN POSITIONS
            # --------------------------------------

            for item in row_words:

                x = item["x"]
                text = item["text"]

                # Ignore date itself.
                if re.fullmatch(
                    r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}',
                    text,
                    re.IGNORECASE
                ):
                    continue

                # DESCRIPTION
                if x < 300:

                    description_parts.append(text)

                # CHEQUE / DEBIT
                elif 300 <= x < 430:

                    if re.fullmatch(
                        r'[\d,]+\.\d{2}',
                        text
                    ):
                        debit_parts.append(text)

                # DEPOSIT / CREDIT
                elif 430 <= x < 555:

                    if re.fullmatch(
                        r'[\d,]+\.\d{2}',
                        text
                    ):
                        credit_parts.append(text)

                # Anything farther right is normally
                # the date/balance area.

            description = " ".join(
                description_parts
            ).strip()

            debit = (
                clean_amount(debit_parts[0])
                if debit_parts
                else 0.0
            )

            credit = (
                clean_amount(credit_parts[0])
                if credit_parts
                else 0.0
            )

            if not description:
                continue

            # --------------------------------------
            # EXCLUDE NON-TRANSACTION ROWS
            # --------------------------------------

            skip_words = [
                "DESCRIPTION",
                "CREDITS",
                "DEBITS",
                "NEXT STATEMENT",
                "MONTHLY AVER",
                "MONTHLY MIN",
                "DEP CONTENT"
            ]

            if any(
                phrase in description.upper()
                for phrase in skip_words
            ):
                continue

            # Must contain a debit or credit.
            if debit == 0 and credit == 0:
                continue

            all_transactions.append(
                {
                    "Month": month,
                    "Day": day,
                    "Description": description,
                    "Debit": debit,
                    "Credit": credit
                }
            )

    # ----------------------------------------------
    # CREATE TRANSACTION DATES
    # ----------------------------------------------

    statement_year = extract_statement_year(
        full_text
    )

    transactions = []

    for item in all_transactions:

        date_text = (
            f"{item['Month']} "
            f"{item['Day']:02d} "
            f"{statement_year}"
        )

        try:

            transaction_date = datetime.strptime(
                date_text,
                "%b %d %Y"
            ).strftime("%Y-%m-%d")

        except ValueError:

            transaction_date = date_text

        transactions.append(
            {
                "Date": transaction_date,
                "Description": item["Description"],
                "Debit": item["Debit"],
                "Credit": item["Credit"]
            }
        )

    controls = get_td_control_totals(
        full_text
    )

    return (
        pd.DataFrame(transactions),
        controls
    )


# --------------------------------------------------
# USER INTERFACE
# --------------------------------------------------

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

    st.success(
        f"Uploaded: {uploaded_file.name}"
    )

    if bank != "TD Canada Trust":

        st.warning(
            "Please select TD Canada Trust."
        )

    elif st.button(
        "Process Statement",
        type="primary"
    ):

        try:

            df, controls = extract_td_transactions(
                uploaded_file.getvalue()
            )

            st.session_state["transactions"] = df
            st.session_state["controls"] = controls

        except Exception as e:

            st.error(
                "The statement could not be processed."
            )

            st.exception(e)


# --------------------------------------------------
# TRANSACTION REVIEW
# --------------------------------------------------

if "transactions" in st.session_state:

    df = st.session_state["transactions"]
    controls = st.session_state["controls"]

    st.divider()

    st.subheader(
        "Transaction Review"
    )

    if df.empty:

        st.error(
            "No transactions were detected."
        )

    else:

        edited_df = st.data_editor(
            df,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True
        )

        # ------------------------------------------
        # CONTROL TOTALS
        # ------------------------------------------

        st.divider()

        st.subheader(
            "Statement Control"
        )

        debit_count = int(
            (edited_df["Debit"] > 0).sum()
        )

        credit_count = int(
            (edited_df["Credit"] > 0).sum()
        )

        debit_total = round(
            edited_df["Debit"].sum(),
            2
        )

        credit_total = round(
            edited_df["Credit"].sum(),
            2
        )

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Transactions",
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

        st.write(
            f"Extracted Debits: "
            f"{debit_count} transactions"
        )

        st.write(
            f"Extracted Credits: "
            f"{credit_count} transactions"
        )

        # ------------------------------------------
        # TD STATEMENT CONTROL TOTALS
        # ------------------------------------------

        expected_debits = controls[
            "debit_count"
        ]

        expected_debit_total = controls[
            "debit_total"
        ]

        expected_credits = controls[
            "credit_count"
        ]

        expected_credit_total = controls[
            "credit_total"
        ]

        if (
            expected_debits is not None
            and expected_credits is not None
        ):

            st.divider()

            st.write(
                f"TD Statement Debits: "
                f"{expected_debits} transactions, "
                f"${expected_debit_total:,.2f}"
            )

            st.write(
                f"TD Statement Credits: "
                f"{expected_credits} transactions, "
                f"${expected_credit_total:,.2f}"
            )

            debit_match = (
                debit_count == expected_debits
                and
                abs(
                    debit_total
                    - expected_debit_total
                ) < 0.01
            )

            credit_match = (
                credit_count == expected_credits
                and
                abs(
                    credit_total
                    - expected_credit_total
                ) < 0.01
            )

            # --------------------------------------
            # RECONCILIATION RESULT
            # --------------------------------------

            if debit_match and credit_match:

                st.success(
                    "✓ STATEMENT RECONCILED"
                )

            else:

                st.error(
                    "⚠ STATEMENT DOES NOT RECONCILE"
                )

                if not debit_match:

                    st.write(
                        "Debit difference: "
                        f"${debit_total - expected_debit_total:,.2f}"
                    )

                if not credit_match:

                    st.write(
                        "Credit difference: "
                        f"${credit_total - expected_credit_total:,.2f}"
                    )

        # ------------------------------------------
        # CSV DOWNLOAD
        # ------------------------------------------

        st.divider()

        csv_data = edited_df.to_csv(
            index=False
        ).encode("utf-8")

        st.download_button(
            "Download QuickBooks CSV",
            csv_data,
            "td_quickbooks_transactions.csv",
            "text/csv"
        )


st.divider()

st.caption(
    "Tax Square Professional Corporation"
)
